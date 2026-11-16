from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select

security = HTTPBearer(auto_error=False)


def _get_secret() -> str:
    return os.getenv("JWT_SECRET", "dev-secret-key")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16).encode("utf-8")
    derived_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return f"pbkdf2_sha256$100000${salt.decode('utf-8')}${derived_key.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash.startswith("pbkdf2_sha256$"):
        return False

    _, iterations, salt, expected_hash = password_hash.split("$", 3)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        int(iterations),
    )
    return secrets.compare_digest(derived_key.hex(), expected_hash)


def create_access_token(user_id: int, username: str, expires_in_minutes: int = 60 * 24) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "uid": user_id,
        "sub": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_in_minutes)).timestamp()),
    }
    return jwt.encode(payload, _get_secret(), algorithm="HS256")


def verify_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, _get_secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="token 已过期") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="token 无效") from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any]:
    if credentials is None:
        raise HTTPException(status_code=401, detail="缺少认证信息")
    token = credentials.credentials
    payload = verify_access_token(token)
    return payload


def resolve_current_user_id(current_user: dict[str, Any], session: Session) -> int:
    user_id = current_user.get("uid")
    if isinstance(user_id, int):
        return user_id

    username = current_user.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="缺少用户信息")

    from app.models import User

    user = session.exec(select(User).where(User.username == username)).first()
    if user is None or user.id is None:
        raise HTTPException(status_code=401, detail="用户不存在")

    return user.id


def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any] | None:
    """可选认证：无 token 或 token 无效时返回 None（供匿名/记录端点使用）。"""
    if credentials is None:
        return None
    try:
        return verify_access_token(credentials.credentials)
    except HTTPException:
        return None
