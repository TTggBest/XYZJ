from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from zhiju import __version__
from zhiju.api.health import router as health_router
from zhiju.api.settings import router as settings_router
from zhiju.api.history import router as history_router
from zhiju.api.identity import router as identity_router
from zhiju.api.integration import router as integration_router
from zhiju.api.channel import router as channel_router
from zhiju.api.operations import router as operations_router
from zhiju.api.production import router as production_router
from zhiju.api.youtube import router as youtube_router
from zhiju.api.skill import router as skill_router
from zhiju.api.demo import router as demo_router
from zhiju.api.realtime import router as realtime_router
from zhiju.api.feishu_sync import router as feishu_sync_router
from zhiju.api.image_processing import router as image_processing_router
from zhiju.api.youtube_oauth import router as youtube_oauth_router
from zhiju.realtime import build_change_event, publish_change_event


def create_app() -> FastAPI:
    frontend_root = Path(__file__).resolve().parents[2]
    app = FastAPI(title="筱宇智矩 API", version=__version__)
    app.include_router(health_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(history_router, prefix="/api")
    app.include_router(identity_router, prefix="/api")
    app.include_router(integration_router, prefix="/api")
    app.include_router(image_processing_router, prefix="/api")
    app.include_router(youtube_oauth_router, prefix="/api")
    app.include_router(channel_router, prefix="/api")
    app.include_router(operations_router, prefix="/api")
    app.include_router(production_router, prefix="/api")
    app.include_router(youtube_router, prefix="/api")
    app.include_router(skill_router, prefix="/api")
    app.include_router(demo_router, prefix="/api")
    app.include_router(realtime_router, prefix="/api")
    app.include_router(feishu_sync_router, prefix="/api")
    app.mount("/assets", StaticFiles(directory=frontend_root / "assets"), name="assets")

    @app.middleware("http")
    async def publish_successful_changes(request, call_next):
        response = await call_next(request)
        is_business_write = (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.url.path.startswith("/api/v3/")
            and request.url.path not in {
                "/api/v3/events/publish",
                "/api/v3/settings/runtime/environment",
            }
            and response.status_code < 400
        )
        if is_business_write:
            await publish_change_event(build_change_event(request))
        return response

    @app.middleware("http")
    async def revalidate_frontend_files(request, call_next):
        response = await call_next(request)
        if request.url.path in {"/", "/assets/app.js", "/assets/styles.css"}:
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/", include_in_schema=False)
    def root() -> FileResponse:
        return FileResponse(frontend_root / "index.html")

    return app


app = create_app()
