"""Legacy artwork is test-only and never part of the application catalog."""
from unittest.mock import patch
from maeagi_biseo.core.sprites import sprite_roots, load_character
from maeagi_biseo.resources import PROJECT_ROOT


def use_character_fixtures(test_class):
    roots = sprite_roots() + [PROJECT_ROOT / 'tests' / 'fixtures' / 'characters']
    replacement = patch('maeagi_biseo.core.sprites.sprite_roots', return_value=roots)
    replacement.start()
    load_character.cache_clear()
    def cleanup():
        replacement.stop()
        load_character.cache_clear()
    test_class.addClassCleanup(cleanup)
