"""Migrate legacy character folder IDs without changing their images."""
import json
from maeagi_biseo.core.sprites import user_character_root, load_character
from maeagi_biseo.core.character_catalog import preferences, set_default
from maeagi_biseo.core.character_profiles import load_profiles, save_profiles
from maeagi_biseo.resources import read_json


def migrate():
    root = user_character_root().resolve()
    renamed = []
    for old, new in read_json('characters.json').get('aliases', {}).items():
        source, destination = (root / old).resolve(), (root / new).resolve()
        if source.parent != root or destination.parent != root:
            raise ValueError('Invalid character migration path')
        if source.is_dir():
            if destination.exists():
                raise ValueError('Destination already exists; refusing to overwrite')
            source.rename(destination)
            renamed.append(new)
    selected, hidden = preferences()
    if selected:
        set_default(selected, hidden)
    save_profiles(load_profiles())
    load_character.cache_clear()
    return {'renamed': renamed, 'default': selected}


if __name__ == '__main__':
    print(json.dumps(migrate()))
