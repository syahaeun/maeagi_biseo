"""Shared confirmation for deleting or unregistering a character."""
from PySide6.QtWidgets import QMessageBox

from maeagi_biseo.core.character_catalog import delete_character, registered_characters
from maeagi_biseo.core.sprites import user_character_root
from maeagi_biseo.resources import tr


def removal_action(info):
    if info is not None and info.path.resolve().parent == user_character_root().resolve() and not info.path.is_symlink():
        return 'editor.delete_character'
    return 'editor.remove_character'


def confirm_character_removal(parent, identifier, store=None):
    info = registered_characters(store).get(identifier)
    if info is None:
        return False
    title_key = removal_action(info)
    confirm_key = 'editor.delete_confirm' if title_key == 'editor.delete_character' else 'editor.remove_confirm'
    if QMessageBox.question(parent, tr(title_key), tr(confirm_key, name=info.name),
                            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
        return False
    try:
        delete_character(identifier, store)
    except (OSError, ValueError) as exc:
        QMessageBox.warning(parent, tr(title_key), str(exc))
        return False
    return True
