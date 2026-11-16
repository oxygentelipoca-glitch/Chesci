import json
from datetime import datetime, date
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def api_success(message: str, data: Any = None, status_code: int = 200):
    payload = {
        "code": 0,
        "message": message,
        "data": _json_safe(data),
    }
    return JSONResponse(status_code=status_code, content=payload)


def api_error(message: str, status_code: int = 400):
    return JSONResponse(
        status_code=status_code,
        content={
            "code": status_code,
            "message": message,
            "data": None,
        },
    )


def to_http_exception(exc: Exception):
    if isinstance(exc, ApiError):
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    if isinstance(exc, HTTPException):
        raise exc
    raise HTTPException(status_code=500, detail="服务器内部错误")
