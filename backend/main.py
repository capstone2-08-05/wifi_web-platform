from fastapi import FastAPI
from app.routers.experiments import router as experiments_router
from app.routers.health import router as health_router
from app.routers.upload import router as upload_router

app = FastAPI(title="capstone2-backend", version="0.1.0")
app.include_router(health_router)
app.include_router(upload_router)
app.include_router(experiments_router)
