"""Automatic UI reading with optional client-relative calibration overrides."""
from datetime import datetime
import json
from pathlib import Path


def absolute_region(saved, client):
    size = [client[2]-client[0], client[3]-client[1]]
    if saved.get('client_size') != size:
        raise ValueError('게임 창 크기가 변경됐습니다. 영역을 다시 지정해주세요.')
    x1, y1, x2, y2 = saved['box']
    if not (0 <= x1 < x2 <= size[0] and 0 <= y1 < y2 <= size[1]):
        raise ValueError('저장된 영역이 유효하지 않습니다. 다시 지정해주세요.')
    return (client[0]+x1, client[1]+y1, client[0]+x2, client[1]+y2)


def capture_manual(kind, region, method, config, key, output):
    # Reject legacy/external requests before capturing any screen pixels.
    if method != 'local':
        raise ValueError('이미지 판독은 PC 내부 OCR만 지원합니다.')
    from tools.sol_erda_capture import game_rect, capture_game, CAPTURE_ROOT, locate
    from PIL import Image
    client = game_rect()
    folder = Path(output) / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    folder.mkdir(parents=True)
    warning = None
    box = None
    if region:
        try:
            box = absolute_region(region, client)
        except (ValueError, KeyError, TypeError):
            warning = '저장 영역이 현재 창과 맞지 않아 자동 탐지로 확인했습니다. 필요하면 영역을 재지정하세요.'
    mode = 'manual' if box else 'automatic'
    detection = None
    if box is None:
        frame = capture_game(client)
        with Image.open(CAPTURE_ROOT / ('Meso.png' if kind == 'meso' else 'Sol Erda.png')) as source:
            reference = source.convert('RGB')
        if kind == 'meso':
            from tools.meso_capture import locate as locate_meso
            detection = locate_meso(frame, reference)
        else:
            detection = locate(frame, reference)
        if not detection['detected']:
            frame.save(folder / 'source.png')
            data = {'kind': kind, 'method': method, 'mode': mode, 'detection': detection,
                    'reading': {'status': 'not_detected', 'value': None,
                                'error': 'UI를 찾지 못했습니다. 게임 UI가 보이는지 확인하거나 영역을 재지정하세요.'}}
            (folder / 'result.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            return folder, data
        relative = detection['box']
        image = frame.crop(relative)
        box = tuple(relative[i] + client[i % 2] for i in range(4))
    else:
        image = capture_game(box)
    if image.size != (box[2]-box[0], box[3]-box[1]):
        raise ValueError('캡처 크기가 변경됐습니다. 영역을 다시 지정해주세요.')
    image.save(folder / f'{kind}.png')
    image.resize((image.width*4, image.height*4)).save(folder / f'{kind}_4x.png')
    from maeagi_biseo.core.local_ocr import read_values
    result = read_values(image, kind, folder, number_only=(mode == 'manual'))
    data = {'kind': kind, 'method': method, 'mode': mode, 'region': region, 'screen_box': box,
            'capture_method': 'windows_graphics_capture',
            'reading': result, 'detection': detection, 'region_warning': warning}
    (folder / 'result.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return folder, data
