"""Check the project's GitHub releases without blocking Qt."""
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from maeagi_biseo.resources import PROJECT_ROOT


REPOSITORY_URL = 'https://github.com/syahaeun/maeagi_biseo'
RELEASES_URL = 'https://api.github.com/repos/syahaeun/maeagi_biseo/releases'


def installed_version():
    root = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else PROJECT_ROOT
    project = root / 'pyproject.toml'
    if project.is_file():
        with project.open('rb') as file:
            return tomllib.load(file)['project']['version']
    return version('maeagi-biseo')


def version_number(tag):
    match = isinstance(tag, str) and re.fullmatch(
        r'v?([0-9]+)\.([0-9]+)\.([0-9]+)(?:-beta\.([0-9]+)|b([0-9]+))?', tag
    )
    if not match:
        raise ValueError('Unsupported release tag')
    beta = match[4] or match[5]
    return int(match[1]), int(match[2]), int(match[3]), beta is None, int(beta or 0)


def select_release(entries, candidate=None):
    for entry in entries:
        if not isinstance(entry, dict) or entry.get('draft'):
            continue
        tag = entry.get('tag_name')
        try:
            number = version_number(tag)
        except ValueError:
            continue
        prerelease = bool(entry.get('prerelease'))
        if prerelease == number[3]:
            continue
        if candidate is None or number > version_number(candidate.tag):
            notes = entry.get('body')
            candidate = Release(tag, notes.strip() if isinstance(notes, str) else '', prerelease)
    return candidate


@dataclass(frozen=True)
class Release:
    tag: str
    notes: str
    beta: bool = False

    @property
    def url(self):
        return f'{REPOSITORY_URL}/releases/tag/{self.tag}'


class UpdateChecker(QObject):
    changed = Signal()
    notification = Signal(str)

    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self.store = store if store is not None else QSettings('DesktopShimeji', 'Updates')
        self.version = installed_version()
        self.state = 'idle'
        self.release = None
        self._network = QNetworkAccessManager(self)
        self._reply = None

    @property
    def include_beta(self):
        return self.store.value('includeBeta', False, bool)

    def set_include_beta(self, include):
        if include == self.include_beta:
            return
        self.store.setValue('includeBeta', include)
        if self._reply is not None:
            reply, self._reply = self._reply, None
            reply.abort()
        self.release = None
        self.check()

    @property
    def dismissed(self):
        return self.release is not None and self._recorded('dismissedVersion')

    def _recorded(self, key):
        return self.store.value(key, '', str) == self.release.tag.removeprefix('v')

    def dismiss(self):
        if self.release is not None:
            self.store.setValue('dismissedVersion', self.release.tag.removeprefix('v'))
            self.changed.emit()

    def check(self, *, automatic=False):
        if self._reply is not None:
            return
        self._request(automatic, 1 if self.include_beta else None)
        self.state = 'checking'
        self.changed.emit()

    def _request(self, automatic, page, candidate=None):
        suffix = '/latest' if page is None else f'?per_page=100&page={page}'
        request = QNetworkRequest(QUrl(RELEASES_URL + suffix))
        request.setRawHeader(b'Accept', b'application/vnd.github+json')
        request.setRawHeader(b'User-Agent', b'Maeagi-Biseo')
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy)
        request.setTransferTimeout(8000)
        reply = self._network.get(request)
        self._reply = reply
        reply.finished.connect(lambda: self._finished(reply, automatic, page, candidate))

    def _finished(self, reply, automatic, page, candidate):
        if reply is not self._reply:
            reply.deleteLater()
            return
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        next_page = page is not None and b'rel="next"' in bytes(reply.rawHeader('Link'))
        self._reply = None
        self.state = 'error'
        try:
            if status == 404 and page is None:
                self.release = None
                self.state = 'unpublished'
            elif status == 200 and reply.error() == QNetworkReply.NoError:
                data = json.loads(bytes(reply.readAll()))
                if page is not None and not isinstance(data, list):
                    raise ValueError('Expected a release list')
                if page is None:
                    if not isinstance(data, dict):
                        raise ValueError('Expected a release object')
                    data = [data] if not data.get('prerelease') else []
                candidate = select_release(data, candidate)
                if page is not None and next_page:
                    self.state = 'checking'
                    self._request(automatic, page + 1, candidate)
                    return
                self.release = None
                self.state = 'unpublished' if candidate is None else 'current'
                if candidate is not None and version_number(candidate.tag) > version_number(self.version):
                    self.release = candidate
                    self.state = 'available'
        except (ValueError, TypeError):
            pass
        finally:
            reply.deleteLater()
        self.changed.emit()
        if self.state == 'available' and automatic and not self.dismissed and not self._recorded('notifiedVersion'):
            self.store.setValue('notifiedVersion', self.release.tag.removeprefix('v'))
            self.notification.emit(self.release.tag)
