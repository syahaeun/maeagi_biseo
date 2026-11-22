"""Refresh the pinned xBRZ WASM and corresponding GPL source (Python 3.12)."""
import base64
import hashlib
import io
from pathlib import Path
import re
import tarfile
from urllib.request import urlopen

VERSION = '1.1.2'
COMMIT = 'bab2980d2e7db4f292cbc48c459a7398fa4ea643'
INTEGRITY = '+D25u8BowmNmA94a7E6h6u1HCxEOUze06PhAgUGfp1oK26qI7ALkUGyfpilFIc3s2ISkOe0uRBduLW9gLPTXmA=='
ROOT = Path(__file__).resolve().parents[1]


def main():
    with urlopen(f'https://registry.npmjs.org/@kayahr/xbrz/-/xbrz-{VERSION}.tgz', timeout=60) as response:
        data = response.read()
    if base64.b64encode(hashlib.sha512(data).digest()).decode() != INTEGRITY:
        raise ValueError('xBRZ package integrity mismatch')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        javascript = archive.extractfile('package/lib/main/xbrz.wasm.js').read().decode()
        wasm = base64.b64decode(re.search(r'atob\("([A-Za-z0-9+/=]+)"\)', javascript)[1], validate=True)
    destination = ROOT / 'content' / 'xbrz'
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'xbrz.wasm').write_bytes(wasm)
    # Keep the actual AssemblyScript source and build scripts, not just JS bindings.
    with urlopen(f'https://codeload.github.com/kayahr/xbrz/tar.gz/{COMMIT}', timeout=60) as response:
        source_archive = response.read()
    source_root = ROOT / 'third_party' / 'xbrz'
    with tarfile.open(fileobj=io.BytesIO(source_archive), mode='r:gz') as archive:
        for member in archive.getmembers():
            relative = Path(*Path(member.name).parts[1:])
            if not member.isfile() or relative.is_absolute() or '..' in relative.parts:
                continue
            if relative.as_posix() in (
                'src/test/images/yoshi-transparent.png',
                'src/test/images/yoshi-transparent-xbrz-5b-x2.png',
                'src/test/images/yoshi-transparent-xbrz-5b-x4.png',
            ):
                fixture = ROOT / 'tests' / 'fixtures' / 'xbrz' / relative.name
                fixture.parent.mkdir(parents=True, exist_ok=True)
                fixture.write_bytes(archive.extractfile(member).read())
            if not (relative.parts[0] in ('src', 'scripts') or len(relative.parts) == 1):
                continue
            if relative.parts[:2] == ('src', 'test'):
                continue
            target = source_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
    license_root = ROOT / 'licenses' / 'xbrz'
    license_root.mkdir(parents=True, exist_ok=True)
    (license_root / 'LICENSE.md').write_bytes((source_root / 'LICENSE.md').read_bytes())
    print(f'xBRZ {VERSION}: {len(wasm)} bytes; SHA256 {hashlib.sha256(wasm).hexdigest()}')


if __name__ == '__main__':
    main()
