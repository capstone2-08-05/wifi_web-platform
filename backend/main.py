from fastapi import FastAPI, Request
from app.routers.experiments import router as experiments_router
from app.routers.health import router as health_router
from app.routers.upload import router as upload_router
from app.routers.space import router as space_router
from app.routers.rf_run import router as rf_run_router
from app.core.errors import AppError, ErrorCode
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

app = FastAPI(title="capstone2-backend", version="0.1.0")


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
app.include_router(space_router)
app.include_router(rf_run_router)
