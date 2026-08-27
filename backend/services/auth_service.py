from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials


security = HTTPBearer(auto_error=False)


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Validate JWT from Authorization header and return user claims."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        return decode_jwt_token(credentials.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


BCRYPT_ROUNDS = int(os.environ.get("BCRYPT_ROUNDS", "12"))


def hash_password(password: str) -> str:
    """Hash a password using bcrypt with configurable work factor."""
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _get_secret_key() -> str:
    """Return the JWT signing key from env or raise if not configured."""
    secret = os.environ.get("JWT_SECRET_KEY", "").strip()
    if not secret:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set in .env. "
            "Set JWT_SECRET_KEY=<random_string> or run migrate_auth.py."
        )
    return secret


def create_jwt_token(user_id: str, role: str, secret_key: str | None = None, expires_delta: timedelta | None = None, token_version: int | None = None) -> str:
    """Create a JWT with claims: user_id, role, iat, exp, token_version."""
    if expires_delta is None:
        expires_delta = timedelta(hours=24)
    if secret_key is None:
        secret_key = _get_secret_key()
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "role": role,
        "iat": now,
        "exp": now + expires_delta,
    }
    if token_version is not None:
        payload["token_version"] = token_version
    return jwt.encode(payload, secret_key, algorithm="HS256")


def decode_jwt_token(token: str, secret_key: str | None = None) -> dict:
    """Decode and validate a JWT. Returns the claims dict or raises an exception.
    
    If the token contains a 'token_version' claim, it will be verified against
    the current stored version in users.json (revocation support).
    """
    if secret_key is None:
        secret_key = _get_secret_key()
    # jwt.decode raises jwt.ExpiredSignatureError, jwt.InvalidTokenError, etc.
    claims = jwt.decode(token, secret_key, algorithms=["HS256"])
    
    # Verify token_version for revocation support
    token_version = claims.get("token_version")
    if token_version is not None:
        from .user_store import get_user
        user = get_user(claims.get("user_id"))
        if user and user.get("token_version") != token_version:
            raise jwt.InvalidTokenError("Token has been revoked")
    
    return claims
