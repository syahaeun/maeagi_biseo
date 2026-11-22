"""Optional local sprite resampling. No network or generated artwork."""
from PIL import Image
import numpy as np


def _scale2x(image):
    """Round connected pixel corners using the four neighboring colors."""
    pixels = np.asarray(image)
    padded = np.pad(pixels, ((1, 1), (1, 1), (0, 0)), mode='edge')
    above, below = padded[:-2, 1:-1], padded[2:, 1:-1]
    left, right = padded[1:-1, :-2], padded[1:-1, 2:]
    equal = lambda a, b: np.all(a == b, axis=2)
    junction = ~equal(above, below) & ~equal(left, right)
    output = np.repeat(np.repeat(pixels, 2, axis=0), 2, axis=1)
    for row, col, a, b in ((0, 0, left, above), (0, 1, above, right),
                            (1, 0, left, below), (1, 1, below, right)):
        mask = junction & equal(a, b)
        output[row::2, col::2][mask] = a[mask]
    return Image.fromarray(output)


def processed_frame(source, factor, smoothing=0):
    """Return the same RGBA pixels used by preview and PNG export."""
    if type(factor) is not int or factor not in (1, 2, 4):
        raise ValueError('Upscale factor must be 1, 2 or 4')
    if type(smoothing) is not int or smoothing not in (0, 1, 2, 3):
        raise ValueError('Invalid smoothing strength')
    with Image.open(source) as image:
        size = (image.width * factor, image.height * factor)
        if max(size) > 8192 or size[0] * size[1] > 16_777_216:
            from maeagi_biseo.resources import tr
            raise ValueError(tr('editor.upscale_too_large'))
        artwork = image.convert('RGBA')
        # Invisible RGB values must not affect connectivity decisions.
        artwork = artwork.convert('RGBa').convert('RGBA')
        if smoothing == 3:
            from maeagi_biseo.core.xbrz import scale_xbrz
            artwork = scale_xbrz(artwork, max(2, factor))
            if artwork.size == size:
                return artwork
        elif smoothing:
            for _ in range(smoothing):
                if artwork.width * artwork.height * 4 > 16_777_216:
                    from maeagi_biseo.resources import tr
                    raise ValueError(tr('editor.upscale_too_large'))
                artwork = _scale2x(artwork)
        # Resample reconstructed contours, rather than blurring the artwork.
        return artwork.convert('RGBa').resize(size, Image.Resampling.LANCZOS).convert('RGBA')


def upscale_frame(source, destination, factor, smoothing=0):
    """Export an RGBA PNG, preserving transparency, with bounded memory use."""
    processed_frame(source, factor, smoothing).save(destination, format='PNG')
