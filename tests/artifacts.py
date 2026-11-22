"""All generated test pictures and scratch outputs belong under ignored Test/."""
from pathlib import Path
import os
from maeagi_biseo.resources import PROJECT_ROOT


def artifact_path(filename):
    root = Path(os.environ.get('SHIMEJI_TEST_RUN_DIR', PROJECT_ROOT / 'Test')).resolve()
    if not root.is_relative_to((PROJECT_ROOT / 'Test').resolve()):
        raise ValueError('Test runs must stay inside Test')
    target = (root / filename).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError('Artifact path must stay inside Test')
    target.parent.mkdir(parents=True, exist_ok=True)
    return target
