from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.services.health_service import HealthService

router = APIRouter()

def get_health_service(db: AsyncSession = Depends(get_db)) -> HealthService:
    return HealthService(db)

@router.get("/live", status_code=status.HTTP_200_OK)
async def liveness_check():
    """"Liveness probe fast not dependencies"""
    return {"status": "alive"}

@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness_check(health_service: HealthService = Depends(get_health_service)):

    """Readiness probe: Checks critical infrastructure via the HealthService."""

    db_ok, db_msg = await health_service.check_database()
    redis_ok, redis_msg = await health_service.check_redis()

    is_ready = db_ok and redis_ok

    health_status = {
        "status": "ready" if is_ready else "not ready",
        "database": db_msg,
        "redis": redis_msg
    }
    if not is_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=health_status
        )

    return health_status