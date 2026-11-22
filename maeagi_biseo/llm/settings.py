"""Provider profiles and credentials from environment or encrypted user storage."""
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from maeagi_biseo.resources import read_json, PROJECT_ROOT
from maeagi_biseo.llm.key_store import read_key

PROVIDERS = read_json('providers.json')


def user_env_path():
    return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'DesktopShimeji' / '.env'


def legacy_store_env_paths():
    """Store Python's redirected LocalAppData is separate from an EXE's."""
    packages = user_env_path().parent.parent / 'Packages'
    current = f'PythonSoftwareFoundation.Python.{sys.version_info.major}.{sys.version_info.minor}_'
    try:
        folders = sorted(packages.glob('PythonSoftwareFoundation.Python.*'),
                         key=lambda path:(not path.name.startswith(current),path.name))
    except OSError:
        return ()
    return tuple(folder / 'LocalCache' / 'Local' / 'DesktopShimeji' / '.env' for folder in folders)


def default_env_path():
    """Recover adjacent/Store Python .env files without replacing saved data."""
    target = user_env_path()
    if target.exists():
        return target
    legacy_root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else PROJECT_ROOT
    for legacy in (legacy_root / '.env',*legacy_store_env_paths()):
        try:
            data = legacy.read_bytes()
        except OSError:
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as output:
                output.write(data)
        except FileExistsError:
            pass
        except OSError:
            return legacy
        return target
    return target


def env_file_values(directory=None):
    path = default_env_path() if directory is None else Path(directory) / '.env'
    try:
        lines = path.read_text(encoding='utf-8-sig').splitlines()
    except (OSError, UnicodeError):
        return {}
    values = {}
    for line in lines:
        name, separator, value = line.strip().partition('=')
        if not separator or name.startswith('#'):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        values[name.strip()] = value.strip()
    return values


def env_value(name, directory=None):
    return os.environ.get(name, '').strip() or env_file_values(directory).get(name, '')


def key_with_source(provider, directory=None):
    profile = PROVIDERS[provider]
    values = env_file_values(directory)
    for source in (os.environ, values):
        for name in profile['key_env']:
            value = source.get(name, '').strip()
            if value:
                return value, name
    # Compatibility with the earlier app, which stored Gemini keys under this name.
    legacy = profile.get('legacy_key_env')
    if legacy:
        value = os.environ.get(legacy, '').strip() or values.get(legacy, '')
        if value:
            return value, legacy
    saved = read_key(provider)
    return (saved, 'AppData (Windows DPAPI)') if saved else ('', '')


def load_api_key(directory=None, provider='openai'):
    return key_with_source(provider, directory)[0]


def provider_defaults(provider):
    profile = PROVIDERS[provider]
    return dict(provider=provider, api_format=profile['api_format'], base_url=profile['base_url'],
                model=env_value(profile['model_env']) or profile['model'], max_tokens='4096',
                timeout_seconds='90' if provider == 'gemini' else '45')


def normalize_config(config, official=False):
    result = dict(config)
    provider = result.get('provider')
    if provider not in PROVIDERS:
        host = urlparse(result.get('base_url', '')).hostname or ''
        provider = ('gemini' if host == 'generativelanguage.googleapis.com' else
                    'claude' if host == 'api.anthropic.com' else
                    'openai' if host == 'api.openai.com' else
                    'local' if host in ('localhost', '127.0.0.1', '::1') else 'other')
    result = {**provider_defaults(provider), **result, 'provider': provider}
    if provider != 'other':
        result['api_format'] = PROVIDERS[provider]['api_format']
    if not result.get('model', '').strip():
        result['model'] = env_value(PROVIDERS[provider]['model_env'])
    # Migrate a previously saved Gemini OpenAI-compatibility URL to its native API.
    if provider == 'gemini':
        result['base_url'] = result['base_url'].rstrip('/').removesuffix('/openai')
        result['model'] = result['model'].removeprefix('models/')
    if official and provider in ('gemini', 'openai', 'claude'):
        result['base_url'] = PROVIDERS[provider]['base_url']
    return result
