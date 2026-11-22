# Owner: B —— 只负责创建 app 并挂载路由。C/D 把接口写在各自的 routes_*.py 里，不要改本文件。
from pathlib import Path
from contextlib import asynccontextmanager
import logging
from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from backend.routes_inference import router as inference_router
from backend.routes_agent import router as agent_router
from backend.routes_memory import router as memory_router
from backend.routes_pose import router as pose_router

@asynccontextmanager
async def lifespan(app):
    from backend.database import get_db_path
    logging.getLogger('uvicorn.error').info('SQLite database: %s', get_db_path())
    yield

app = FastAPI(title="YogaCoach API",lifespan=lifespan)

app.include_router(pose_router)
app.include_router(inference_router)
app.include_router(agent_router)
app.include_router(memory_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get('/api/ready')
def ready():
    from backend.readiness import readiness
    return readiness()

# Optional same-origin production hosting, after all API routes.
_dist=Path(__file__).resolve().parents[1]/'frontend/dist'
if _dist.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount('/',StaticFiles(directory=_dist,html=True),name='frontend')
