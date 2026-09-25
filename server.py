import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from db import close_pool, init_db, ping
from demo.seed import seed_demo
from pipeline.queue import Worker
from routes.agents import router as agents_router
from routes.hackathons import router as hackathons_router
from routes.projects import router as projects_router
from services import llm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
for noisy in ("httpx", "ddgs", "primp", "chromadb"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_demo()
    worker = None
    if settings.run_worker:
        worker = Worker()
        worker.start()
    if not llm.is_configured():
        logging.warning("LLM_API_KEY is not set: judges will fall back to measured signals only")
    yield
    if worker:
        worker.stop()
    close_pool()


app = FastAPI(
    title="Evalio API",
    description=(
        "AI hackathon jury: a Code Judge, a Market Judge and a Product Judge evaluate every "
        "submission against the hackathon's weighted criteria; a Head Judge ranks them."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )



@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    """Return a readable message (the frontend shows `detail` as-is) plus the raw errors."""
    messages = []
    for err in exc.errors():
        field = next((str(p) for p in reversed(err["loc"]) if not isinstance(p, int) and p != "body"), "request")
        messages.append(f"{field}: {err['msg'].removeprefix('Value error, ')}")
    return JSONResponse(status_code=422, content={"detail": "; ".join(messages), "errors": jsonable(exc.errors())})


def jsonable(errors: list[dict]) -> list[dict]:
    return [{k: v for k, v in e.items() if k in ("loc", "msg", "type")} for e in errors]


app.include_router(hackathons_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(agents_router, prefix="/api")


@app.get("/health")
def health():
    return {
        "status": "ok" if ping() else "degraded",
        "database": ping(),
        "llm_configured": llm.is_configured(),
        "model": settings.llm_model,
        "worker": settings.run_worker,
    }


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
