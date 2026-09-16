from datetime import timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from fastapi import HTTPException, status

from app.core.security import get_password_hash, verifyPassword, create_access_token
from app.core.config import settings
from app.models.user import User
from app.schemas.user import UserCreate
from app.schemas.auth import Token

class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def register_user(self, user_in: UserCreate) -> User:
        result = await self.db.execute(
            select(User).where(
                or_(User.email == user_in.email, User.username == user_in.username)
            )
        )

        if result.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email or username already registered",
            )

        # HAsh password and create user
        hashed_password = get_password_hash(user_in.password)
        db_user = User(
            username=user_in.username,
            email=user_in.email,
            password_hash=hashed_password
        )

        self.db.add(db_user)
        await self.db.commit()
        await self.db.refresh(db_user)

        return db_user

    async def authenticate_user(self, username: str, password: str) -> User:

        result = await self.db.execute(select(User).where(User.username == username))
        user = result.scalars().first()

        if not user or not verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )
        # Generate JWT
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(

            data= {"sub":str(user.id)},
            expires_delta=access_token_expires

        )
        return Token(access_token=access_token, token_type="bearer")

"""
Why use a class? By creating an AuthService class ? 
that accepts a database session in its __init__, we can easily inject it, 
mock it for unit tests, and avoid passing db manually to every single function.
"""