from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class User(SQLModel, table=True):

    id: Optional[int] = Field(
        default=None,
        primary_key=True
    )

    username: str = Field(
        unique=True,
        index=True
    )

    password_hash: str

    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )

    updated_at: datetime = Field(
        default_factory=datetime.utcnow
    )

    is_active: bool = True


class Conversation(SQLModel, table=True):

    id: Optional[int] = Field(
        default=None,
        primary_key=True
    )

    user_id: Optional[int] = Field(
        default=None,
        foreign_key="user.id",
        index=True
    )

    title: str = "新对话"

    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )

    updated_at: datetime = Field(
        default_factory=datetime.utcnow
    )


class Message(SQLModel, table=True):

    id: Optional[int] = Field(
        default=None,
        primary_key=True
    )

    user_id: Optional[int] = Field(
        default=None,
        foreign_key="user.id",
        index=True
    )

    conversation_id: int = Field(
        foreign_key="conversation.id"
    )

    role: str

    content: str

    sources: Optional[str] = None

    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )


class File(SQLModel, table=True):

    id: Optional[int] = Field(
        default=None,
        primary_key=True
    )

    user_id: Optional[int] = Field(
        default=None,
        foreign_key="user.id",
        index=True
    )

    filename: str

    filepath: str

    source: str = "user"


class SearchHistory(SQLModel, table=True):
    """用户搜索历史记录（按用户隔离）。

    记录用户在实验方案生成等页面执行的搜索与分析；
    filters_json 存储筛选条件的 JSON 序列化（可为空）。
    """

    __tablename__ = "search_history"

    id: Optional[int] = Field(
        default=None,
        primary_key=True
    )

    user_id: int = Field(
        foreign_key="user.id",
        index=True
    )

    query: str = Field(
        max_length=500
    )

    filters_json: Optional[str] = Field(
        default=None,
        description="筛选条件 JSON（序列化字符串）",
    )

    result_count: int = Field(
        default=0
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )