import base64
import hashlib
import os

_PREFIX = "ENC:"


def _fernet():
    key = os.environ.get("MCP_CREDENTIAL_KEY", "").strip()
    if not key:
        return None
    from cryptography.fernet import Fernet

    try:
        return Fernet(key.encode())
    except Exception:
        digest = hashlib.sha256(key.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


def enc_cred(secret: str) -> str:
    f = _fernet()
    if f is None:
        return secret
    return _PREFIX + f.encrypt(secret.encode()).decode()


def dec_cred(value: str) -> str:
    if not isinstance(value, str) or not value.startswith(_PREFIX):
        return value
    f = _fernet()
    if f is None:
        raise RuntimeError("MCP_CREDENTIAL_KEY is not set; cannot decrypt")
    return f.decrypt(value[len(_PREFIX) :].encode()).decode()
