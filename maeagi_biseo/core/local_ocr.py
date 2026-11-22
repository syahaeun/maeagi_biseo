"""V2: local Windows OCR, with conservative numeric parsing and saved evidence."""
import asyncio
from collections import Counter
import re
import unicodedata

from PIL import Image, ImageOps
import numpy as np


def parse_amount(text, kind):
    text = re.sub(r'\s+', '', unicodedata.normalize('NFKC', text)).replace(',', '')
    if kind == 'sol_erda':
        return int(text) if re.fullmatch(r'\d{1,9}', text) else None
    if kind != 'meso':
        raise ValueError('Unknown OCR kind')
    # Windows OCR commonly reads the small UI glyph 억 as 역; retain raw text in evidence.
    text = re.sub(r'(?<=\d)역(?=\d|$)', '억', text)
    if not re.fullmatch(r'(?:\d+조)?(?:\d+억)?(?:\d+만)?\d*', text) or not text:
        return None
    total = 0
    for unit, multiplier in [('조', 10**12), ('억', 10**8), ('만', 10**4)]:
        if unit in text:
            part, text = text.split(unit, 1)
            if not part or (multiplier < 10**12 and int(part) >= 10000):
                return None
            total += int(part) * multiplier
    if total and text and int(text) >= 10000:
        return None
    return total + int(text or '0')


async def recognize_file(path, engine):
    from winrt.windows.storage import StorageFile, FileAccessMode
    from winrt.windows.graphics.imaging import BitmapDecoder, BitmapPixelFormat, BitmapAlphaMode
    file = await StorageFile.get_file_from_path_async(str(path.resolve()))
    stream = await file.open_async(FileAccessMode.READ)
    try:
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async(BitmapPixelFormat.BGRA8, BitmapAlphaMode.IGNORE)
        try:
            result = await engine.recognize_async(bitmap)
            return result.text
        finally:
            bitmap.close()
    finally:
        stream.close()


def number_region(crop, kind):
    base = (96, 43, 149, 58) if kind == 'sol_erda' else (45, 7, 173, 24)
    size = (165, 65) if kind == 'sol_erda' else (182, 30)
    if kind == 'meso' and crop.width / crop.height > 7:
        base, size = (30, 6, 198, 23), (207, 27)
    return tuple(round(v * crop.size[i % 2] / size[i % 2]) for i, v in enumerate(base))


async def _read(crop, kind, folder, number_only=False):
    if kind not in ('meso', 'sol_erda'):
        raise ValueError('Unknown OCR kind')
    engine, tag = None, 'digits'
    if kind == 'meso':
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        languages = [language.language_tag for language in OcrEngine.available_recognizer_languages]
        tag = next((tag for tag in languages if tag.lower().startswith('ko')), None)
        if not tag:
            return {'status': 'unavailable', 'value': None, 'languages': languages,
                    'error': 'Windows OCR Korean language is not installed'}
        engine = OcrEngine.try_create_from_language(Language(tag))
        if engine is None:
            return {'status': 'unavailable', 'value': None, 'error': 'Cannot create Windows OCR engine'}
    # Relative to the detected full UI; never include Sol Erda's left progress count.
    box = number_region(crop, kind)
    if number_only:
        box = (0, 0, crop.width, crop.height)
    number = crop.crop(box).convert('RGB')
    number.save(folder / 'ocr_number.png')
    attempts = []
    digit_engine = None
    if kind == 'sol_erda':
        from rapidocr_onnxruntime import RapidOCR
        digit_engine = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
        # White digit cores are distinct from the purple outline and gray background.
        rgb = np.asarray(number)
        mask = Image.fromarray(np.where(rgb.min(axis=2) >= 200, 0, 255).astype('uint8'))
        ink_box = ImageOps.invert(mask).getbbox()
        if ink_box:
            mask = mask.crop(ink_box)
        number = mask.convert('RGB')
    for scale in (4, 6, 8):
        enlarged = number.resize((number.width*scale, number.height*scale), Image.Resampling.LANCZOS)
        gray = ImageOps.grayscale(enlarged)
        # Normalize polarity: OCR expects dark lettering on a light background.
        for variant, image in [('gray', gray), ('threshold', gray.point(lambda p: 255 if p > 140 else 0))]:
            image = ImageOps.expand(image, border=20, fill=255)
            path = folder / f'ocr_{scale}x_{variant}.png'
            image.save(path)
            confidence = None
            if digit_engine:
                recognized, _ = digit_engine(np.asarray(image.convert('RGB')), use_det=False, use_cls=False, use_rec=True)
                raw = ''.join(item[0] for item in (recognized or []))
                confidence = min((float(item[1]) for item in (recognized or [])), default=0.0)
            else:
                raw = await recognize_file(path, engine)
            value = parse_amount(raw, kind)
            if confidence is not None and confidence < 0.90:
                value = None
            attempts.append({'file': path.name, 'text': raw, 'value': value, 'confidence': confidence})
    votes = Counter(a['value'] for a in attempts if a['value'] is not None)
    # Disagreement is visible and never silently becomes a numeric balance.
    accepted = len(votes) == 1 and next(iter(votes.values())) >= 3
    return {'engine': 'RapidOCR/ONNX CPU' if digit_engine else 'Windows.Media.Ocr', 'language': tag, 'status': 'ok' if accepted else 'uncertain',
            'value': next(iter(votes)) if accepted else None, 'attempts': attempts,
            'number_box': list(box), 'agreement': max(votes.values(), default=0)}


def read_values(crop, kind, folder, number_only=False):
    folder.mkdir(parents=True, exist_ok=True)
    try:
        return asyncio.run(_read(crop, kind, folder, number_only=number_only))
    except Exception as exc:
        return {'status': 'error', 'value': None, 'error': f'{type(exc).__name__}: {exc}'}
