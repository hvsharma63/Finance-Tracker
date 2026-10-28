from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import AppError, Conflict, Unauthorized
from app.core.security import (
    SESSION_COOKIE,
    create_session,
    end_session,
    hash_password,
    login_limiter,
    require_user,
    session_user,
    user_exists,
    validate_password_strength,
    verify_password,
)
from app.models import User
from app.services.ledger import audit

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(max_length=256)


def _set_cookie(resp: Response, token: str) -> None:
    s = get_settings()
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", secure=s.cookie_secure,
                    max_age=s.session_hours * 3600, path="/")


@router.get("/status")
def status(request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    if not s.auth_enabled:
        return {"auth_enabled": False, "setup_required": False, "authenticated": True, "username": None}
    user = session_user(db, request.cookies.get(SESSION_COOKIE))
    return {"auth_enabled": True, "setup_required": not user_exists(db), "authenticated": user is not None,
            "username": user.username if user else None}


@router.post("/setup")
def setup(body: Credentials, response: Response, db: Session = Depends(get_db)):
    if user_exists(db):
        raise Conflict("Already set up")
    validate_password_strength(body.password)
    user = User(username=body.username.strip(), password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    audit.record(db, "user", user.id, "created")
    db.commit()
    _set_cookie(response, create_session(db, user))
    return {"username": user.username}


@router.post("/login")
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    key = request.client.host if request.client else "unknown"
    login_limiter.check(key)
    user = db.query(User).filter(User.username == body.username.strip()).one_or_none()
    ok = user is not None and verify_password(body.password, user.password_hash)
    login_limiter.result(key, ok)
    if not ok:
        raise Unauthorized("Invalid username or password")
    _set_cookie(response, create_session(db, user))
    return {"username": user.username}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    end_session(db, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.post("/change-password")
def change_password(body: PasswordChange, request: Request, db: Session = Depends(get_db),
                    user: User | None = Depends(require_user)):
    if user is None:
        raise AppError("Authentication is disabled")
    if not verify_password(body.current_password, user.password_hash):
        raise Unauthorized("Current password is incorrect")
    validate_password_strength(body.new_password)
    user.password_hash = hash_password(body.new_password)
    audit.record(db, "user", user.id, "password_changed")
    db.commit()
    return {"ok": True}
