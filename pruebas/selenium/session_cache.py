"""Sesión de pruebas cifrada para el usuario actual de Windows mediante DPAPI."""

import ctypes
from ctypes import wintypes
from hashlib import sha256
import os
from pathlib import Path


class _Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data, decrypt=False):
    buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = _Blob()
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    operation = library.CryptUnprotectData if decrypt else library.CryptProtectData
    operation.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    operation.restype = wintypes.BOOL
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    release = ctypes.WinDLL('kernel32').LocalFree
    release.argtypes = [ctypes.c_void_p]
    release.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        release(result.data)


def _path(origin, email):
    key = sha256(f'{origin}\n{email}'.encode()).hexdigest()
    return Path(__file__).with_name('.artifacts') / f'session-{key}.bin'


def load(origin, email):
    if os.name != 'nt':
        return None
    try:
        return _crypt(_path(origin, email).read_bytes(), decrypt=True).decode('utf-8')
    except (OSError, UnicodeError):
        return None


def save(origin, email, session):
    if os.name == 'nt':
        path = _path(origin, email)
        path.parent.mkdir(exist_ok=True)
        encrypted = _crypt(session.encode('utf-8'))
        temporary = path.with_suffix(f'.{os.getpid()}.tmp')
        temporary.write_bytes(encrypted)
        temporary.replace(path)


def remove(origin, email):
    _path(origin, email).unlink(missing_ok=True)
