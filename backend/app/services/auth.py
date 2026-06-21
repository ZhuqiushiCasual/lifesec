import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from typing import Optional

from app.config import settings

ACCESS_TOKEN_EXPIRE_DAYS = 30


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${h}"


def verify_password(plain: str, hashed: str) -> bool:
    salt, h = hashed.split("$", 1)
    return hashlib.sha256((salt + plain).encode()).hexdigest() == h


def _sign(data: bytes) -> str:
    return hmac.new(settings.secret_key.encode(), data, hashlib.sha256).hexdigest()


def create_access_token(user_id: str) -> str:
    payload = json.dumps(
        {
            "sub": user_id,
            "exp": (datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)).timestamp(),
        },
        separators=(",", ":"),
    )
    b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = _sign(b64.encode())
    return f"{b64}.{sig}"


def decode_access_token(token: str) -> Optional[str]:
    try:
        b64, sig = token.split(".")
        if _sign(b64.encode()) != sig:
            return None
        payload = json.loads(base64.urlsafe_b64decode(b64 + "=="))
        if payload.get("exp", 0) < datetime.utcnow().timestamp():
            return None
        return payload.get("sub")
    except Exception:
        return None
