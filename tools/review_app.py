"""Open the production UI with isolated Test settings for desktop interaction QA."""
import sys
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from maeagi_biseo.app import Pet, PETS
from maeagi_biseo.ui.chat import ChatWindow
from maeagi_biseo.ui.dialogue import DialogueManager
from maeagi_biseo.resources import read_json
from tests.artifacts import artifact_path


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    pet = Pet()
    dialogue = DialogueManager(PETS)
    settings = QSettings(str(artifact_path('desktop_review/settings.ini')), QSettings.IniFormat)
    chat = ChatWindow(PETS, dialogue, settings_store=settings)
    chat.setWindowTitle(read_json('test_journey.json')['review_title'])
    app.aboutToQuit.connect(chat.shutdown)
    chat.open_for(pet)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
