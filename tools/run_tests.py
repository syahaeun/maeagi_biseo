"""Run test tiers in separate processes and retain honest logs/evidence in Test/."""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from maeagi_biseo.resources import PROJECT_ROOT

SUITES = {
    'unit': ['discover', '-s', 'tests/unit', '-t', '.', '-v'],
    'api': ['tests.integration.test_gemini_live', 'tests.integration.test_farming_tools_live', '-v'],
    'native': ['tests.integration.test_native_windows', '-v'],
    'ui': ['tests.ui.test_user_journey', '-v'],
    'sol-erda': ['tests.unit.test_sol_erda_capture', 'tests.ui.test_sol_erda_settings', '-v'],
    'meso': ['tests.unit.test_meso_capture', 'tests.ui.test_meso_settings', '-v'],
    'ocr': ['tests.unit.test_local_ocr', 'tests.ui.test_meso_settings', 'tests.ui.test_sol_erda_settings', '-v'],
    'capture': ['tests.unit.test_manual_capture', 'tests.ui.test_manual_settings', '-v'],
}


def main():
    parser = argparse.ArgumentParser(description='Run tests and save logs/screenshots under Test/runs')
    parser.add_argument('--suite', choices=[*SUITES, 'all'], default='unit')
    args = parser.parse_args()
    stamp = datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d_%H%M%S_%f')
    folder = PROJECT_ROOT / 'Test' / 'runs' / stamp
    folder.mkdir(parents=True)
    (PROJECT_ROOT / 'Test' / 'latest_run.txt').write_text(str(folder), encoding='utf-8')
    summary = {'run_directory': str(folder), 'suites': []}
    selected = SUITES if args.suite == 'all' else {args.suite: SUITES[args.suite]}
    for name, command in selected.items():
        environment = dict(os.environ, SHIMEJI_TEST_RUN_DIR=str(folder), PYTHONIOENCODING='utf-8')
        environment['QT_QPA_PLATFORM'] = 'windows' if name in ('ui', 'native') and sys.platform == 'win32' else 'offscreen'
        started = time.monotonic()
        print(f'Running {name}; evidence: {folder}', flush=True)
        result = subprocess.run([sys.executable, '-m', 'unittest', *command], cwd=PROJECT_ROOT,
            env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
        log = folder / (name + '.log')
        log.write_text(result.stdout, encoding='utf-8')
        print(result.stdout, end='', flush=True)
        count_match = re.search(r'Ran (\d+) tests?', result.stdout)
        count = int(count_match[1]) if count_match else 0
        status = 'failed' if result.returncode else 'skipped' if count == 0 else 'passed'
        summary['suites'].append({'name': name, 'status': status, 'tests_run': count,
            'returncode': result.returncode, 'elapsed_seconds': round(time.monotonic() - started, 2), 'log': str(log)})
        summary['status'] = 'failed' if any(item['status'] == 'failed' for item in summary['suites']) else (
            'incomplete' if any(item['status'] == 'skipped' for item in summary['suites']) else 'passed')
        (folder / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if summary['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
