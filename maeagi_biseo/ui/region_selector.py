"""Select physical pixels on a fitted snapshot of the game client."""
import math
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget, QDialog, QVBoxLayout, QLabel, QDialogButtonBox


class RegionCanvas(QWidget):
    selected = Signal(object)

    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.image = image
        self.start_point = self.end_point = None
        self.setMinimumSize(480, 280)
        self.setCursor(Qt.CrossCursor)

    def image_rect(self):
        scale = min(self.width()/self.image.width(), self.height()/self.image.height())
        w, h = self.image.width()*scale, self.image.height()*scale
        return QRectF((self.width()-w)/2, (self.height()-h)/2, w, h)

    def pixel(self, position):
        rect = self.image_rect()
        return (max(0, min(self.image.width(), (position.x()-rect.x())*self.image.width()/rect.width())),
                max(0, min(self.image.height(), (position.y()-rect.y())*self.image.height()/rect.height())))

    def box(self):
        if self.start_point is None or self.end_point is None:
            return None
        a, b = self.start_point, self.end_point
        box = [math.floor(min(a[0], b[0])), math.floor(min(a[1], b[1])),
               math.ceil(max(a[0], b[0])), math.ceil(max(a[1], b[1]))]
        return box if box[2]-box[0] >= 4 and box[3]-box[1] >= 4 else None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.image_rect().contains(event.position()):
            self.start_point = self.end_point = self.pixel(event.position())
            self.selected.emit(None)
            self.update()

    def mouseMoveEvent(self, event):
        if self.start_point and event.buttons() & Qt.LeftButton:
            self.end_point = self.pixel(event.position())
            self.update()

    def mouseReleaseEvent(self, event):
        if self.start_point and event.button() == Qt.LeftButton:
            self.end_point = self.pixel(event.position())
            self.selected.emit(self.box())
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.black)
        target = self.image_rect()
        painter.drawImage(target, self.image)
        box = self.box()
        if box:
            sx, sy = target.width()/self.image.width(), target.height()/self.image.height()
            painter.setPen(QPen(Qt.red, 2))
            painter.drawRect(QRectF(target.x()+box[0]*sx, target.y()+box[1]*sy,
                                    (box[2]-box[0])*sx, (box[3]-box[1])*sy))


class RegionSelector(QDialog):
    def __init__(self, pil_image, label, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'{label} 판독 영역 지정')
        self.resize(1100, 720)
        image = pil_image.convert('RGB')
        qimage = QImage(image.tobytes(), image.width, image.height, image.width*3, QImage.Format_RGB888).copy()
        layout = QVBoxLayout(self)
        instruction = QLabel('현재 게임 화면에서 숫자와 단위만 드래그하세요. '
                             '메소는 억·만 등을 포함하고, 조각은 오른쪽 보유 수량만 선택하세요. '
                             '숫자가 늘어날 여백도 포함하세요. Esc: 취소')
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        self.canvas = RegionCanvas(qimage)
        layout.addWidget(self.canvas, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText('이 영역 사용')
        self.buttons.button(QDialogButtonBox.Cancel).setText('취소')
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.canvas.selected.connect(lambda box: self.buttons.button(QDialogButtonBox.Ok).setEnabled(box is not None))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
