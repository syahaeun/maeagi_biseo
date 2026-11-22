"""Settings panel for local Sol Erda capture diagnostics."""
import json
from pathlib import Path
import sys

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QUrl, QSize
from PySide6.QtGui import QDesktopServices, QPixmap, QPainter
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget, QSizePolicy,
)

from maeagi_biseo.resources import PROJECT_ROOT
from maeagi_biseo.ui.manual_capture import ManualCaptureControls


class CapturePreview(QLabel):
    """Keep the original capture and fit it into the available preview area."""
    def __init__(self, text):
        super().__init__(text)
        self.original = QPixmap()
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

    def setPixmap(self, pixmap):
        self.original = QPixmap(pixmap)
        self.fit_image()

    def fit_image(self):
        self.update()

    def sizeHint(self):
        return QSize(200, 120)

    def minimumSizeHint(self):
        return QSize(0, 0)

    def pixmap(self):
        return self.original.scaled(self.contentsRect().size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def paintEvent(self, event):
        if self.original.isNull():
            super().paintEvent(event)
            return
        pixmap = self.pixmap()
        painter = QPainter(self)
        painter.drawPixmap((self.width() - pixmap.width()) // 2, (self.height() - pixmap.height()) // 2, pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_image()

    def clear(self):
        self.original = QPixmap()
        super().clear()

    def setText(self, text):
        self.original = QPixmap()
        super().setText(text)


class SolErdaPanel(QWidget):
    capture_kind = 'sol_erda'
    capture_label = '솔 에르다'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.folder = None
        self.restore_window = False
        layout = QVBoxLayout(self)
        help_text = QLabel(f'{self.capture_label}: 기본은 자동 탐지입니다. 읽기 확인을 눌러 값을 확인하세요. '
                           '문제가 있으면 메소의 숫자·단위 또는 오른쪽 조각 수량을 재지정하세요. '
                           '숫자는 PC 내부 OCR로 판독하며 화면 이미지를 외부로 전송하지 않습니다.')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.manual = ManualCaptureControls(self)
        layout.addWidget(self.manual)
        row = QHBoxLayout()
        self.capture_button = QPushButton('5초 뒤 캡처 확인')
        self.capture_button.setObjectName('captureMeso' if self.capture_kind == 'meso' else 'captureSolErda')
        self.capture_button.clicked.connect(lambda: self.start())
        self.file_button = QPushButton('스크린샷으로 확인')
        self.file_button.clicked.connect(self.choose_image)
        self.folder_button = QPushButton('결과 폴더 열기')
        self.folder_button.setEnabled(False)
        self.folder_button.clicked.connect(self.open_folder)
        for button in (self.capture_button, self.file_button, self.folder_button):
            row.addWidget(button)
        # Live reading uses the shared controls; saved screenshots can also be opened here.
        self.capture_button.hide()
        layout.addLayout(row)
        self.status = QLabel('아직 캡처하지 않았습니다.')
        self.status.setObjectName(f'{self.capture_kind}CaptureStatus')
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status.setMinimumWidth(0)
        self.status.setTextFormat(Qt.PlainText)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.preview = CapturePreview(f'지정한 {self.capture_label} 영역이 여기에 표시됩니다.')
        self.preview.setWordWrap(True)
        self.preview.setObjectName(f'{self.capture_kind}CapturePreview')
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(120)
        layout.addWidget(self.preview, 1)

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(self, '게임 스크린샷 선택', '', 'Images (*.png *.jpg *.jpeg *.bmp)', options=QFileDialog.DontUseNativeDialog)
        if path:
            self.start(path)

    def start(self, image=None):
        if self.process is not None:
            return
        self.folder = None
        self.folder_button.setEnabled(False)
        self.preview.clear()
        self.capture_button.setEnabled(False)
        self.file_button.setEnabled(False)
        self.status.setText('스크린샷을 분석하고 있습니다.' if image else '5초 뒤 캡처합니다. 메이플 창으로 전환해주세요.')
        # Separate process keeps detection off the UI thread.
        process = QProcess(QApplication.instance())
        self.process = process
        process.setWorkingDirectory(str(PROJECT_ROOT))
        executable = Path(sys.executable)
        if executable.name.lower() == 'pythonw.exe':
            executable = executable.with_name('python.exe')
        process.setProgram(str(executable))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert('PYTHONIOENCODING', 'utf-8')
        process.setProcessEnvironment(environment)
        args = ['-m', f'tools.{self.capture_kind}_capture']
        args += ['--image', str(image)] if image else ['--delay', '5']
        process.setArguments(args)
        process.finished.connect(self.finished)
        process.finished.connect(process.deleteLater)
        process.errorOccurred.connect(self.process_error)
        QApplication.instance().aboutToQuit.connect(process.kill)
        self.restore_window = not bool(image)
        if self.restore_window:
            self.window().showMinimized()
        process.start()

    def process_error(self, error):
        if error == QProcess.FailedToStart:
            self.status.setText('캡처 도구를 실행하지 못했습니다. Python 실행 환경을 확인해주세요.')
            self.cleanup()

    def finished(self, exit_code, _exit_status):
        output = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        errors = bytes(self.process.readAllStandardError()).decode('utf-8', errors='replace')
        try:
            paths = [line[len('Artifacts: '):] for line in output.splitlines() if line.startswith('Artifacts: ')]
            if not paths:
                raise ValueError(errors.strip() or output.strip() or f'Exit code: {exit_code}')
            self.folder = Path(paths[-1])
            result = json.loads((self.folder / 'result.json').read_text(encoding='utf-8'))
            self.folder_button.setEnabled(True)
            if result['detected']:
                self.status.setText(f"탐지 성공 · 점수 {result['score']:.3f}\n"
                                    f"화면 좌표: {result['screen_box']}\n저장 위치: {self.folder}")
                self.preview.setPixmap(QPixmap(str(self.folder / f'{self.capture_kind}_4x.png')))
                ocr = result.get('ocr', {})
                if ocr.get('status') == 'ok':
                    unit = '메소' if self.capture_kind == 'meso' else '개'
                    self.status.setText(self.status.text() + f"\n내부 OCR: {ocr['value']:,} {unit}")
                else:
                    self.status.setText(self.status.text() + '\n내부 OCR: 판독 미확정 · ' +
                                        str(ocr.get('error') or ocr.get('status', '미실행')))
            else:
                self.status.setText(f"탐지 실패 · 최고 점수 {result['score']:.3f}\n"
                                    'UI가 보이는지 확인해주세요. 결과 폴더의 source.png에서 실제 캡처를 확인할 수 있습니다.\n'
                                    f'저장 위치: {self.folder}')
                self.preview.setText('탐지한 UI가 없습니다.')
        except (ValueError, OSError, KeyError) as exc:
            message = str(exc)
            if 'ModuleNotFoundError' in message:
                message = '캡처용 패키지가 필요합니다. 프로젝트 폴더에서 다음 명령을 실행해주세요:\n' \
                          f'"{sys.executable}" -m pip install -r requirements.txt\n\n' + message
            self.status.setText('캡처 오류\n' + message[-2500:])
            self.preview.setText('캡처를 완료하지 못했습니다.')
        finally:
            self.cleanup()

    def cleanup(self):
        if self.process is not None:
            self.process.deleteLater()
            self.process = None
        self.capture_button.setEnabled(True)
        self.file_button.setEnabled(True)
        if self.restore_window:
            self.window().showNormal()
            self.window().raise_()
            self.window().activateWindow()
        self.restore_window = False

    def open_folder(self):
        if self.folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder)))


class MesoPanel(SolErdaPanel):
    capture_kind = 'meso'
    capture_label = '보유 메소'
