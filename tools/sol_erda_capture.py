"""Capture-only Sol Erda diagnostic. No LLM calls or API keys are used."""
import argparse
import ctypes
from ctypes import wintypes as W
from datetime import datetime
import json
from pathlib import Path
import time

import cv2
import numpy as np
from maeagi_biseo.resources import tr
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
CAPTURE_ROOT = ROOT / 'Images' / 'Capture'


def enable_dpi():
    # Same physical-coordinate capture approach as runetimer's pc_capture.
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        ctypes.windll.shcore.SetProcessDpiAwareness(2)


def game_window():
    """Find the largest visible MapleStory client; never fall back to desktop."""
    u = ctypes.windll.user32
    u.GetClientRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
    u.ClientToScreen.argtypes = [W.HWND, ctypes.POINTER(W.POINT)]
    u.IsWindowVisible.argtypes = [W.HWND]
    u.IsIconic.argtypes = [W.HWND]
    u.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
    callback_type = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    u.EnumWindows.argtypes = [callback_type, W.LPARAM]
    found = []

    @callback_type
    def visit(hwnd, _):
        title = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(hwnd, title, len(title))
        if title.value.casefold() == 'maplestory' and u.IsWindowVisible(hwnd) and not u.IsIconic(hwnd):
            rect, point = W.RECT(), W.POINT()
            if u.GetClientRect(hwnd, ctypes.byref(rect)) and u.ClientToScreen(hwnd, ctypes.byref(point)):
                if rect.right >= 320 and rect.bottom >= 240:
                    found.append((hwnd, (point.x, point.y, point.x + rect.right, point.y + rect.bottom)))
        return True

    u.EnumWindows(visit, 0)
    if not found:
        raise RuntimeError('Visible MapleStory window not found. Open the game and Sol Erda UI.')
    return max(found, key=lambda item: (item[1][2]-item[1][0]) * (item[1][3]-item[1][1]))


def game_rect():
    return game_window()[1]


def capture_game(bbox=None):
    """Capture the game window without raising it or copying covering windows."""
    hwnd, client = game_window()
    box = client if bbox is None else bbox
    if not (client[0] <= box[0] < box[2] <= client[2]
            and client[1] <= box[1] < box[3] <= client[3]):
        raise ValueError(tr('capture.window_changed'))
    from maeagi_biseo.platforms.window_capture import capture_window
    image = capture_window(hwnd, client)
    if game_window() != (hwnd, client):
        raise RuntimeError(tr('capture.window_changed'))
    if bbox is not None:
        image = image.crop((box[0]-client[0], box[1]-client[1],
                            box[2]-client[0], box[3]-client[1]))
    if image.size != (box[2]-box[0], box[3]-box[1]):
        raise RuntimeError(tr('capture.window_dimensions'))
    if not any(high for low, high in image.getextrema()):
        raise RuntimeError(tr('capture.window_black'))
    return image


def locate(image, reference, threshold=0.80, anchors=None):
    """Match both stable icons, ignoring changing counts and transparent border."""
    screen = np.asarray(image.convert('RGB'))
    # Reference: 165x65. Both icons provide independent evidence.
    anchors = anchors or [(32, 16, 60, 38), (106, 16, 132, 38)]
    best = None
    for scale in np.arange(0.75, 2.01, 0.05):
        scale = round(float(scale), 2)  # Keep .5 pixel rounding stable across UI layouts.
        template = reference.resize((round(reference.width*scale), round(reference.height*scale)), Image.Resampling.BILINEAR)
        width, height = template.size
        if width > image.width or height > image.height:
            continue
        combined = None
        for ax, ay, bx, by in anchors:
            x, y, right, bottom = [round(v*scale) for v in (ax, ay, bx, by)]
            icon = np.asarray(template.convert('RGB'))[y:bottom, x:right]
            scores = cv2.matchTemplate(screen, icon, cv2.TM_CCOEFF_NORMED)
            aligned = scores[y:y+image.height-height+1, x:x+image.width-width+1]
            combined = aligned.copy() if combined is None else np.minimum(combined, aligned)
        _, score, _, (x, y) = cv2.minMaxLoc(combined)
        candidate = {'score': float(score), 'scale': float(scale), 'box': [x, y, x+width, y+height]}
        if best is None or score > best['score']:
            best = candidate
    if best is None:
        return {'detected': False, 'score': 0.0, 'box': None}
    best['detected'] = best['score'] >= threshold
    return best


def main(kind='sol_erda'):
    meso = kind == 'meso'
    reference_name = 'Meso.png' if meso else 'Sol Erda.png'
    reference_size = (182, 30) if meso else (165, 65)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, help='Offline screenshot instead of live game capture')
    parser.add_argument('--reference', type=Path, default=CAPTURE_ROOT / reference_name)
    from maeagi_biseo.core.runtime_paths import capture_output_root
    parser.add_argument('--output', type=Path, default=capture_output_root() / kind)
    parser.add_argument('--threshold', type=float, default=0.80)
    parser.add_argument('--delay', type=float, default=3, help='Seconds to expose game UI before capture')
    args = parser.parse_args()
    if not 0 < args.threshold <= 1 or args.delay < 0:
        parser.error('threshold must be in (0, 1]; delay must be nonnegative')
    reference = Image.open(args.reference).convert('RGB')
    if reference.size != reference_size and not (meso and reference.size == (207, 27)):
        parser.error(f'Reference must be the original {reference_size}: {reference_name}')
    origin = (0, 0)
    if args.image:
        frame = Image.open(args.image).convert('RGB')
    else:
        enable_dpi()
        print(f'Capturing MapleStory window in {args.delay:g}s. Keep the game UI open.', flush=True)
        time.sleep(args.delay)
        bounds = game_rect()
        origin = bounds[:2]
        frame = capture_game(bounds)
        if frame.size != (bounds[2]-bounds[0], bounds[3]-bounds[1]):
            raise RuntimeError('Unexpected capture dimensions')
    folder = args.output / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    folder.mkdir(parents=True, exist_ok=False)
    frame.save(folder / 'source.png')
    if meso:
        from tools.meso_capture import locate as locate_meso
        result = locate_meso(frame, reference, args.threshold)
    else:
        result = locate(frame, reference, args.threshold)
    result['kind'] = kind
    result['version'] = 2
    result['ocr'] = {'status': 'not_detected', 'value': None}
    result.update(origin=list(origin), threshold=args.threshold, source='offline' if args.image else 'live', reference=str(args.reference.resolve()))
    result['capture_method'] = 'offline_image' if args.image else 'windows_graphics_capture'
    if result['detected']:
        box = result['box']
        result['screen_box'] = [v + origin[i % 2] for i, v in enumerate(box)]
        crop = frame.crop(box)
        from maeagi_biseo.core.local_ocr import read_values
        result['ocr'] = read_values(crop, kind, folder)
        crop.save(folder / f'{kind}.png')
        crop.resize((crop.width*4, crop.height*4), Image.Resampling.NEAREST).save(folder / f'{kind}_4x.png')
        annotated = frame.copy()
        ImageDraw.Draw(annotated).rectangle(box, outline='red', width=3)
        annotated.save(folder / 'detected.png')
    (folder / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    print(f'Artifacts: {folder}')
    return 0 if result['detected'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
