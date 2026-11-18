from datetime import datetime
from sqlalchemy import Integer, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

class PublicKey(Base):
    __tablename__ = "public_keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    
    # PEM formatted public key
    public_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationship
    user: Mapped["User"] = relationship()


class PublicKeyHistory(Base):
    """Every public key a user has ever published, by version (append-only).

    Messages are encrypted with the keys that were current when they were sent,
    so clients need old public keys to decrypt history after a key change.
    """
    __tablename__ = "public_key_history"
    __table_args__ = (UniqueConstraint("user_id", "key_version", name="uq_public_key_history_user_version"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    public_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
