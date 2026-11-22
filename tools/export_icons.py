"""Export transparent artwork as multi-resolution Windows icon resources."""
from pathlib import Path
from PIL import Image
import cv2
import numpy as np


def main():
    root = Path(__file__).resolve().parent.parent
    with Image.open(root / 'icon.png') as source:
        artwork = source.convert('RGBA')
    # Extract only the neutral checkerboard connected to the image boundary.
    # Preserve the original RGB artwork: no generated or repainted pixels.
    pixels = np.array(artwork)
    rgb = pixels[:, :, :3].astype(np.int16)
    neutral = ((rgb.max(axis=2) - rgb.min(axis=2) <= 22)
               & (rgb.min(axis=2) >= 180)).astype(np.uint8)
    _, labels = cv2.connectedComponents(neutral, connectivity=8)
    boundary = np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
    background = np.isin(labels, boundary[boundary != 0])
    pixels[background, 3] = 0
    # Remove narrow checkerboard/matte remnants without repainting the artwork.
    # Keep the character and the two intentionally detached butterflies.
    mask = (pixels[:, :, 3] > 0).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    count, components, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = [index for index in range(1, count)
            if stats[index, cv2.CC_STAT_AREA] >= 100]
    pixels[~np.isin(components, keep), 3] = 0
    artwork = Image.fromarray(pixels)
    # The user-selected cleaned cutout already contains its final alpha.
    approved = root / 'icon-approved.png'
    if approved.is_file():
        with Image.open(approved) as source:
            artwork = source.convert('RGBA')
    artwork = artwork.crop(artwork.getbbox())
    side = max(artwork.size)
    padding = max(1, round(side * .025))
    canvas = Image.new('RGBA', (side + padding * 2, side + padding * 2))
    canvas.alpha_composite(artwork, ((canvas.width-artwork.width)//2,
                                   (canvas.height-artwork.height)//2))
    artwork = canvas
    artwork.save(root / 'icon-app.png')
    assert artwork.getchannel('A').getextrema() == (0, 255)
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    artwork.save(root / 'icon-app.ico', sizes=[(s, s) for s in sizes])
    artwork.save(root / 'icon-tray.ico', sizes=[(s, s) for s in sizes[:7]])
    for name in ('icon-app.ico', 'icon-tray.ico'):
        with Image.open(root / name) as icon:
            print(name, sorted(icon.ico.sizes()))
            for size in icon.ico.sizes():
                assert icon.ico.getimage(size).getchannel('A').getextrema() == (0, 255)


if __name__ == '__main__':
    main()
