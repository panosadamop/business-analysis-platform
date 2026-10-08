"""Structured API errors.

Section 17.3 requires documented error codes for authorization, version
conflicts, invalid mappings and policy blocked egress.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class AppError(HTTPException):
    code = "error"
    status = 400

    def __init__(self, message: str, *, details: Any = None, code: str | None = None,
                 status: int | None = None) -> None:
        super().__init__(status_code=status or self.status, detail=message)
        self.message = message
        self.details = details
        if code:
            self.code = code

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class NotFound(AppError):
    code = "not_found"
    status = 404


class Forbidden(AppError):
    code = "forbidden"
    status = 403


class Unauthorized(AppError):
    code = "unauthorized"
    status = 401


class ValidationFailed(AppError):
    code = "validation_failed"
    status = 422


class VersionConflict(AppError):
    """REQ-APP-04 — an item changed while a decision was being prepared."""

    code = "version_conflict"
    status = 409


class PolicyBlocked(AppError):
    """AT-07 — the egress gate refused to release content."""

    code = "policy_blocked_egress"
    status = 451


class InvalidMapping(AppError):
    code = "invalid_mapping"
    status = 409


class LimitExceeded(AppError):
    code = "limit_exceeded"
    status = 413


class ConflictState(AppError):
    code = "conflict"
    status = 409


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


async def unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": str(exc), "details": None}},
    )
