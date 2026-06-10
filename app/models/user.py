from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    strava_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    access_token: Mapped[str] = mapped_column(String)  # TODO: Fernet encryption
    refresh_token: Mapped[str] = mapped_column(String)  # TODO: Fernet encryption
    expires_at: Mapped[int] = mapped_column()
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    profile_pic: Mapped[str | None] = mapped_column(String, nullable=True)
    subscribed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    stripe_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    beta_user: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    auto_rename: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
