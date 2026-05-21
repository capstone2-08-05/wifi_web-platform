import logging

# 앱 로거 활성화 — `logger = logging.getLogger(__name__)` 로 만든 logger.info() 가
# 콘솔에 보이도록. uvicorn 자체 INFO 와는 별개 (uvicorn 은 자체 로거 사용).
# force=True: uvicorn 이 이미 root logger 에 handler 를 박았을 경우 덮어쓰기.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    force=True,
)

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from app.routers.experiments import router as experiments_router
from app.routers.health import router as health_router
from app.routers.upload import router as upload_router
from app.routers.rf.measurements import router as measurements_router
from app.routers.auth import router as auth_router
from app.routers.projects import router as projects_router
from app.routers.floors import router as floors_router
from app.routers.scene.scene_drafts import (
    router as scene_drafts_router,
    floor_scene_drafts_router,
)
from app.core.errors import AppError, ErrorCode
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.core.settings import CORS_ALLOW_ORIGINS
from app.routers.assets import floor_assets_router, assets_router
from app.routers.scene.draft_rooms import scene_draft_rooms_router, draft_rooms_router
from app.routers.scene.draft_walls import scene_draft_walls_router, draft_walls_router
from app.routers.scene.draft_openings import scene_draft_openings_router, draft_openings_router
from app.routers.scene.draft_objects import scene_draft_objects_router, draft_objects_router
from app.routers.scene.scene_versions import (
    promote_router,
    scene_versions_router,
    floor_scene_versions_router,
)
from app.routers.scene.rooms import router as rooms_router
from app.routers.scene.walls import router as walls_router
from app.routers.scene.openings import router as openings_router
from app.routers.scene.objects import router as objects_router
from app.routers.patch_logs import router as patch_logs_router
from app.routers.catalog.materials import router as materials_router
from app.routers.catalog.material_hypotheses import (
    wall_hypotheses_router,
    hypotheses_router,
)
from app.routers.rf.rf_runs import router as rf_runs_router, floor_rf_runs_router
from app.routers.rf.rf_jobs import router as rf_jobs_router
from app.routers.rf.ap_layouts import (
    router as ap_layouts_router,
    rf_run_router as rf_run_ap_layouts_router,
)
from app.routers.rf.calibration_runs import router as calibration_runs_router
from app.routers.rf.ap_recommendation import router as ap_recommendation_router
from app.routers.inference.jobs import router as jobs_router
from app.routers.inference.floorplan_jobs import router as floorplan_jobs_router
from app.services.inference.job_poller import job_poller_lifespan


app = FastAPI(
    title="capstone2-backend",
    version="0.1.0",
    lifespan=job_poller_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 로컬 자산 정적 서빙 (assets / heatmaps / RF maps — local:// URI 의 HTTP 대응).
# refactor/no-aws (Colab) — S3 presigned URL 의 로컬 대체.
from app.services._local_storage import STORAGE_ROOT as _STORAGE_ROOT
_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/storage", StaticFiles(directory=str(_STORAGE_ROOT)), name="storage")

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
app.include_router(measurements_router)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(floors_router)
app.include_router(scene_drafts_router)
app.include_router(floor_scene_drafts_router)
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
app.include_router(promote_router)
app.include_router(scene_versions_router)
app.include_router(floor_scene_versions_router)
app.include_router(rooms_router)
app.include_router(walls_router)
app.include_router(openings_router)
app.include_router(objects_router)
app.include_router(patch_logs_router)
app.include_router(materials_router)
app.include_router(wall_hypotheses_router)
app.include_router(hypotheses_router)
app.include_router(rf_runs_router)
app.include_router(floor_rf_runs_router)
app.include_router(rf_jobs_router)
app.include_router(ap_layouts_router)
app.include_router(rf_run_ap_layouts_router)
app.include_router(calibration_runs_router)
app.include_router(ap_recommendation_router)
app.include_router(jobs_router)
app.include_router(floorplan_jobs_router)
