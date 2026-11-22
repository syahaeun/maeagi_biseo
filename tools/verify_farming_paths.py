"""Read-only source/frozen storage probe; writes its report only under Test/."""
import json
import os
from pathlib import Path
import sqlite3
import sys

from maeagi_biseo.core.farming import FarmingStore


def inspect(path):
    result = {'path': str(path), 'exists': path.is_file(),
              'resolved': os.path.realpath(path)}
    if result['exists']:
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            result['integrity'] = db.execute('PRAGMA quick_check').fetchone()[0]
            result['sessions'] = db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
    return result


def main():
    output = Path(sys.argv[1]).resolve()
    workspace = Path(sys.argv[2]).resolve()
    if not output.is_relative_to(workspace / 'Test'):
        raise ValueError('Report must be under workspace/Test')
    logical = FarmingStore().path
    package = Path(os.environ['LOCALAPPDATA']) / 'Packages' / 'PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0' / 'LocalCache' / 'Local' / 'DesktopShimeji' / 'Farming' / 'records.sqlite3'
    report = {'frozen': bool(getattr(sys, 'frozen', False)),
              'executable': sys.executable, 'base_prefix': sys.base_prefix,
              'default_database': inspect(logical), 'store_database': inspect(package)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
