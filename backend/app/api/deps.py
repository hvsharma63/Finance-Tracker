from fastapi import APIRouter, Depends

from app.core.security import require_user


def protected_router(**kwargs) -> APIRouter:
    """Router whose every route requires a signed-in user (when auth is enabled)."""
    return APIRouter(dependencies=[Depends(require_user)], **kwargs)


def paginate(page: int, page_size: int) -> tuple[int, int]:
    page = max(1, page)
    page_size = max(1, min(page_size, 500))
    return (page - 1) * page_size, page_size
