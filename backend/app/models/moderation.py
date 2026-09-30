# moderation.py - user reports, takedown requests, and the audit trail
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.db import Base


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint(
            "target_type in ('meme','quote','resource','user','class')", name="ck_reports_target_type"
        ),
        CheckConstraint(
            "reason in ('spam','harassment','personal_info','inappropriate','copyright','other')",
            name="ck_reports_reason",
        ),
        CheckConstraint("status in ('open','actioned','dismissed')", name="ck_reports_status"),
        UniqueConstraint("reporter_id", "target_type", "target_id", name="uq_reports_reporter_target"),
        Index("ix_reports_status_target", "status", "target_type", "target_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    reporter_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(10), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    details: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
    handled_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), default=None)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    reporter: Mapped["User"] = relationship(foreign_keys=[reporter_id])  # noqa: F821


class TakedownRequest(Base):
    __tablename__ = "takedown_requests"
    __table_args__ = (
        CheckConstraint("status in ('open','done')", name="ck_takedown_requests_status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    contact: Mapped[str] = mapped_column(String(200), nullable=False)
    target_url: Mapped[str] = mapped_column(String(500), nullable=False)
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
    handled_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"), default=None)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(10), default=None)
    target_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)