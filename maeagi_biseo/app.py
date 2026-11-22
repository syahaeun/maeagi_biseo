from maeagi_biseo.resources import tr, application_icon_path
import sys, random, time
if sys.version_info < (3, 12):
    raise SystemExit(tr('runtime.python_required'))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QIcon, QActionGroup
from PySide6.QtWidgets import QApplication, QWidget, QMenu, QSystemTrayIcon, QMessageBox
from maeagi_biseo.ui.dialogue import DialogueManager
from maeagi_biseo.ui.chat import ChatWindow
from maeagi_biseo.ui.chat_theme import apply_chat_theme
from maeagi_biseo.core.sprites import load_character, default_character, SpriteError
from maeagi_biseo.core.movement import PetMotion
from maeagi_biseo.core.character_profiles import allowed_for
from maeagi_biseo.core.obs_settings import load_obs, normalize_obs
from maeagi_biseo.core.character_catalog import registered_characters
from maeagi_biseo.platforms.windows import keep_above_taskbar
PETS = []
DIALOGUE = None
CHAT = None


class Pet(PetMotion, QWidget):

    def __init__(self, x=None, kind=None, window_tracker=None):
        super().__init__()
        self.kind = kind or default_character()
        self.sprites = load_character(self.kind)
        self.sprite_state = None
        self.sprite_phase = 0
        self.petted_until = 0
        self.init_motion(window_tracker)
        self.allowed_actions = allowed_for(self.kind)
        self.paused = bool(PETS) and all(pet.paused for pet in PETS)
        self.foot_offset = self.sprites.foot_offset
        # OBS excludes WS_EX_TOOLWINDOW windows from its window-capture list.
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.WindowDoesNotAcceptFocus)
        self.setWindowTitle(self.sprites.info.name)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self.sprites.canvas)
        screen = QApplication.primaryScreen().availableGeometry()
        self.area = screen
        self.xpos = float(x if x is not None else random.randint(screen.left(), max(screen.left(), screen.right() - self.width())))
        self.xpos = max(screen.left(), min(self.xpos, screen.right() - self.width() + 1))
        self.ypos = float(screen.bottom() + 1 - self.foot_offset)
        self.direction = random.choice([-1, 1])
        self.state = 'idle'
        self.state_until = time.monotonic() + 2
        self.phase = 0
        self.drag_offset = None
        self.focus = False
        self.affection = 0
        self.broadcast_window = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)
        self.move(int(self.xpos), int(self.ypos))
        self.show()
        self.topmost_timer = QTimer(self)
        self.topmost_timer.timeout.connect(self.ensure_above_taskbar)
        self.topmost_timer.start(500)
        PETS.append(self)
        self.ensure_above_taskbar()
        if CHAT is not None:
            CHAT.refresh_targets()
        self.apply_obs_settings(load_obs(getattr(CHAT, 'store', None)))

    def ensure_above_taskbar(self):
        if QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None:
            visible = [pet for pet in PETS if pet.isVisible()]
            if not visible or self is not visible[-1]:
                return
            # Newest pet stays in front; only one timer maintains the group.
            ordered = list(reversed(visible))
            keep_above_taskbar(ordered[0])
            for front, back in zip(ordered, ordered[1:]):
                keep_above_taskbar(back, behind=front)

    def set_broadcast_enabled(self, enabled=True):
        self.obs_config['enabled'] = bool(enabled)
        if enabled:
            if self.broadcast_window is None:
                from maeagi_biseo.ui.broadcast import BroadcastWindow
                self.broadcast_window = BroadcastWindow(self,
                    lambda: DIALOGUE.bubbles.get(self) if DIALOGUE is not None else None, self.obs_config)
            self.broadcast_window.showNormal()
        elif self.broadcast_window is not None:
            self.broadcast_window.hide()

    def apply_obs_settings(self, config):
        self.obs_config = normalize_obs(config)
        self.set_desktop_motion(self.obs_config['desktop_motion'])
        if self.broadcast_window is not None:
            self.broadcast_window.set_config(self.obs_config)
        self.set_broadcast_enabled(self.obs_config['enabled'])

    def current_sprite_frame(self):
        state = 'pet' if self.state == 'idle' and time.monotonic() < self.petted_until else self.state
        if not self.action_allowed(state):
            state = 'idle'
        if state != self.sprite_state:
            self.sprite_state = state
            self.sprite_phase = self.phase
        return self.sprites.frame(state, (self.phase - self.sprite_phase) * 275)

    def speech_anchor_rect(self):
        top, bottom = self.sprites.frame_artwork_rows(self.current_sprite_frame())
        if self.motion == 'ceiling':
            top, bottom = self.height() - bottom, self.height() - top
        rect = self.geometry()
        rect.setTop(rect.y() + top)
        rect.setHeight(bottom - top)
        return rect

    def paintEvent(self, event):
        image = self.current_sprite_frame()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.motion == 'ceiling':
            painter.translate(self.width(), self.height())
            painter.rotate(180)
        if (self.direction < 0) != (self.sprites.facing == 'left'):
            painter.translate(self.width(), 0)
            painter.scale(-1, 1)
        painter.drawPixmap(0, 0, image)
        painter.end()

    def set_facing(self, direction):
        self.direction = -1 if direction < 0 else 1
        if self.broadcast_window is not None:
            self.broadcast_window.fixed_direction = self.direction
            self.broadcast_window.update()
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.drag_offset = e.globalPosition().toPoint() - self.pos()
            self.drag_origin = e.globalPosition().toPoint()
            self.drag_active = False
            self.drag_samples = []
            self.record_drag()
        elif e.button() == Qt.RightButton:
            self.menu(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if not self.action_allowed('drag'):
            return
        if self.drag_offset is not None:
            if not self.drag_active:
                if (e.globalPosition().toPoint() - self.drag_origin).manhattanLength() < QApplication.startDragDistance():
                    return
                self.drag_active = True
            pt = e.globalPosition().toPoint() - self.drag_offset
            self.move(pt)
            self.xpos = float(pt.x())
            self.ypos = float(pt.y())
            self.record_drag()
            self.state = 'drag'
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self.drag_offset is not None:
                self.drag_offset = None
                if self.drag_active:
                    vx, vy = self.release_velocity()
                    if vx:
                        self.direction = 1 if vx > 0 else -1
                    self.land(vx, vy)
                self.drag_active = False
            if self.action_allowed('pet'):
                self.affection += 1
                self.petted_until = time.monotonic() + 1.2
            if self.motion == 'ground':
                self.state = 'idle'
                self.state_until = time.monotonic() + 1.2
            self.update()

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        # Qt delivers press, release, double-click, release: cancel the drag the second press would start.
        self.drag_offset = None
        self.drag_active = False
        if CHAT is not None:
            CHAT.open_for(self)

    def menu(self, pt):
        menu = self.action_menu()
        try:
            menu.exec(pt)
        finally:
            menu.deleteLater()

    def action_menu(self):
        menu = QMenu(self)
        mode = CHAT.theme_selector.currentData() if CHAT is not None else 'light'
        apply_chat_theme(menu, mode)
        broadcast = menu.addAction(tr('obs.menu'))
        broadcast.setCheckable(True)
        broadcast.setChecked(self.broadcast_window is not None and self.broadcast_window.isVisible())
        broadcast.toggled.connect(self.set_broadcast_enabled)
        facing = menu.addMenu(tr('menu.facing'))
        directions = QActionGroup(facing)
        directions.setExclusive(True)
        for direction,key in ((-1,'menu.face_left'),(1,'menu.face_right')):
            action = facing.addAction(tr(key))
            action.setCheckable(True)
            action.setChecked(self.direction == direction)
            directions.addAction(action)
            action.triggered.connect(lambda checked=False,direction=direction:self.set_facing(direction))
        menu.addSeparator()
        if CHAT is not None:
            menu.addAction(tr('tray.chat'), lambda: CHAT.open_for(self))
            menu.addAction(tr('menu.pet_settings'), lambda: CHAT.settings(self))
            menu.addSeparator()
        for state in ('idle', 'walk', 'sleep', 'hop'):
            if self.action_allowed(state):
                menu.addAction(tr('action.' + state), lambda checked=False, state=state: self.set_state(state))
        if self.action_allowed('climb') and self.action_allowed('walk'):
            menu.addAction(tr('menu.climb'), self.request_climb)
        if self.action_allowed('talk'):
            menu.addAction(tr('menu.friend_chat'), self.talk_to_friend)
        menu.addSeparator()
        pause = menu.addAction(tr('menu.pause'))
        pause.setCheckable(True)
        pause.setChecked(self.paused)
        pause.triggered.connect(self.set_paused)
        focus = menu.addAction(tr('menu.focus'))
        focus.setCheckable(True)
        focus.setChecked(self.focus)
        focus.triggered.connect(self.set_focus)
        menu.addSeparator()
        menu.addAction(tr('menu.close_pet'), self.close_pet)
        menu.addAction(tr('menu.quit'), QApplication.quit)
        return menu

    def talk_to_friend(self):
        if DIALOGUE is None or DIALOGUE.active:
            return
        friends = [p for p in PETS if p is not self and p.drag_offset is None]
        if friends:
            DIALOGUE.start(self, min(friends, key=lambda p: abs(p.x() - self.x())))

    def set_state(self, s):
        if not self.action_allowed(s):
            return
        if s == 'hop':
            self.start_jump()
            return
        if self.motion != 'ground':
            return
        self.state = s
        self.state_until = time.monotonic() + 5

    def set_focus(self, v):
        self.focus = v
        self.climb_requested = False
        if v and self.motion in ('wall', 'ceiling'):
            self.begin_fall()
        self.set_state('idle')

    def close_pet(self):
        if self.broadcast_window is not None:
            self.broadcast_window.close()
            self.broadcast_window.deleteLater()
            self.broadcast_window = None
        self.timer.stop()
        self.topmost_timer.stop()
        if self in PETS:
            PETS.remove(self)
        if CHAT is not None:
            CHAT.refresh_targets()
        self.close()
        self.deleteLater()
        if not PETS:
            QApplication.quit()

def spawn_pet(x=None, kind=None):
    try:
        return Pet(x, kind)
    except SpriteError as exc:
        QMessageBox.warning(None, tr('sprites.error_title'), str(exc))
        return None


def close_removed_character(identifier):
    affected = [pet for pet in PETS if pet.kind == identifier]
    if affected and len(affected) == len(PETS):
        spawn_pet(kind=default_character())
    for pet in affected:
        pet.close_pet()
    if CHAT is not None:
        CHAT.refresh_targets()


def edit_characters(parent=None, identifier=None):
    from maeagi_biseo.ui.character_editor import CharacterEditor
    from PySide6.QtWidgets import QDialog
    parent = parent if isinstance(parent, QWidget) else CHAT
    dialog = CharacterEditor(parent, selected_identifier=identifier,
                             catalog_store=getattr(parent, 'catalog_store', None))
    dialog.characterDeleted.connect(close_removed_character)
    if dialog.exec() == QDialog.Accepted:
        for pet in PETS:
            if pet.kind == dialog.identifier:
                feet = pet.ypos + pet.foot_offset
                pet.sprites = load_character(pet.kind)
                pet.setWindowTitle(pet.sprites.info.name)
                pet.foot_offset = pet.sprites.foot_offset
                pet.setFixedSize(pet.sprites.canvas)
                pet.ypos = feet - pet.foot_offset
                pet.xpos = max(pet.area.left(), min(pet.xpos, pet.area.right() - pet.width() + 1))
                if pet.motion == 'wall':
                    pet.xpos = float(pet.area.left() if pet.wall_side < 0 else pet.area.right() - pet.width() + 1)
                pet.move(round(pet.xpos), round(pet.ypos))
                pet.sprite_state = None
                pet.update()
        if not any(pet.kind == dialog.identifier for pet in PETS):
            spawn_pet(kind=dialog.identifier)
    dialog.deleteLater()


def character_menu(menu, x=None):
    submenu = menu.addMenu(tr('menu.add_character'))
    for identifier, info in registered_characters().items():
        submenu.addAction(info.name, lambda checked=False, name=identifier: spawn_pet(x, name))
    return submenu


def main():
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('MaeagiBiseo.App')
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(application_icon_path())))
    from maeagi_biseo.ui.window_chrome import install_window_chrome
    install_window_chrome()
    app.setQuitOnLastWindowClosed(False)
    global DIALOGUE, CHAT
    try:
        pet = spawn_pet(kind=default_character())
    except SpriteError as exc:
        QMessageBox.warning(None, tr('sprites.error_title'), str(exc))
        return
    if pet is None:
        return
    DIALOGUE = DialogueManager(PETS)
    CHAT = ChatWindow(PETS, DIALOGUE)
    from maeagi_biseo.core.updates import UpdateChecker
    CHAT.updates = UpdateChecker(CHAT)
    app.aboutToQuit.connect(CHAT.shutdown)
    tray = QSystemTrayIcon(QIcon(str(application_icon_path(tray=True))), app)
    menu = QMenu()
    menu.addAction(tr('tray.chat'), lambda: CHAT.open_for())
    menu.addAction(tr('common.settings'), CHAT.settings)
    menu.addAction(tr('updates.check'), lambda: CHAT.open_updates(check=True))
    menu.addAction(tr('obs.open_all'), lambda: [pet.set_broadcast_enabled() for pet in PETS])
    character_menu(menu)
    menu.addAction(tr('menu.edit_characters'), edit_characters)
    pause_all = menu.addAction(tr('tray.pause_all'))
    pause_all.setCheckable(True)
    pause_all.triggered.connect(lambda value: [pet.set_paused(value) for pet in PETS])
    menu.addAction(tr('tray.recover_all'), lambda: [pet.go_to_floor() for pet in PETS])
    menu.addAction(tr('tray.quit'), app.quit)
    tray.setContextMenu(menu)
    # Rebuild the character submenu so registrations and hidden entries update.
    for action in menu.actions():
        if action.menu() is not None:
            submenu = action.menu()
            def refresh_characters(submenu=submenu):
                submenu.clear()
                for identifier, info in registered_characters().items():
                    submenu.addAction(info.name, lambda checked=False, name=identifier: spawn_pet(kind=name))
            submenu.aboutToShow.connect(refresh_characters)
    tray.setToolTip(tr('tray.tooltip'))
    CHAT.updates.notification.connect(lambda tag: tray.showMessage(
        tr('updates.notification_title'), tr('updates.notification_text', version=tag),
        QIcon(str(application_icon_path(tray=True))),
    ))
    tray.messageClicked.connect(CHAT.open_updates)
    tray.show()
    QTimer.singleShot(0, lambda: CHAT.updates.check(automatic=True))
    CHAT.open_for(pet)
    sys.exit(app.exec())
if __name__ == '__main__':
    main()

