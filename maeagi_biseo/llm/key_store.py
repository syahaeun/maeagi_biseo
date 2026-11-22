"""User-scoped API credentials encrypted with Windows DPAPI."""
import ctypes
import os
from pathlib import Path
from ctypes import wintypes


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def key_path(provider):
    if not provider or not all(c.isascii() and (c.isalnum() or c == '_') for c in provider):
        raise ValueError('Invalid provider identifier')
    return Path(os.environ['LOCALAPPDATA']) / 'DesktopShimeji' / 'credentials' / (provider + '.dpapi')


def _crypt(data, decrypt=False):
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buffer)
    result = Blob()
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        function = crypt32.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        args = (ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result))
    else:
        function = crypt32.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        args = (ctypes.byref(source), 'DesktopShimeji', None, None, None, 1, ctypes.byref(result))
    function.restype = wintypes.BOOL
    if not function(*args):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel32.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))


def read_key(provider):
    try:
        return _crypt(key_path(provider).read_bytes(), decrypt=True).decode('utf-8')
    except (OSError, UnicodeError, KeyError):
        return ''


def store_key(provider, key):
    path = key_path(provider)
    if not key:
        path.unlink(missing_ok=True)
        return
    encrypted = _crypt(key.encode('utf-8'))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    try:
        temporary.write_bytes(encrypted)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
