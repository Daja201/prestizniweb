# content.py - memes, quotes, resources, tags, votes/likes
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Table,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.schema import Computed
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.db import Base

meme_tags = Table(
    "meme_tags",
    Base.metadata,
    Column("meme_id", BigInteger, ForeignKey("memes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", BigInteger, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

resource_tags = Table(
    "resource_tags",
    Base.metadata,
    Column("resource_id", BigInteger, ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", BigInteger, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (CheckConstraint("name = lower(name)", name="ck_tags_lowercase"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)


class Meme(Base):
    __tablename__ = "memes"
    __table_args__ = (
        CheckConstraint("status in ('visible','hidden','deleted')", name="ck_memes_status"),
        Index("ix_memes_status_id", "status", text("id DESC")),
        Index("ix_memes_class_id", "class_id"),
        Index("ix_memes_status_created_at_id", "status", text("created_at DESC"), text("id DESC")),
        Index("ix_memes_status_likes_id", "status", text("likes_count DESC"), text("id DESC")),
        CheckConstraint("width > 0", name="ck_memes_width"),
        CheckConstraint("height > 0", name="ck_memes_height"),
        CheckConstraint("likes_count >= 0", name="ck_memes_likes_count"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    author_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    class_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("school_classes.id"), default=None
    )
    caption: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    image_path: Mapped[str] = mapped_column(String(200), nullable=False)
    thumb_path: Mapped[str] = mapped_column(String(200), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    likes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="visible")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    author: Mapped["User"] = relationship()  # noqa: F821
    school_class: Mapped["SchoolClass | None"] = relationship()  # noqa: F821
    tags: Mapped[list["Tag"]] = relationship(secondary=meme_tags)


class MemeLike(Base):
    __tablename__ = "meme_likes"

    meme_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("memes.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Quote(Base):
    __tablename__ = "quotes"
    __table_args__ = (
        CheckConstraint("status in ('pending','visible','hidden','deleted')", name="ck_quotes_status"),
        Index("ix_quotes_status_id", "status", text("id DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    author_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    class_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("school_classes.id"), default=None
    )
    text: Mapped[str] = mapped_column(String(400), nullable=False)
    said_by: Mapped[str] = mapped_column(String(80), nullable=False)
    context: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    said_on: Mapped[date | None] = mapped_column(Date, default=None)
    votes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    author: Mapped["User"] = relationship()  # noqa: F821
    school_class: Mapped["SchoolClass | None"] = relationship()  # noqa: F821


class QuoteVote(Base):
    __tablename__ = "quote_votes"

    quote_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("quotes.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Resource(Base):
    __tablename__ = "resources"
    __table_args__ = (
        CheckConstraint("kind in ('notes','test','exercises','link','other')", name="ck_resources_kind"),
        CheckConstraint("status in ('visible','hidden','deleted')", name="ck_resources_status"),
        CheckConstraint(
            "(url is not null and file_path is null) or (url is null and file_path is not null)",
            name="ck_resources_url_xor_file",
        ),
        CheckConstraint("school_year is null or school_year between 1 and 4", name="ck_resources_school_year"),
        CheckConstraint("upvotes_count >= 0", name="ck_resources_upvotes_count"),
        CheckConstraint("downloads_count >= 0", name="ck_resources_downloads_count"),
        Index("ix_resources_status_id", "status", text("id DESC")),
        Index("ix_resources_search_vector", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    author_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    class_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("school_classes.id"), default=None
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(40), nullable=False)
    school_year: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    url: Mapped[str | None] = mapped_column(String(500), default=None)
    file_path: Mapped[str | None] = mapped_column(String(200), default=None)
    file_name: Mapped[str | None] = mapped_column(String(200), default=None)
    file_size: Mapped[int | None] = mapped_column(Integer, default=None)
    file_mime: Mapped[str | None] = mapped_column(String(100), default=None)
    upvotes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    downloads_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="visible")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', title || ' ' || description || ' ' || subject)", persisted=True),
    )

    author: Mapped["User"] = relationship()  # noqa: F821
    school_class: Mapped["SchoolClass | None"] = relationship()  # noqa: F821
    tags: Mapped[list["Tag"]] = relationship(secondary=resource_tags)


class ResourceVote(Base):
    __tablename__ = "resource_votes"

    resource_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)