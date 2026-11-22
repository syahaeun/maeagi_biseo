"""Copy the current character's referenced artwork into project resources."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from maeagi_biseo.core.sprites import user_character_root, read_manifest, STATES
from maeagi_biseo.core.character_profiles import load_profiles
from maeagi_biseo.resources import PROJECT_ROOT


def bundle(identifier):
    if Path(identifier).name != identifier or '/' in identifier or '\\' in identifier:
        raise ValueError('Invalid character identifier')
    source = user_character_root() / identifier
    manifest = read_manifest(source)
    if not manifest.get('animations', {}).get('idle', {}).get('frames'):
        raise ValueError('Missing idle frames')
    destination = PROJECT_ROOT / 'Images' / 'Characters' / identifier
    destination.mkdir(parents=True, exist_ok=True)
    files = {}
    for state in STATES:
        for filename in manifest['animations'].get(state, {}).get('frames', []):
            path = (source / filename).resolve()
            if not path.is_relative_to(source.resolve()):
                raise ValueError('Invalid image path')
            files[filename] = path
    for filename, path in files.items():
        target = destination / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(target.read_bytes()).digest():
            raise ValueError('Image verification failed')
    manifest['profile'] = load_profiles().get(identifier, {})
    (destination / 'character.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (PROJECT_ROOT / 'content' / 'characters.json').write_text(json.dumps({'default': identifier}, indent=2), encoding='utf-8')
    return {'identifier': identifier, 'images': len(files), 'bytes': sum(path.stat().st_size for path in files.values()), 'destination': str(destination)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('identifier')
    print(json.dumps(bundle(parser.parse_args().identifier)))
