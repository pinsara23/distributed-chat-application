from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.public_key import PublicKey, PublicKeyHistory

class KeyService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def upload_or_update_key(self, user_id: int, public_key_pem: str) -> PublicKey:
        """Upserts a public key for a user and manages versioning."""

        stmt = select (PublicKey).where(PublicKey.user_id == user_id)
        resullt = await self.db.execute(stmt)
        existing_key = resullt.scalar_one_or_none()

        if existing_key:
            if existing_key.public_key_pem.strip() == public_key_pem.strip():
                # Same key re-uploaded (e.g. client restart): not a key change,
                # so do not bump the version or peers would see false rotations.
                return existing_key
            # A different key: update it and increment the version
            existing_key.public_key_pem = public_key_pem
            existing_key.key_version += 1
            db_key = existing_key
        else:
            # Create a new public key entry
            db_key = PublicKey(user_id=user_id, public_key_pem=public_key_pem, key_version=1)
            self.db.add(db_key)

        # Keep every version so peers can still decrypt messages sent before a key change.
        self.db.add(PublicKeyHistory(user_id=user_id, key_version=db_key.key_version, public_key_pem=public_key_pem))

        await self.db.commit()
        await self.db.refresh(db_key)
        return db_key

    async def get_key_by_user_id(self, user_id: int) -> PublicKey | None:
        """Fetches the public key for a given user ID."""
        stmt = select(PublicKey).where(PublicKey.user_id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_key_history(self, user_id: int) -> list[PublicKeyHistory]:
        """All public keys the user has published, oldest first."""
        stmt = (
            select(PublicKeyHistory)
            .where(PublicKeyHistory.user_id == user_id)
            .order_by(PublicKeyHistory.key_version.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
