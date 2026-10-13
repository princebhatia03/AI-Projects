import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.api.routes import router
from app.pipeline import state as pipeline_state
from app.storage import campaigns_db
from app.storage.pincode_graph import close

# Ensure app.* INFO logs appear next to uvicorn access logs (uvicorn does not
# attach handlers to the root logger by default).
_app_logger = logging.getLogger("app")
_app_logger.setLevel(logging.INFO)
if not any(isinstance(h, logging.StreamHandler) for h in _app_logger.handlers):
    _handler = logging.StreamHandler()
    _handler.setLevel(logging.INFO)
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s — %(message)s"))
    _app_logger.addHandler(_handler)
_app_logger.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.load_error = None
    app.state.status = {"loaded": False, "agentic": True, "postgres_required": False}
    try:
        campaigns_db.init_db()
        if pipeline_state.load_artifacts_if_present():
            app.state.status = pipeline_state.get_status()
            logging.getLogger(__name__).info(
                "Startup: loaded pipeline artifacts (pincodes=%s)",
                app.state.status.get("pincode_count"),
            )
        else:
            app.state.status = {
                "loaded": False,
                "agentic": True,
                "postgres_required": False,
                "hint": "POST /pipeline/run to load DataSet CSVs and build pincode risk predictions",
                "chat_ready": config.llm_ready(),
                "llm_provider": config.LLM_PROVIDER,
            }
            logging.getLogger(__name__).info("Startup: no artifacts yet — POST /pipeline/run to build")
    except Exception as exc:  # noqa: BLE001
        app.state.load_error = str(exc)
        app.state.status = {
            "loaded": False,
            "error": str(exc),
            "agentic": True,
            "postgres_required": False,
            "chat_ready": config.llm_ready(),
            "llm_provider": config.LLM_PROVIDER,
        }
        logging.getLogger(__name__).exception("Startup failed: %s", exc)
    yield
    close()


app = FastAPI(title="Pincode risk prediction", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
