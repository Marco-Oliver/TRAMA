"""Protect cloud API keys using Windows DPAPI for the logged-in Windows user.

No password or key is sent to the TRAMA UI after saving. No extra dependencies.
On non-Windows systems the secure GUI key store is deliberately unavailable.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from pathlib import Path

PROVIDERS={"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY", "openrouter": "OPENROUTER_API_KEY"}


def _crypt(payload: bytes, encrypt: bool) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("Armazenamento de chaves pela interface disponível apenas no Windows")
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    api = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    method = api.CryptProtectData if encrypt else api.CryptUnprotectData
    method.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR),
                       ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
                       wintypes.DWORD, ctypes.POINTER(DATA_BLOB)] if not encrypt else [
                       ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR,
                       ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
                       wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
    method.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buf = ctypes.create_string_buffer(payload)
    incoming = DATA_BLOB(len(payload), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    outgoing = DATA_BLOB()
    label = "TRAMA API Keys" if encrypt else ctypes.byref(wintypes.LPWSTR())
    ok = method(ctypes.byref(incoming), label, None, None, None, 1, ctypes.byref(outgoing))
    if not ok:
        raise OSError(ctypes.get_last_error(), "Falha no Windows DPAPI")
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        kernel.LocalFree(outgoing.pbData)


class KeyVault:
    def __init__(self, path: Path):
        self.path = path

    def _load(self):
        if not self.path.is_file():return {}
        try:
            obj=json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError,ValueError):
            return {}
        if not isinstance(obj,dict):return {}
        return {k:v for k,v in obj.items() if k in PROVIDERS and isinstance(v,str)}

    def _save(self, obj:dict):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix="trama-keys-",dir=str(self.path.parent))
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as fp:
                json.dump(obj,fp)
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)

    def configured(self):
        return {k:k in self._load() for k in PROVIDERS}

    def save(self, provider:str, key:str):
        if provider not in PROVIDERS or not isinstance(key,str) or not 8<=len(key.strip())<=400:
            raise ValueError("Provedor ou chave inválidos")
        # Trim accidental whitespace; never log the key.
        obj=self._load()
        obj[provider]=base64.b64encode(_crypt(key.strip().encode("utf-8"),True)).decode("ascii")
        self._save(obj)

    def remove(self, provider:str):
        if provider not in PROVIDERS:raise ValueError("Provedor inválido")
        obj=self._load();obj.pop(provider,None);self._save(obj)

    def get_env(self):
        out={}
        for provider,token in self._load().items():
            try:
                out[PROVIDERS[provider]]=_crypt(base64.b64decode(token,validate=True),False).decode("utf-8")
            except (OSError,UnicodeDecodeError,ValueError):
                # Do not fall back to plaintext or leak encrypted material.
                continue
        return out
