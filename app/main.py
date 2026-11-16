import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.auth import get_current_user
from app.core.response import ApiError, api_error, api_success
from app.routers import auth, chat, chemistry, files, upload

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="RAG AI助手")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5180",
        "http://127.0.0.1:5180",
    ],
    allow_origin_regex=r"https?://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    logging.info("request %s %s", request.method, request.url.path)
    response = await call_next(request)
    return response


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return api_error(exc.message, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return api_error("请求参数错误", status_code=422)


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logging.exception("Unhandled error", exc_info=exc)
    return api_error("服务器内部错误", status_code=500)


app.include_router(auth.router)
app.include_router(upload.router)
app.include_router(chat.router)
app.include_router(chemistry.router)
app.include_router(files.router)


@app.get("/")
def root():
    return api_success("RAG AI服务运行正常", {"status": "ok"})