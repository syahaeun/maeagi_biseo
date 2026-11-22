"""Offline, scripted conversations between nearby desktop pets."""
from maeagi_biseo.resources import tr, style, read_json, SCRIPTS
import random
import time
from types import SimpleNamespace
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPen
from PySide6.QtWidgets import QLabel
from maeagi_biseo.core.dialogue_store import dialogue_store, load_scripts


def render_bubble_frame(source, copy, pet_rect, bubble_rect, below, scale):
    """Use the same bubble text, padding and tail in preview and broadcast."""
    copy.setText(source.text())
    copy.setFixedSize(max(source.width(),round(bubble_rect.width()/scale)),source.height())
    copy.setStyleSheet(source.styleSheet())
    copy.appearance = dict(source.appearance)
    copy.tail_on_top = below
    tail_x = (pet_rect.center().x()-bubble_rect.left())/bubble_rect.width()*copy.width()
    copy.pet = SimpleNamespace(x=lambda:tail_x, width=lambda:0)
    copy.move(0,0)
    return copy.grab()


def bubble_position(pet, size, screen, offset=(0, 0)):
    """Shared placement for live bubbles and the editor's screen-edge preview."""
    x = pet.x() + (pet.width() - size.width()) // 2 + offset[0]
    above_y = pet.top() - size.height() - 8
    below = above_y < screen.top()
    if below:
        y = pet.bottom() + 1 + 8 + max(0, offset[1])
    else:
        y = above_y + min(0, offset[1])
    x = max(screen.left(), min(x, screen.right() - size.width() + 1))
    y = max(screen.top(), min(y, screen.bottom() - size.height() + 1))
    return x, y, below


class Bubble(QLabel):

    def __init__(self, pet):
        super().__init__(None)
        self.pet = pet
        self.appearance = read_json('bubble.json')
        self.tail_on_top = False
        self.setObjectName('speechBubble')
        self.pages = []
        self.page_index = 0
        self.page_timer = QTimer(self)
        self.page_timer.timeout.connect(self.next_page)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWordWrap(True)
        self.setTextFormat(Qt.PlainText)
        self.setFixedWidth(300)
        self.refresh_theme()
        self.hide()

    def refresh_theme(self):
        from maeagi_biseo.ui.chat_theme import appearance_for, COLORS
        mode = appearance_for()
        self.appearance = read_json('bubble.json')
        sheet = style('bubble.qss')
        if mode == 'dark':
            colors = COLORS[mode]
            self.appearance.update(background=colors['surface'], border=colors['line'])
            sheet = sheet.replace('#38313c', colors['text'])
        self.setStyleSheet(sheet)
        self.update()

    def paintEvent(self, event):
        # Explicitly paint the background: a translucent top-level QLabel may
        # otherwise show only its text on Windows, despite a QSS background.
        options = self.appearance
        tail = options['tail_height']
        top = tail + 1 if self.tail_on_top else 1
        bottom = self.height() - 1 if self.tail_on_top else self.height() - tail - 1
        body = QRectF(1, top, self.width() - 2, max(1, bottom - top))
        path = QPainterPath()
        path.addRoundedRect(body, options['radius'], options['radius'])
        x = max(24, min(self.width() - 24, self.pet.x() + self.pet.width()/2 - self.x()))
        triangle = QPainterPath()
        edge = body.top() + 1 if self.tail_on_top else body.bottom() - 1
        tip = 1 if self.tail_on_top else self.height() - 1
        triangle.moveTo(x - 9, edge)
        triangle.lineTo(x, tip)
        triangle.lineTo(x + 9, edge)
        triangle.closeSubpath()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(options['background']))
        painter.setPen(QPen(QColor(options['border']), options['border_width']))
        painter.drawPath(path.united(triangle))
        painter.end()
        super().paintEvent(event)

    def say(self, message):
        self.page_timer.stop()
        self.setText(message)
        self.adjustSize()
        self.follow()
        self.show()

    def say_long(self, message):
        self.pages = [message[i:i + 180] for i in range(0, len(message), 180)]
        self.page_index = 0
        self.show_page()

    def show_page(self):
        page = self.pages[self.page_index]
        suffix = tr('bubble.page', current=self.page_index + 1, total=len(self.pages)) if len(self.pages) > 1 else ''
        self.say(page + suffix)
        self.page_timer.start(max(6500, len(page) * 100))

    def next_page(self):
        self.page_index += 1
        if self.page_index < len(self.pages):
            self.show_page()
        else:
            self.page_timer.stop()
            self.hide()

    def follow(self):
        self.setWindowTitle(tr('obs.bubble_title', name=self.pet.sprites.info.name))
        screen = self.pet.screen().availableGeometry()
        sprites = getattr(self.pet, 'sprites', None)
        offset = getattr(sprites, 'bubble_offset', (0, 0))
        anchor = getattr(self.pet, 'speech_anchor_rect', self.pet.geometry)()
        x, y, self.tail_on_top = bubble_position(anchor, self.size(), screen, offset)
        self.move(x, y)
        self.update()

