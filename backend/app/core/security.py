"""Single-user authentication, sessions, CSRF protection and login rate limiting."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import AppError, Unauthorized
from app.models import User, UserSession

SESSION_COOKIE = "ft_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "finance-tracker"
_hasher = PasswordHasher()


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, pw)
    except (VerificationError, InvalidHashError):
        return False


def validate_password_strength(pw: str) -> None:
    if len(pw) < 10:
        raise AppError("Password must be at least 10 characters", code="weak_password")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    hours = get_settings().session_hours
    db.add(UserSession(token_hash=_token_hash(token), user_id=user.id,
                       expires_at=datetime.now(timezone.utc) + timedelta(hours=hours)))
    db.execute(delete(UserSession).where(UserSession.expires_at < datetime.now(timezone.utc)))
    db.commit()
    return token


def end_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(UserSession).where(UserSession.token_hash == _token_hash(token)))
        db.commit()


def session_user(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    s = db.get(UserSession, _token_hash(token))
    if s is None or s.expires_at < datetime.now(timezone.utc):
        return None
    return db.get(User, s.user_id)


def require_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    if not get_settings().auth_enabled:
        return None
    user = session_user(db, request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise Unauthorized("Sign in required")
    return user


def user_exists(db: Session) -> bool:
    return db.scalar(select(User.id).limit(1)) is not None


class LoginRateLimiter:
    """In-memory limiter: 5 attempts/minute per client; 10 consecutive failures lock for 5 minutes."""

    def __init__(self, per_minute: int = 5, lock_after: int = 10, lock_seconds: int = 300):
        self.per_minute, self.lock_after, self.lock_seconds = per_minute, lock_after, lock_seconds
        self.attempts: dict[str, deque] = defaultdict(deque)
        self.failures: dict[str, int] = defaultdict(int)
        self.locked_until: dict[str, float] = {}
        self.lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self.lock:
            if self.locked_until.get(key, 0) > now:
                raise AppError("Too many failed sign-in attempts. Try again later.", code="rate_limited", status_code=429)
            q = self.attempts[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                raise AppError("Too many sign-in attempts. Wait a minute.", code="rate_limited", status_code=429)
            q.append(now)

    def result(self, key: str, success: bool) -> None:
        with self.lock:
            if success:
                self.failures.pop(key, None)
                return
            self.failures[key] += 1
            if self.failures[key] >= self.lock_after:
                self.locked_until[key] = time.monotonic() + self.lock_seconds
                self.failures[key] = 0

    def reset(self) -> None:
        with self.lock:
            self.attempts.clear()
            self.failures.clear()
            self.locked_until.clear()


login_limiter = LoginRateLimiter()


class SecurityMiddleware(BaseHTTPMiddleware):
    """CSRF: state-changing API requests must carry X-Requested-With (not sendable cross-site without CORS).
    Adds conservative security headers to every response."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
                return JSONResponse(status_code=403, content={"error": {
                    "code": "csrf", "message": "Missing CSRF header", "details": None}})
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        return response
