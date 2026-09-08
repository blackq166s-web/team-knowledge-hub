"""Windows current-user DPAPI storage. No plaintext key is written to disk."""
import ctypes
import os
import uuid
from ctypes import wintypes


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(value: bytes, decrypt=False) -> bytes:
    if os.name != "nt":
        raise ValueError("本机加密保存目前仅支持 Windows。")
    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
            raise ValueError("无法读取或保存本机密钥，请在系统设置中重新配置。")
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.memset(buffer, 0, len(buffer))
        if output.data:
            ctypes.memset(output.data, 0, output.size)
            kernel.LocalFree(output.data)


def key_path(root):
    return root / "data/app/deepseek.dpapi"


def load_key(root):
    path = key_path(root)
    if not path.exists():
        return ""
    try:
        return _crypt(path.read_bytes(), decrypt=True).decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("本机密钥无法读取，请重新配置。") from exc


def save_key(root, key):
    key = key.strip()
    if not key or len(key) > 4096 or "\n" in key or "\r" in key:
        raise ValueError("请输入有效的 API Key。")
    encrypted = _crypt(key.encode("utf-8"))
    path = key_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(encrypted)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def delete_key(root):
    key_path(root).unlink(missing_ok=True)
