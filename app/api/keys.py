from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.key import PublicKeyCreate, PublicKeyResponse
from app.services.key_service import KeyService

router = APIRouter()

def get_key_service(db: AsyncSession = Depends(get_db)) -> KeyService:
    return KeyService(db)

@router.post("/", response_model=PublicKeyResponse)
async def upload_public_key(
    key_in: PublicKeyCreate,
    current_user: User = Depends(get_current_user),
    key_service: KeyService = Depends(get_key_service)
):
    """Uploads or updates the user's public key."""
    return await key_service.upload_or_update_key(current_user.id, key_in.public_key_pem)

@router.get("/{user_id}", response_model=PublicKeyResponse)
async def get_public_key(
    user_id: int,
    current_user: User = Depends(get_current_user),
    key_service: KeyService = Depends(get_key_service)
):
    """Retrieves the public key for a specific user to establish E2EE."""
    db_key = await key_service.get_key_by_user_id(user_id)

    if not db_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Public key not found for this user."
        )
    return db_key