from fastapi import FastAPI
from app.api import auth

app = FastAPI(
    title="Distributed Chat API (Stage 1)",
    description="Secure Single-Server Chat Backend",
    version="1.0.0"
)

# Include our routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])

@app.get("/")
async def root():
    return {"message": "Welcome to the Distributed Chat API"}