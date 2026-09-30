# school_class.py - class pages and their membership
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.db import Base


class SchoolClass(Base):
    __tablename__ = "school_classes"
    __table_args__ = (CheckConstraint("status in ('pending','active','hidden')", name="ck_school_classes_status"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    members: Mapped[list["ClassMember"]] = relationship(
        back_populates="school_class", cascade="all, delete-orphan"
    )


class ClassMember(Base):
    __tablename__ = "class_members"
    __table_args__ = (
        CheckConstraint("role in ('member','owner')", name="ck_class_members_role"),
        CheckConstraint("status in ('pending','approved')", name="ck_class_members_status"),
    )

    class_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("school_classes.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False, default="member")
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    school_class: Mapped["SchoolClass"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship()  # noqa: F821 - User imported via app.models package