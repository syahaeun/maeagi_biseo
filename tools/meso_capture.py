"""Local Meso UI capture with support for both supplied UI layouts."""
from PIL import Image
from tools.sol_erda_capture import CAPTURE_ROOT, locate as locate_anchors, main as capture_main

ANCHORS = [(3, 5, 29, 25), (173, 5, 182, 25)]


def locate(image, reference, threshold=0.80):
    # Each layout has independent dimensions: changing width is not uniform scaling.
    references = [(reference, 'Meso2.png' if reference.size == (207, 27) else 'Meso.png')]
    for name in ('Meso.png', 'Meso2.png'):
        if name != references[0][1]:
            with Image.open(CAPTURE_ROOT / name) as source:
                references.append((source.convert('RGB'), name))
    best = None
    for template, name in references:
        wide = template.size == (207, 27)
        anchors = [(3, 5, 29, 25), (198, 5, 207, 25)] if wide else ANCHORS
        candidate = locate_anchors(image, template, threshold, anchors=anchors)
        candidate['layout'] = name
        if best is None or candidate['score'] > best['score']:
            best = candidate
    return best


def main():
    return capture_main(kind='meso')


if __name__ == '__main__':
    raise SystemExit(main())
