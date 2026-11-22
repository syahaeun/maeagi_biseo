"""Visual placement of a broadcast pet relative to its speech bubble."""
from types import SimpleNamespace
from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QPalette, QTransform
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel
from maeagi_biseo.core.obs_settings import fixed_obs_layout
from maeagi_biseo.core.sprites import load_character, default_character, SpriteError
from maeagi_biseo.resources import tr
from maeagi_biseo.ui.chat_theme import COLORS, appearance_for
from maeagi_biseo.ui.dialogue import Bubble, render_bubble_frame


class PlacementPreview(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setFixedHeight(250)
        self.setMinimumWidth(220)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(tr('obs.placement_accessible'))
        self.drag = None

    def scene(self):
        config = self.editor.config()
        canvas,pet,bubble,below = self.editor.layout_rects(config)
        scale = min(max(1,self.width()-32)/canvas.width(),(self.height()-32)/canvas.height())
        transform = QTransform()
        transform.translate((self.width()-canvas.width()*scale)/2,(self.height()-canvas.height()*scale)/2)
        transform.scale(scale,scale)
        return transform,pet,bubble,below

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        palette = self.palette()
        painter.fillRect(self.rect(), QColor(COLORS[appearance_for(self)]['background']))
        transform,pet,bubble,below = self.scene()
        painter.setTransform(transform)
        fill = palette.color(QPalette.Highlight)
        fill.setAlpha(18)
        painter.fillRect(pet,fill)
        painter.setPen(QPen(palette.color(QPalette.Highlight),1/transform.m11(),Qt.DashLine))
        painter.drawRect(pet)
        if self.editor.sprites is not None:
            image = self.editor.sprites.frame('idle',0)
            source = image.rect()
            source.setTop(self.editor.sprites.idle_top_margin)
            painter.drawPixmap(pet,image,source)
        else:
            painter.drawText(pet,Qt.AlignCenter,tr('obs.preview_pet'))
        frame = render_bubble_frame(self.editor.sample_bubble,self.editor.bubble_copy,pet,bubble,below,
                                    self.editor.config()['bubble_scale']/100)
        painter.drawPixmap(bubble,frame,frame.rect())

    def mousePressEvent(self, event):
        transform,pet,_,_ = self.scene()
        inverse,valid = transform.inverted()
        if event.button() == Qt.LeftButton and valid and pet.contains(inverse.map(event.position()).toPoint()):
            config = self.editor.config()
            self.drag = (event.position(),transform.m11(),config['pet_alignment'],config['pet_gap'],
                         config['bubble_position'])
            self.setCursor(Qt.ClosedHandCursor)
            self.setFocus()

    def mouseMoveEvent(self, event):
        if self.drag is None:
            transform,pet,_,_ = self.scene()
            self.setCursor(Qt.OpenHandCursor if transform.mapRect(QRectF(pet)).contains(event.position()) else Qt.ArrowCursor)
            return
        origin,scale,alignment,gap,side = self.drag
        delta = (event.position()-origin)/scale
        config = self.editor.config()
        _,pet,bubble,_ = self.editor.layout_rects(config)
        span = bubble.width()-pet.width()
        if span > 0:
            self.editor.alignment.setValue(round(alignment+delta.x()/span*100))
        self.editor.gap.setValue(round(gap+delta.y()*(1 if side == 'above' else -1)))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag = None
            self.setCursor(Qt.OpenHandCursor)

    def keyPressEvent(self, event):
        step = 10 if event.modifiers() & Qt.ShiftModifier else 1
        if event.key() in (Qt.Key_Left,Qt.Key_Right):
            self.editor.alignment.setValue(self.editor.alignment.value()+(-step if event.key()==Qt.Key_Left else step))
        elif event.key() in (Qt.Key_Up,Qt.Key_Down):
            direction = -1 if event.key()==Qt.Key_Up else 1
            if self.editor.config()['bubble_position']=='below':
                direction *= -1
            self.editor.gap.setValue(self.editor.gap.value()+direction*step)
        else:
            super().keyPressEvent(event)


class ObsPlacementEditor(QWidget):
    def __init__(self, config_provider, config, parent=None):
        super().__init__(parent)
        self.config = config_provider
        self.sprites = None
        self.setMinimumHeight(560)
        proxy = SimpleNamespace(x=lambda:0,width=lambda:0)
        self.sample_bubble = Bubble(proxy)
        self.sample_bubble.setParent(self,Qt.Widget)
        self.sample_bubble.setText(tr('obs.preview_speech'))
        self.sample_bubble.ensurePolished()
        self.sample_bubble.adjustSize()
        self.sample_bubble.hide()
        self.bubble_copy = Bubble(proxy)
        self.bubble_copy.setParent(self,Qt.Widget)
        self.bubble_copy.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        self.preview = PlacementPreview(self)
        layout.addWidget(self.preview)
        self.zoom_label = QLabel()
        self.zoom_label.setObjectName('settingsSubtitle')
        layout.addWidget(self.zoom_label)
        hint = QLabel(tr('obs.placement_hint'))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QHBoxLayout()
        self.presets = {}
        for value,key in ((0,'obs.align_left'),(50,'obs.align_center'),(100,'obs.align_right')):
            button = QPushButton(tr(key))
            button.clicked.connect(lambda checked=False,value=value:self.alignment.setValue(value))
            self.presets[value] = button
            buttons.addWidget(button)
        reset = QPushButton(tr('obs.placement_reset'))
        reset.clicked.connect(self.reset)
        buttons.addWidget(reset)
        layout.addLayout(buttons)
        layout.addWidget(QLabel(tr('obs.horizontal_placement')))
        self.alignment = QSlider(Qt.Horizontal)
        self.alignment.setAccessibleName(tr('obs.horizontal_placement'))
        self.alignment.setRange(0,100)
        self.alignment.setValue(config['pet_alignment'])
        layout.addWidget(self.alignment)
        self.width_hint = QLabel(tr('obs.placement_width_hint'))
        self.width_hint.setWordWrap(True)
        self.width_hint.hide()
        layout.addWidget(self.width_hint)
        self.gap_label = QLabel()
        layout.addWidget(self.gap_label)
        self.gap = QSlider(Qt.Horizontal)
        self.gap.setAccessibleName(tr('obs.placement_gap'))
        self.gap.setRange(0,200)
        self.gap.setValue(config['pet_gap'])
        layout.addWidget(self.gap)
        self.alignment.valueChanged.connect(self.refresh)
        self.gap.valueChanged.connect(self.refresh)
        self.set_character(default_character())

    def set_character(self, identifier):
        try:
            self.sprites = load_character(identifier or default_character())
        except SpriteError:
            self.sprites = None
        self.refresh()

    def values(self):
        return dict(pet_alignment=self.alignment.value(),pet_gap=self.gap.value())

    def reset(self):
        self.alignment.setValue(50)
        self.gap.setValue(8)

    def refresh(self):
        self.gap_label.setText(tr('obs.gap_value',value=self.gap.value()))
        _,pet,bubble,_ = self.layout_rects(self.config())
        movable = bubble.width() > pet.width()
        self.alignment.setEnabled(movable)
        self.width_hint.setVisible(not movable)
        for button in self.presets.values():
            button.setEnabled(movable)
        self.zoom_label.setText(tr('obs.preview_zoom',value=round(self.preview.scene()[0].m11()*100)))
        self.preview.update()

    def layout_rects(self, config):
        size = QSize(self.sprites.canvas) if self.sprites is not None else QSize(130,155)
        if self.sprites is not None:
            size.setHeight(size.height() - self.sprites.idle_top_margin)
        pet_scale = config['pet_scale']/100
        bubble_scale = config['bubble_scale']/100
        pet = QSize(max(1,round(size.width()*pet_scale)),max(1,round(size.height()*pet_scale)))
        reserve = QSize(max(1,round(300*bubble_scale)),max(1,round(180*bubble_scale)))
        speech = QSize(max(1,round(self.sample_bubble.width()*bubble_scale)),
                       max(1,round(self.sample_bubble.height()*bubble_scale)))
        return fixed_obs_layout(config,pet,reserve,speech)
