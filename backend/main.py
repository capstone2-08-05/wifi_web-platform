from fastapi import FastAPI, Request
from app.routers.experiments import router as experiments_router
from app.routers.health import router as health_router
from app.routers.upload import router as upload_router
from app.routers.rf_run import router as rf_run_router
from app.routers.measurements import router as measurements_router
from app.routers.auth import router as auth_router
from app.routers.projects import router as projects_router
from app.routers.floors import router as floors_router
from app.routers.scene_drafts import router as scene_drafts_router
from app.core.errors import AppError, ErrorCode
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.core.settings import CORS_ALLOW_ORIGINS
from app.routers.assets import floor_assets_router, assets_router
from app.routers.draft_rooms import scene_draft_rooms_router, draft_rooms_router
from app.routers.draft_walls import scene_draft_walls_router, draft_walls_router
from app.routers.draft_openings import scene_draft_openings_router, draft_openings_router
from app.routers.draft_objects import scene_draft_objects_router, draft_objects_router


app = FastAPI(title="capstone2-backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(AppError)

async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message},
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": ErrorCode.INVALID_REQUEST_BODY,
            "message": "Request validation failed.",
            "details": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "code": ErrorCode.INTERNAL_SERVER_ERROR,
            "message": "Internal server error.",
        },
    )

app.include_router(health_router)
app.include_router(upload_router)
app.include_router(experiments_router)
app.include_router(rf_run_router)
app.include_router(measurements_router)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(floors_router)
app.include_router(scene_drafts_router)
app.include_router(floor_assets_router)
app.include_router(assets_router)
app.include_router(scene_draft_rooms_router)
app.include_router(draft_rooms_router)
app.include_router(scene_draft_walls_router)
app.include_router(draft_walls_router)
app.include_router(scene_draft_openings_router)
app.include_router(draft_openings_router)
app.include_router(scene_draft_objects_router)
app.include_router(draft_objects_router)