class DialogueManager:

    def __init__(self, pets, settings_store=None):
        self.pets = pets
        self.store = settings_store if settings_store is not None else dialogue_store()
        self.active = None
        self.next_attempt = time.monotonic() + 5
        self.bubbles = {}
        self.user_until = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)

    def tick(self):
        now = time.monotonic()
        for pet, bubble in list(self.bubbles.items()):
            if pet not in self.pets:
                bubble.page_timer.stop()
                bubble.close()
                bubble.deleteLater()
                del self.bubbles[pet]
            elif bubble.isVisible():
                bubble.follow()
        if self.active:
            a, b, lines, index, deadline = self.active
            if a not in self.pets or b not in self.pets or not a.can_talk() or not b.can_talk():
                self.finish()
            elif now >= deadline:
                self.advance()
            return
        if now < self.user_until:
            return
        if now < self.next_attempt:
            return
        self.next_attempt = now + random.uniform(7, 13)
        available = [p for p in self.pets if p.can_talk()]
        pairs = [(a, b) for i, a in enumerate(available) for b in available[i + 1:] if abs(a.x() + a.width()/2 - (b.x() + b.width()/2)) <= 240 and abs(a.y() - b.y()) <= 90]
        if pairs and random.random() < 0.65:
            self.start(*random.choice(pairs))

    def start(self, a, b):
        if self.active or time.monotonic() < self.user_until or a is b or (a not in self.pets) or (b not in self.pets):
            return
        if not a.can_talk() or not b.can_talk():
            return
        scripts = load_scripts(self.store)
        if not scripts:
            return
        lines = random.choice(scripts)
        for pet in (a, b):
            pet.state = 'talk'
            pet.state_until = float('inf')
        a.direction = 1 if b.x() > a.x() else -1
        b.direction = -a.direction
        self.active = (a, b, lines, 0, time.monotonic() + 2.5)
        self.bubble(a).say(lines[0])

    def bubble(self, pet):
        if pet not in self.bubbles:
            self.bubbles[pet] = Bubble(pet)
        return self.bubbles[pet]

    def say_to_user(self, pet, message):
        self.finish()
        for bubble in self.bubbles.values():
            bubble.page_timer.stop()
            bubble.hide()
        bubble = self.bubble(pet)
        bubble.say_long(message)
        self.user_until = time.monotonic() + sum((max(6.5, len(page) * 0.1) for page in bubble.pages)) + 1

    def advance(self):
        a, b, lines, index, _ = self.active
        self.bubble(a).hide()
        self.bubble(b).hide()
        index += 1
        if index >= len(lines):
            self.finish()
            return
        speaker = a if index % 2 == 0 else b
        self.bubble(speaker).say(lines[index])
        self.active = (a, b, lines, index, time.monotonic() + 2.5)

    def finish(self):
        if not self.active:
            return
        a, b, _, _, _ = self.active
        for pet in (a, b):
            if pet in self.bubbles:
                self.bubbles[pet].hide()
            if pet in self.pets and pet.state == 'talk':
                pet.state = 'idle'
                pet.state_until = time.monotonic() + random.uniform(2, 4)
        self.active = None
        self.next_attempt = time.monotonic() + random.uniform(12, 22)
