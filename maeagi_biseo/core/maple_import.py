"""Fetch official MapleStory avatar frames without exposing credentials."""
import json
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from urllib.request import Request, build_opener, HTTPRedirectHandler

from PySide6.QtGui import QImage
from maeagi_biseo.resources import tr


class MapleImportError(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class MapleClient:
    def __init__(self, key):
        self.key = key.strip()
        self.opener = build_opener(NoRedirect())

    def request(self, url, authenticated=False):
        headers = {'x-nxopen-api-key': self.key} if authenticated else {}
        try:
            with self.opener.open(Request(url, headers=headers), timeout=15) as response:
                data = response.read(8 * 1024 * 1024 + 1)
                if len(data) > 8 * 1024 * 1024:
                    raise MapleImportError(tr('maple.invalid_response'))
                return data
        except HTTPError as exc:
            key = {400: 'not_found', 401: 'key_error', 403: 'key_error', 429: 'rate_limit'}.get(exc.code, 'network_error')
            raise MapleImportError(tr('maple.' + key)) from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise MapleImportError(tr('maple.network_error')) from None

    def api(self, endpoint, **params):
        try:
            data = json.loads(self.request('https://open.api.nexon.com/maplestory/v1/' + endpoint + '?' + urlencode(params), True))
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except MapleImportError:
            raise
        except (ValueError, UnicodeError):
            raise MapleImportError(tr('maple.invalid_response')) from None

    def download(self, name, destination, cancelled=lambda: False):
        name = name.strip()
        if not name:
            raise MapleImportError(tr('maple.name_required'))
        if not self.key:
            raise MapleImportError(tr('maple.key_required'))
        ocid = self.api('id', character_name=name).get('ocid')
        if not isinstance(ocid, str) or not ocid:
            raise MapleImportError(tr('maple.not_found'))
        basic = self.api('character/basic', ocid=ocid)
        url = basic.get('character_image')
        if not isinstance(url, str):
            raise MapleImportError(tr('maple.invalid_response'))
        parts = urlsplit(url)
        if (parts.scheme != 'https' or parts.netloc != 'open.api.nexon.com'
                or not parts.path.startswith('/static/maplestory/character/look/')):
            raise MapleImportError(tr('maple.invalid_response'))
        folder = Path(destination) / uuid.uuid4().hex
        folder.mkdir(parents=True)
        animations = {}
        images = []
        try:
            for state, action, count, delay in (('idle', 'A00', 3, 300), ('walk', 'A02', 4, 140),
                                               ('hop', 'A06', 1, 150), ('climb', 'A08', 2, 180)):
                frames = []
                for index in range(count):
                    if cancelled():
                        raise MapleImportError(tr('maple.cancelled'))
                    params = dict(parse_qsl(parts.query))
                    params.update(action=f'{action}.{index}', emotion='E00', width=300, height=300, x=150, y=250)
                    frame_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), ''))
                    image = QImage.fromData(self.request(frame_url))
                    if image.isNull() or image.width() != 300 or image.height() != 300:
                        raise MapleImportError(tr('maple.invalid_response'))
                    path = folder / f'{state}_{index}.png'
                    if not image.save(str(path)):
                        raise MapleImportError(tr('maple.save_error'))
                    frames.append(str(path))
                    images.append((path, image))
                animations[state] = {'frames': frames, 'frame_ms': delay, 'foot_offset': 250}
            # Use one crop for every action: retain relative pose positions and
            # remove the large API margins that would leave the pet off the wall.
            left, top, right, bottom = 300, 300, -1, -1
            for _, image in images:
                rgba = image.convertToFormat(QImage.Format_RGBA8888)
                alpha = bytes(rgba.constBits())[3::4]
                occupied = [i for i, value in enumerate(alpha) if value]
                if occupied:
                    left = min(left, min(i % 300 for i in occupied))
                    right = max(right, max(i % 300 for i in occupied))
                    top = min(top, occupied[0] // 300)
                    bottom = max(bottom, occupied[-1] // 300)
            if right < left:
                raise MapleImportError(tr('maple.invalid_response'))
            left, top = max(0, min(left - 4, 284)), max(0, min(top - 4, 234))
            right, bottom = min(300, max(right + 5, left + 16)), min(300, max(bottom + 5, 254, top + 16))
            for path, image in images:
                if not image.copy(left, top, right - left, bottom - top).save(str(path)):
                    raise MapleImportError(tr('maple.save_error'))
            for entry in animations.values():
                entry['foot_offset'] = 250 - top
            animations['fall'] = dict(animations['hop'])
            animations['drag'] = dict(animations['hop'])
            animations['ceiling'] = dict(animations['climb'])
            return {'name': basic.get('character_name') or name, 'animations': animations, 'canvas': [right - left, bottom - top]}
        except Exception:
            for path in folder.iterdir():
                path.unlink()
            folder.rmdir()
            raise
