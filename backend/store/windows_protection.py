from __future__ import annotations

import ctypes
from ctypes import wintypes


class DataBlob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data: bytes, *, protect: bool) -> bytes:
    if not hasattr(ctypes, "WinDLL"):
        raise OSError("Windows veri koruması kullanılamıyor")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    operation.argtypes = [
        ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob),
    ]
    operation.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    backing = ctypes.create_string_buffer(data)
    source = DataBlob(len(data), ctypes.cast(backing, ctypes.POINTER(ctypes.c_ubyte)))
    result = DataBlob()
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise OSError(ctypes.get_last_error(), "Windows veri koruması başarısız")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel32.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))


def protect_key(key: bytes) -> bytes:
    return _crypt(key, protect=True)


def unprotect_key(wrapped: bytes) -> bytes:
    return _crypt(wrapped, protect=False)
