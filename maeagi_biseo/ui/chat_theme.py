"""Chat colors shared by the light and dark appearances."""
from PySide6.QtGui import QColor, QPalette
from maeagi_biseo.resources import style, resource_path


COLORS = {
    'light': {'background': '#f5f7f3', 'surface': '#ffffff', 'text': '#27372e',
              'muted': '#64756a', 'line': '#dce4db', 'hover': '#edf2e9',
              'accent': '#28674f', 'accent_hover': '#20563f', 'accent_text': '#ffffff',
              'user': '#e2eddf', 'rail': '#ffffff', 'rail_text': '#27372e', 'rail_hover': '#edf2e9',
              'dm_bg': '#f1edf7', 'dm_panel': '#fdfbff', 'dm_inbox': '#f7f2fc',
              'dm_line': '#ded3eb', 'dm_hover': '#eee5f7', 'dm_selected': '#e7d8f8',
              'dm_bubble': '#faf5ff', 'dm_outgoing': '#e5d3fa', 'dm_outgoing_text': '#2b1b43',
              'dm_action': '#68469c', 'dm_action_hover': '#593789', 'dm_action_text': '#ffffff',
              'dm_record': '#f4ebfc'},
    'dark': {'background': '#202124', 'surface': '#272829', 'text': '#e3e5e8',
             'muted': '#a6a7ad', 'line': '#3c3d40', 'hover': '#333438',
             'accent': '#1b64da', 'accent_hover': '#2272eb', 'accent_text': '#ffffff',
             'user': '#323437', 'rail': '#272829', 'rail_text': '#e3e5e8', 'rail_hover': '#333438',
             'dm_bg': '#17161e', 'dm_panel': '#20202a', 'dm_inbox': '#25232e',
             'dm_line': '#423b50', 'dm_hover': '#302a3b', 'dm_selected': '#433653',
             'dm_bubble': '#2d2a38', 'dm_outgoing': '#c2a4ef', 'dm_outgoing_text': '#261938',
             'dm_action': '#c5aafd', 'dm_action_hover': '#d6c2fb', 'dm_action_text': '#281941',
             'dm_record': '#33283f'},
}


def appearance_for(widget=None):
    from PySide6.QtWidgets import QApplication
    while widget is not None:
        mode = widget.property('appearance')
        if mode in COLORS:
            return mode
        widget = widget.parentWidget()
    app = QApplication.instance()
    mode = app.property('appearance') if app is not None else None
    return mode if mode in COLORS else 'light'


def apply_chat_theme(widget, mode, *, _propagate=True):
    from maeagi_biseo.ui.window_chrome import install_window_chrome, apply_native_title_bar
    from PySide6.QtWidgets import QApplication
    install_window_chrome()
    mode = mode if mode in COLORS else 'light'
    app = QApplication.instance()
    widget.setProperty('appearance', mode if mode in COLORS else 'light')
    colors = COLORS.get(mode, COLORS['light'])
    sheet = style('chat.qss')
    sheet = sheet.replace('@checkmark@',resource_path('checkmark.png').as_posix())
    for key, value in colors.items():
        sheet = sheet.replace('@' + key + '@', value)
    palette = QPalette(widget.palette())
    for role, key in ((QPalette.Window, 'background'), (QPalette.Base, 'surface'),
                      (QPalette.Text, 'text'), (QPalette.WindowText, 'text'),
                      (QPalette.Button, 'surface'), (QPalette.ButtonText, 'text'),
                      (QPalette.AlternateBase, 'background'), (QPalette.ToolTipBase, 'surface'),
                      (QPalette.ToolTipText, 'text'), (QPalette.Light, 'line'),
                      (QPalette.Midlight, 'hover'), (QPalette.Mid, 'line'),
                      (QPalette.Dark, 'background'), (QPalette.Shadow, 'background'),
                      (QPalette.Link, 'accent'),
                      (QPalette.PlaceholderText, 'muted'), (QPalette.Highlight, 'accent')):
        palette.setColor(role, QColor(colors[key]))
    palette.setColor(QPalette.HighlightedText, QColor(colors['accent_text']))
    widget.setPalette(palette)
    widget.setStyleSheet(sheet)
    if widget.objectName() == 'chat' and _propagate:
        app.setProperty('appearance', mode)
        app.setPalette(palette)
        app.setStyleSheet(sheet)
        for window in app.topLevelWidgets():
            if window is widget:
                continue
            if window.objectName() == 'speechBubble':
                window.refresh_theme()
            elif window.property('appearance') is not None:
                apply_chat_theme(window, mode, _propagate=False)
    if widget.isWindow() and widget.isVisible():
        apply_native_title_bar(widget, colors, mode == 'dark')
