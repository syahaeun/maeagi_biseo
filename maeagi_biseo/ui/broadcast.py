"""A single transparent capture window for a pet and its live speech bubble."""
import time
from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QSize
from PySide6.QtGui import QPainter, QGuiApplication, QPixmap
from PySide6.QtWidgets import QWidget
from maeagi_biseo.resources import tr
from maeagi_biseo.core.obs_settings import normalize_obs, fixed_obs_layout
from maeagi_biseo.ui.dialogue import Bubble, render_bubble_frame
from maeagi_biseo.platforms.windows import park_capture_window


class BroadcastWindow(QWidget):
    def __init__(self, pet, bubble_provider, config=None):
        super().__init__()
        self.pet = pet
        self.bubble_provider = bubble_provider
        self.config = normalize_obs(config)
        self.bubble_reserve = QSize(300,180)
        self.fixed_started = time.monotonic()
        self.fixed_direction = pet.direction
        self.bubble_copy = Bubble(pet)
        self.bubble_copy.setParent(self, Qt.Widget)
        self.bubble_copy.hide()
        # OBS excludes tool windows. Keep a normal, named top-level HWND while
        # allowing mouse input through the desktop-sized transparent surface.
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint |
                            Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.refresh)
        self.refresh()

    def set_config(self, config):
        config = normalize_obs(config)
        if config != self.config:
            self.bubble_reserve = QSize(300,180)
        if config['position'] == 'fixed' and self.config['position'] != 'fixed':
            self.fixed_started = time.monotonic()
            self.fixed_direction = self.pet.direction
        self.config = config
        self.refresh()

    def refresh(self):
        self.setWindowTitle(tr('obs.window_title', name=self.pet.sprites.info.name))
        screen = self.pet.screen()
        if screen is not None:
            if self.config['position'] == 'fixed':
                bubble = self.bubble_provider()
                if bubble is not None and bubble.isVisible():
                    self.bubble_reserve = self.bubble_reserve.expandedTo(bubble.size())
                pet_size,bubble_size = self.fixed_sizes()
                canvas_size = fixed_obs_layout(self.config,pet_size,bubble_size)[0]
                self.canvas_geometry = QRect(QPoint(),canvas_size)
            else:
                self.canvas_geometry = screen.geometry()
            # Keep the capture surface outside the visible desktop so a fixed
            # broadcast position does not create a second visible desktop pet.
            right = max(s.geometry().right() for s in QGuiApplication.screens())+1
            geometry = QRect(QPoint(right+64,self.canvas_geometry.top()),self.canvas_geometry.size())
            if QGuiApplication.platformName() == 'windows' and self.isVisible():
                if self.size() != geometry.size():
                    self.resize(geometry.size())
                if not park_capture_window(self):
                    self.hide()
                    return
            elif self.geometry() != geometry:
                self.setGeometry(geometry)
        self.update()

    def fixed_sizes(self):
        pet_scale = self.config['pet_scale']/100
        bubble_scale = self.config['bubble_scale']/100
        pet_height = self.pet.height() - self.pet.sprites.idle_top_margin
        return (QSize(max(1,round(self.pet.width()*pet_scale)),max(1,round(pet_height*pet_scale))),
                QSize(max(1,round(self.bubble_reserve.width()*bubble_scale)),
                      max(1,round(self.bubble_reserve.height()*bubble_scale))))

    def fixed_layout(self, bubble):
        pet_size,reserve = self.fixed_sizes()
        size = None
        if bubble is not None and bubble.isVisible():
            scale = self.config['bubble_scale']/100
            size = QSize(max(1,round(bubble.width()*scale)),max(1,round(bubble.height()*scale)))
        _,pet_rect,bubble_rect,below = fixed_obs_layout(self.config,pet_size,reserve,size)
        return pet_rect,bubble_rect,below

    def layout_rects(self, bubble):
        if self.config['position'] == 'fixed':
            return self.fixed_layout(bubble)
        scale = min(self.config['pet_scale']/100, self.width()/self.pet.width(),
                    self.height()/self.pet.height())
        size = QSize(max(1, round(self.pet.width()*scale)), max(1, round(self.pet.height()*scale)))
        anchor = self.pet.mapToGlobal(QPoint(self.pet.width()//2,self.pet.foot_offset))-self.canvas_geometry.topLeft()
        x = max(0,min(self.width()-size.width(),anchor.x()-size.width()//2))
        y = max(0,min(self.height()-size.height(),anchor.y()-round(self.pet.foot_offset*scale)))
        pet_rect = QRect(QPoint(x,y),size)
        if bubble is None or not bubble.isVisible():
            return pet_rect, None, False
        bubble_scale = min(self.config['bubble_scale']/100,
                           self.width()/bubble.width(), self.height()/bubble.height())
        bubble_size = QSize(max(1,round(bubble.width()*bubble_scale)),max(1,round(bubble.height()*bubble_scale)))
        bubble_size.setWidth(max(bubble_size.width(),pet_rect.width()))
        offset = getattr(self.pet.sprites, 'bubble_offset', (0, 0))
        bx = pet_rect.x()-round((bubble_size.width()-pet_rect.width())*self.config['pet_alignment']/100)
        bx = max(0,min(self.width()-bubble_size.width(),bx))
        gap = self.config['pet_gap']
        below = self.config['bubble_position'] == 'below'
        by = pet_rect.bottom()+1+gap+offset[1] if below else pet_rect.top()-gap-bubble_size.height()+offset[1]
        if below and by+bubble_size.height() > self.height():
            below = False
            by = pet_rect.top()-gap-bubble_size.height()+offset[1]
        elif not below and by < 0:
            below = True
            by = pet_rect.bottom()+1+gap+offset[1]
        by = max(0,min(self.height()-bubble_size.height(),by))
        return pet_rect, QRect(QPoint(bx,by),bubble_size), below

    def bubble_frame(self, source, pet_rect, bubble_rect, below):
        return render_bubble_frame(source,self.bubble_copy,pet_rect,bubble_rect,below,
                                   self.config['bubble_scale']/100)

    def pet_frame(self):
        if self.config['position'] != 'fixed':
            return self.pet.grab()
        # Broadcast focus mode: idle animation and facing are independent from
        # desktop jumping, falling, climbing, rotation and walking direction.
        ratio = self.devicePixelRatioF()
        frame = QPixmap(self.pet.size()*ratio)
        frame.setDevicePixelRatio(ratio)
        frame.fill(Qt.transparent)
        painter = QPainter(frame)
        image = self.pet.sprites.frame('idle',(time.monotonic()-self.fixed_started)*1000)
        if (self.fixed_direction < 0) != (self.pet.sprites.facing == 'left'):
            painter.translate(self.pet.width(),0)
            painter.scale(-1,1)
        painter.drawPixmap(0,0,image)
        painter.end()
        return frame

    def paintEvent(self, event):
        painter = QPainter(self)
        # Clear the entire frame, including pixels left by movement or a hidden
        # bubble. Render widgets only; never capture the user's desktop.
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.pet.isVisible():
            bubble = self.bubble_provider()
            pet_rect,bubble_rect,below = self.layout_rects(bubble)
            frame = self.pet_frame()
            source = frame.rect()
            if self.config['position'] == 'fixed':
                source.setTop(round(self.pet.sprites.idle_top_margin * frame.devicePixelRatio()))
            painter.drawPixmap(pet_rect,frame,source)
            if bubble_rect is not None:
                frame = self.bubble_frame(bubble,pet_rect,bubble_rect,below)
                painter.drawPixmap(bubble_rect,frame,frame.rect())
        painter.end()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        if self.isVisible():
            self.timer.start()
            # Re-park after Windows has processed restoring/showing the window.
            QTimer.singleShot(0,self.refresh)

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.isVisible() and hasattr(self,'timer'):
            QTimer.singleShot(0,self.refresh)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)
