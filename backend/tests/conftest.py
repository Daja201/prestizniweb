# Shared integration-test fixtures using an isolated PostgreSQL database.
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
import psycopg
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import settings
from sqlalchemy import create_engine
from app.core.db import SessionLocal
from app.main import app
from app.models import AuditLog, ClassMember, LoginToken, Meme, MemeLike, Quote, QuoteVote, Report, Resource, ResourceVote, SchoolClass, TakedownRequest, User, UserSession
from app.services.sessions import create_session


def _database_name() -> str:
    return f"{settings.postgres_db}_test"


def _admin_database_url() -> str:
    parts = urlsplit(settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    return urlunsplit((parts.scheme, parts.netloc, "/postgres", parts.query, parts.fragment))


@pytest.fixture(scope="session", autouse=True)
def test_database():
    name = _database_name()
    admin_url = _admin_database_url()
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name.replace(chr(34), chr(34) * 2)}"') if not _database_exists(conn, name) else None
    test_url = settings.database_url.replace(settings.postgres_db, name, 1)
    os.environ["DATABASE_URL"] = test_url
    settings.database_url = test_url
    test_engine = create_engine(test_url, future=True)
    SessionLocal.configure(bind=test_engine)
    from alembic.config import Config
    from alembic import command
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(cfg, "head")
    yield
    test_engine.dispose()
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name.replace(chr(34), chr(34) * 2)}" WITH (FORCE)')


def _database_exists(conn, name: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone())


@pytest.fixture(autouse=True)
def clean_db():
    yield
    db = SessionLocal()
    try:
        for model in (Report, AuditLog, TakedownRequest, ResourceVote, Resource, QuoteVote, Quote, MemeLike, Meme, ClassMember, SchoolClass, UserSession, LoginToken, User):
            db.execute(delete(model))
        db.commit()
    finally:
        db.close()


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client


@pytest.fixture
def make_user(db: Session):
    def factory(email: str | None = None, role: str = "student", status: str = "active") -> User:
        index = int(db.scalar(__import__("sqlalchemy").select(__import__("sqlalchemy").func.count()).select_from(User)) or 0) + 1
        email_value = email or f"student{index}@spseiostrava.cz"
        user = User(email=email_value.lower(), display_name=f"Student {index}", role=role, status=status)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    return factory


@pytest.fixture
def login(db: Session):
    def do_login(client: TestClient, user: User) -> None:
        raw = create_session(db, user, "127.0.0.1", "pytest")
        db.commit()
        client.cookies.set("session", raw)
    return do_login
