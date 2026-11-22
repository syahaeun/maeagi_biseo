"""Manual region controls shared by the meso and fragment settings tabs."""
import json
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QDialog
from maeagi_biseo.resources import tr
from maeagi_biseo.core.runtime_paths import capture_output_root
from maeagi_biseo.ui.capture_notice import CaptureNotice


class CaptureWorker(QThread):
    result = Signal(object)
    error = Signal(str)

    def __init__(self, action, kind, region=None):
        super().__init__(QApplication.instance())
        self.action, self.kind, self.region = action, kind, region
        QApplication.instance().aboutToQuit.connect(self.wait)

    def run(self):
        try:
            if self.action == 'select':
                from tools.sol_erda_capture import game_rect, capture_game
                client = game_rect()
                image = capture_game(client)
                self.result.emit({'image': image, 'client_size': [client[2]-client[0], client[3]-client[1]]})
            else:
                from maeagi_biseo.core.capture_region import capture_manual
                folder, data = capture_manual(self.kind, self.region, 'local', {}, '',
                                               capture_output_root() / 'manual_capture' / self.kind)
                self.result.emit({'folder': folder, 'data': data})
        except Exception as exc:
            self.error.emit(str(exc))


class ManualCaptureControls(QWidget):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.region, self.store = None, None
        self.worker = None
        self.busy = False
        self.capture_notice = CaptureNotice(self)
        layout = QVBoxLayout(self)
        self.region_label = QLabel('지정된 영역이 없습니다.')
        self.region_label.setWordWrap(True)
        row = QVBoxLayout()
        self.select_button = QPushButton('문제 시 영역 재지정 (5초 뒤)')
        self.select_button.setObjectName(f'{host.capture_kind}SelectRegion')
        self.read_button = QPushButton('읽기 확인 (5초 뒤)')
        self.read_button.setObjectName(f'{host.capture_kind}ReadRegion')
        self.read_button.setEnabled(True)
        self.select_button.clicked.connect(lambda: self.schedule('select'))
        self.read_button.clicked.connect(lambda: self.schedule('read'))
        row.addWidget(self.select_button)
        row.addWidget(self.read_button)
        layout.addLayout(row)
        self.reset_button = QPushButton('보정 영역 해제 · 자동 탐지로 복귀')
        self.reset_button.clicked.connect(self.reset_region)
        layout.addWidget(self.region_label)
        layout.addWidget(self.reset_button)
        self.update_label()

    def configure(self, store):
        self.store = store
        try:
            self.region = json.loads(str(store.value(f'region_{self.host.capture_kind}', 'null')))
            if not isinstance(self.region, dict):
                self.region = None
        except ValueError:
            self.region = None
        self.update_label()

    def update_label(self):
        self.region_label.setText('기본: 자동으로 UI를 찾아 읽습니다. 문제가 있을 때만 영역을 재지정하세요.' if not self.region else
            f"보정 영역 사용: {self.region.get('box')} · 창 크기: {self.region.get('client_size')}\n"
            '창 이동은 따라가며, 창 크기가 바뀌면 자동 탐지합니다. UI 배율 변경 시 필요하면 재지정하세요.')
        self.read_button.setEnabled(not self.busy)
        self.region_label.setVisible(bool(self.region))
        self.reset_button.setVisible(bool(self.region))
        self.reset_button.setEnabled(bool(self.region) and not self.busy)

    def reset_region(self):
        self.region = None
        self.update_label()
        self.host.status.setText('자동 탐지로 변경했습니다. 설정의 저장을 누르면 유지됩니다.')

    def save_settings(self):
        self.store.setValue(f'region_{self.host.capture_kind}', json.dumps(self.region))
        self.store.setValue(f'method_{self.host.capture_kind}', 'local')

    def schedule(self, action, delay_ms=5000, restore_after=True):
        if self.busy:
            return
        self.busy = True
        self.restore_after = restore_after
        self.select_button.setEnabled(False)
        self.read_button.setEnabled(False)
        self.reset_button.setEnabled(False)
        self.host.window().showMinimized()
        self.capture_notice.begin(delay_ms, lambda: self.launch(action), self.host.status, tr('capture.reading_now'))

    def cancel_pending(self):
        self.capture_notice.stop()
        self.restore_after = False
        if self.worker is None and self.busy:
            self.done()

    def launch(self, action):
        worker = CaptureWorker(action, self.host.capture_kind, self.region)
        self.worker = worker
        worker.result.connect(self.selected if action == 'select' else self.read_result)
        worker.error.connect(self.failed)
        worker.finished.connect(self.done)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def restore(self):
        if not getattr(self, 'restore_after', True):
            return
        self.host.window().showNormal()
        self.host.window().raise_()
        self.host.window().activateWindow()

    def selected(self, data):
        from maeagi_biseo.ui.region_selector import RegionSelector
        self.capture_notice.stop()
        if not self.restore_after:
            return
        self.restore()
        dialog = RegionSelector(data['image'], self.host.capture_label, self.host.window())
        if dialog.exec() == QDialog.Accepted:
            self.region = {'box': dialog.canvas.box(), 'client_size': data['client_size']}
            self.update_label()
            self.host.status.setText('보정 영역을 지정했습니다. 읽기 확인 후 설정의 저장을 누르세요.')
            # In-memory preview only. The full game screenshot is never sent to an API.
            import io
            stream = io.BytesIO()
            data['image'].crop(self.region['box']).save(stream, format='PNG')
            pixmap = QPixmap()
            pixmap.loadFromData(stream.getvalue())
            self.host.preview.setPixmap(pixmap.scaled(pixmap.width()*3, pixmap.height()*3))
        else:
            self.host.status.setText('영역 지정을 취소했습니다. 기존 영역을 유지합니다.')

    def read_result(self, data):
        self.host.folder = data['folder']
        self.host.folder_button.setEnabled(True)
        result = data['data']['reading']
        preview_path = data['folder'] / f'{self.host.capture_kind}_4x.png'
        if preview_path.is_file():
            self.host.preview.setPixmap(QPixmap(str(preview_path)))
        else:
            self.host.preview.setText('UI를 찾지 못했습니다. 필요하면 영역을 재지정하세요.')
        method = 'PC 내부 OCR'
        unit = '메소' if self.host.capture_kind == 'meso' else '개'
        text = f"{method}: {result['value']:,} {unit}" if result.get('status') == 'ok' else \
            f"{method}: 판독 미확정 · {result.get('error') or result.get('status')}"
        mode = '보정 영역' if data['data'].get('mode') == 'manual' else '자동 탐지'
        if result.get('status') != 'ok':
            text += '\n게임 UI를 확인하거나 문제 시 영역 재지정을 사용하세요.'
        self.host.status.setText(f'{mode} · ' + text + f"\n결과 저장 위치: {data['folder']}" +
                                ('\n' + data['data']['region_warning'] if data['data'].get('region_warning') else ''))
        self.restore()

    def failed(self, error):
        self.host.status.setText('캡처·판독 오류\n' + error)
        self.restore()

    def done(self):
        self.capture_notice.stop()
        self.worker = None
        self.busy = False
        self.select_button.setEnabled(True)
        self.update_label()
