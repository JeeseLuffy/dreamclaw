import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from dclaw.community_config import CommunityConfig
from dclaw.community_service import CommunityService


class LoginRequest(BaseModel):
    nickname: str


class ContentRequest(BaseModel):
    user_id: int
    body: str
    parent_id: int | None = None


class LikeRequest(BaseModel):
    user_id: int


class TickRequest(BaseModel):
    max_agents: int | None = None


class ModelUpdateRequest(BaseModel):
    user_id: int
    provider: str
    model: str


class OnlineScheduler(threading.Thread):
    def __init__(self, service: CommunityService, interval: int):
        super().__init__(daemon=True)
        self.service = service
        self.interval = interval
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        while not self._stop_event.wait(self.interval):
            self.service.run_ai_tick()


def create_app(config: CommunityConfig | None = None) -> FastAPI:
    config = config or CommunityConfig.from_env()
    service = CommunityService(config)
    scheduler = OnlineScheduler(service=service, interval=config.scheduler_interval_seconds)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        scheduler.start()
        yield
        scheduler.stop()
        scheduler.join(timeout=2)

    app = FastAPI(title="DreamClaw Community API", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/models")
    def models():
        return service.available_models()

    @app.post("/auth/login")
    def login(payload: LoginRequest):
        try:
            return service.register_or_login(payload.nickname)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/timeline")
    def timeline(limit: int = 30):
        return service.get_timeline(limit=min(100, max(1, limit)))

    @app.post("/content")
    def create_content(payload: ContentRequest):
        try:
            return service.create_human_content(
                user_id=payload.user_id,
                body=payload.body,
                parent_id=payload.parent_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/content/{content_id}/like")
    def like(content_id: int, payload: LikeRequest):
        try:
            return {"liked": service.like_content(payload.user_id, content_id)}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/ai/tick")
    def run_tick(payload: TickRequest):
        return service.run_ai_tick(max_agents=payload.max_agents)

    @app.get("/metrics")
    def metrics():
        return service.community_metrics()

    @app.get("/users")
    def users(limit: int = 100):
        return service.list_users(limit=min(200, max(1, limit)))

    @app.get("/dashboard/{user_id}")
    def dashboard(user_id: int):
        try:
            return service.user_dashboard(user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/traces")
    def traces(limit: int = 40):
        return service.recent_traces(limit=min(200, max(1, limit)))

    @app.post("/ai/model")
    def update_model(payload: ModelUpdateRequest):
        try:
            return service.update_user_ai_model(payload.user_id, payload.provider, payload.model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


def run_api():
    import uvicorn

    config = CommunityConfig.from_env()
    app = create_app(config)
    host = "0.0.0.0"
    port = 8011
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_api()
