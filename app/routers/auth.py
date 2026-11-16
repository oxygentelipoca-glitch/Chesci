from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.auth import create_access_token, get_current_user, hash_password, verify_password
from app.core.response import api_error, api_success
from app.database import engine
from app.models import User

router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str


def _ensure_demo_user() -> User:
    with Session(engine) as session:
        existing_user = session.exec(select(User).where(User.username == "demo")).first()
        if existing_user is not None:
            return existing_user

        demo_user = User(username="demo", password_hash=hash_password("demo123"))
        session.add(demo_user)
        session.commit()
        session.refresh(demo_user)
        return demo_user


@router.post("/login")
def login(request: LoginRequest):
    _ensure_demo_user()

    with Session(engine) as session:
        user = session.exec(select(User).where(User.username == request.username)).first()
        if user is None or not verify_password(request.password, user.password_hash):
            return api_error("用户名或密码错误", status_code=401)

        token = create_access_token(user.id, user.username)
        return api_success(
            "登录成功",
            {
                "token": token,
                "token_type": "bearer",
                "user": user.username,
                "user_id": user.id,
            },
        )


@router.post("/register")
def register(request: RegisterRequest):
    if not request.username or len(request.password) < 4:
        return api_error("用户名不能为空，密码至少 4 位", status_code=400)

    with Session(engine) as session:
        existing_user = session.exec(select(User).where(User.username == request.username)).first()
        if existing_user is not None:
            return api_error("用户名已存在", status_code=400)

        user = User(username=request.username, password_hash=hash_password(request.password))
        session.add(user)
        session.commit()
        session.refresh(user)

        token = create_access_token(user.id, user.username)
        return api_success(
            "注册成功",
            {
                "token": token,
                "token_type": "bearer",
                "user": user.username,
                "user_id": user.id,
            },
        )


@router.get("/me")
def me(current_user: dict = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    return api_success("当前用户", {
        "username": current_user.get("sub"),
        "user_id": current_user.get("uid"),
    })
