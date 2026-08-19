"""密碼雜湊、Session token、Cookie 處理。"""

import base64
import hashlib
import hmac
import json
import secrets
import time

ITERATIONS = 100_000


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return "pbkdf2${}${}${}".format(
        ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def verify_password(password, stored):
    try:
        _, iters, salt_b64, dk_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iters)
        )
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def _b64sign(secret, payload):
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def make_token(user_id, secret, ttl_seconds=60 * 60 * 24 * 14):
    exp = int(time.time()) + ttl_seconds
    payload = base64.urlsafe_b64encode(
        json.dumps({"uid": user_id, "exp": exp}).encode("utf-8")
    ).rstrip(b"=").decode()
    return "{}.{}".format(payload, _b64sign(secret, payload))


def parse_token(token, secret):
    try:
        payload, sig = token.split(".", 1)
        if not hmac.compare_digest(_b64sign(secret, payload), sig):
            return None
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        data = json.loads(raw)
        if data.get("exp", 0) < int(time.time()):
            return None
        return data.get("uid")
    except Exception:
        return None


def get_cookie(request, name):
    raw = request.headers.get("cookie") or ""
    for part in raw.split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return None


def session_cookie(token, max_age=60 * 60 * 24 * 14):
    return "session={}; Path=/; HttpOnly; SameSite=Lax; Max-Age={}".format(token, max_age)


def clear_session_cookie():
    return "session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
