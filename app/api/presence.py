from fastapi import APIRouter, Depends
from app.presence.service import presence_service
from app.api.deps import get_current_user

router = APIRouter()

@router.get("/{target_user_id}/presence")
async def get_user_presence(target_user_id: int, current_user_id: dict = Depends(get_current_user)):
    
    """Get the presence status of a specific user."""
    presence_info = await presence_service.get_presence(target_user_id)
    return presence_info