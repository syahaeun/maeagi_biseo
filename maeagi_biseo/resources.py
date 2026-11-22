"""Load editable UTF-8 content independently of the current working directory."""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def application_icon_path(*, tray=False):
    """Resolve the shared window/tray icon in source and PyInstaller builds."""
    root = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else PROJECT_ROOT
    return root / ('icon-tray.ico' if tray else 'icon-app.ico')


def resource_path(name):
    if getattr(sys, 'frozen', False):
        external = Path(sys.executable).parent / 'content' / name
        if external.is_file():
            return external
        return Path(sys._MEIPASS) / 'content' / name
    return PROJECT_ROOT / 'content' / name


def read_json(name):
    return json.loads(resource_path(name).read_text(encoding='utf-8-sig'))


TEXTS = read_json('texts.ko.json')
PERSONAS = read_json('personas.json')
DEFAULTS = PERSONAS['defaults']
PRESETS = PERSONAS['presets']
SCRIPTS = read_json('dialogue.ko.json')


def tr(key, **values):
    text = TEXTS[key]
    return text.format(**values) if values else text


def style(name):
    return resource_path(name).read_text(encoding='utf-8-sig')
