from datetime import datetime, timedelta
import jwt
from passlib.context import CryptContext
from app.core.config import settings

# Hashing algorithm - argon2id
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def verifyPassword(plin_passowrd: str, hashed_password: str)-> bool:
    return pwd_context.verify(plin_passowrd, hashed_password)

def get_password_hash(plain_password: str) -> str:
    return pwd_context.hash(plain_password)

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})

    # create jwt token
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt