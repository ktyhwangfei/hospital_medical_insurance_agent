import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.data_platform.storage.skill.seed import seed_default_skills
from src.gateway.api_gateway.audit_middleware import GatewayAuditMiddleware
from src.runtime.api.knowledge_routes import router as knowledge_router
from src.runtime.api.mcp_routes import router as mcp_router
from src.runtime.api.model_routes import router as model_router
from src.runtime.api.routes import _skill_storage, router
from src.runtime.api.skill_routes import router as skill_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    print("[STARTUP] lifespan: 步骤 1/2 加载数据存储", flush=True)
    from src.data_platform.data_access.factory import create_data_store
    create_data_store()
    print("[STARTUP] lifespan: 步骤 1/2 完成", flush=True)

    print("[STARTUP] lifespan: 步骤 2/2 播种默认技能", flush=True)
    seed_default_skills(_skill_storage)
    print("[STARTUP] lifespan: 步骤 2/2 完成", flush=True)
    yield


def create_app() -> FastAPI:
    print("[STARTUP] create_app: 开始创建 FastAPI 应用", flush=True)
    app = FastAPI(title='medical-insurance-ai-agent', lifespan=_lifespan)

    print("[STARTUP] create_app: 添加中间件", flush=True)
    app.add_middleware(GatewayAuditMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            'http://127.0.0.1:3000',
            'http://localhost:3000',
            'http://127.0.0.1:5173',
            'http://localhost:5173',
        ],
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    @app.get('/health')
    def health() -> dict[str, str]:
        return {'status': 'ok'}

    print("[STARTUP] create_app: 注册路由模块", flush=True)
    app.include_router(router, prefix='/api/v1/medical-insurance-ai-agent')
    app.include_router(skill_router, prefix='/api/v1/medical-insurance-ai-agent')
    app.include_router(mcp_router)
    app.include_router(knowledge_router, prefix='/api/v1/medical-insurance-ai-agent')
    app.include_router(model_router, prefix='/api/v1/medical-insurance-ai-agent')
    print("[STARTUP] create_app: 完成", flush=True)
    return app
