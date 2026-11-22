"""Persist broadcast-only sizing and independent desktop motion preferences."""
import json
from PySide6.QtCore import QSettings, QRect, QSize, QPoint

DEFAULT_OBS = dict(enabled=False, pet_scale=100, bubble_scale=100, position='follow',
                   bubble_position='above', desktop_motion=True, pet_alignment=50, pet_gap=8)


def normalize_obs(value):
    value = value if isinstance(value, dict) else {}
    result = dict(DEFAULT_OBS)
    for key in ('enabled', 'desktop_motion'):
        result[key] = value.get(key, result[key]) is True
    result['position'] = 'fixed' if value.get('position') == 'fixed' else 'follow'
    result['bubble_position'] = 'below' if value.get('bubble_position') == 'below' else 'above'
    for key in ('pet_scale', 'bubble_scale'):
        try:
            result[key] = max(25,min(300,int(value.get(key,result[key]))))
        except (TypeError, ValueError, OverflowError):
            pass
    for key,low,high in (('pet_alignment',0,100),('pet_gap',0,200)):
        try:
            result[key] = max(low,min(high,int(value.get(key,result[key]))))
        except (TypeError,ValueError,OverflowError):
            pass
    return result


def fixed_obs_layout(config, pet_size, reserve_size, bubble_size=None):
    """Align the pet within the bubble's horizontal edges, never beyond them."""
    below = config['bubble_position'] == 'below'
    gap = config['pet_gap']
    reserve_size = QSize(max(reserve_size.width(),pet_size.width()),reserve_size.height())
    pet_x = round((reserve_size.width()-pet_size.width())*max(0,min(100,config['pet_alignment']))/100)
    pet_y = -gap-pet_size.height() if below else reserve_size.height()+gap
    pet = QRect(QPoint(pet_x,pet_y),pet_size)
    reserve = QRect(QPoint(),reserve_size)
    bounds = pet.united(reserve)
    shift = QPoint(16-bounds.left(),16-bounds.top())
    pet.translate(shift)
    bubble = None
    if bubble_size is not None:
        bubble_size = QSize(reserve_size.width(),bubble_size.height())
        x = 0
        y = 0 if below else reserve_size.height()-bubble_size.height()
        bubble = QRect(QPoint(x,y)+shift,bubble_size)
    return bounds.size()+QSize(32,32),pet,bubble,below


def load_obs(store=None):
    store = store if store is not None else QSettings('DesktopShimeji', 'Chat')
    try:
        value = json.loads(str(store.value('obs_settings', '{}')))
    except (ValueError, TypeError):
        value = {}
    return normalize_obs(value)


def save_obs(config, store):
    config = normalize_obs(config)
    store.setValue('obs_settings', json.dumps(config))
    store.sync()
    return config
