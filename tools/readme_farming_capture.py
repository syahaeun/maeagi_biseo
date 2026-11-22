"""Capture actual game readings from a read-only backup of the user's DB."""
import os
import sqlite3
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from maeagi_biseo.core.farming import FarmingStore
from maeagi_biseo.ui.chat import DEFAULTS, SettingsDialog
from tests.artifacts import artifact_path


def main():
    app = QApplication([])
    app.setProperty('appearance', 'dark')
    source = Path(os.environ['LOCALAPPDATA']) / 'Packages/PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0/LocalCache/Local/DesktopShimeji/Farming/records.sqlite3'
    path = artifact_path('readme-farming/actual-readings.sqlite3')
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as original:
        with sqlite3.connect(path) as copy:
            original.backup(copy)
    store = FarmingStore(path)

    def settings(name):
        return QSettings(str(artifact_path(f'readme-farming/{name}.ini')), QSettings.IniFormat)

    dialog = SettingsDialog(DEFAULTS, '', capture_store=settings('capture'),
                            character_store=settings('characters'), catalog_store=settings('catalog'),
                            dialogue_store=settings('dialogue'), farming_store=store)
    dialog.show()
    item = dialog.navigation.item(4)
    QTest.mouseClick(dialog.navigation.viewport(), Qt.LeftButton,
                     pos=dialog.navigation.visualItemRect(item).center())
    QTest.qWait(700)
    assert dialog.farming_panel.isVisible()
    assert dialog.farming_panel.table.rowCount() == 2
    shot = dialog.screen().grabWindow(int(dialog.winId()))
    assert not shot.isNull()
    output = Path('docs/images/farming-records.png')
    assert shot.save(str(output))
    print(f'Saved {output}: {shot.width()}x{shot.height()}, 2 actual reading records')
    dialog.close()


if __name__ == '__main__':
    main()
