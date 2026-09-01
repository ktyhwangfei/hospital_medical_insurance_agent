# ⚠️ load_dotenv 必须在所有其他 import 之前，否则 production.py 的模块级
# os.getenv() 会在 .env 加载前执行，导致 DATA_SOURCE_MODE 等配置始终为默认值。
from dotenv import load_dotenv
load_dotenv()

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.gateway.api_gateway.audit_middleware import GatewayAuditMiddleware
from src.runtime.api.infra_skill_routes import router as infra_skill_router
from src.runtime.api.policy_knowledge_routes import router as policy_knowledge_router
from src.runtime.api.policy_pipeline_routes import router as policy_pipeline_router
from src.runtime.api.policy_qa_routes import router as policy_qa_router
from src.runtime.api.semantic_routes import router as semantic_router
from src.runtime.api.semantic_alignment_routes import router as semantic_alignment_router
from src.runtime.api.policy_workbench_routes import router as policy_workbench_router
from src.runtime.api.model_governance_routes import router as model_governance_router
from src.runtime.api.data_governance_routes import router as data_governance_router

logger = logging.getLogger(__name__)


def _without_validation_inputs(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_validation_inputs(item)
            for key, item in value.items()
            if key != "input"
        }
    if isinstance(value, list):
        return [_without_validation_inputs(item) for item in value]
    return value


async def _request_validation_error_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": jsonable_encoder(_without_validation_inputs(exc.errors()))},
    )


@asynccontextmanager
async def _lifespan(app: FastAPI):
    print("[STARTUP] lifespan: 加载数据存储", flush=True)
    from src.data_platform.data_access.factory import create_data_store
    create_data_store()
    print("[STARTUP] lifespan: 完成", flush=True)
    yield


def create_app() -> FastAPI:
    print("[STARTUP] create_app: 开始创建 FastAPI 应用", flush=True)
    app = FastAPI(title='medical-insurance-ai-agent', lifespan=_lifespan)
    app.add_exception_handler(
        RequestValidationError,
        _request_validation_error_handler,
    )

    print("[STARTUP] create_app: 添加中间件", flush=True)
    app.add_middleware(GatewayAuditMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            'http://127.0.0.1:3000',
            'http://localhost:3000',
        ],
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    @app.get('/health')
    def health() -> dict[str, str]:
        # 就绪判定：真实数据源（PostgreSQL）必须连通。本地/生产均不使用内存模式，
        # 故 DATA_SOURCE_READY 为 False（连不上 PG 而回退内存）时返回 503，让
        # 启动脚本（ws.ps1 / start-servers.ps1）据 /health 判定真实就绪状态。
        from src.data_platform.data_access.factory import DATA_SOURCE_READY
        if not DATA_SOURCE_READY:
            raise HTTPException(status_code=503, detail='data source not ready')
        return {'status': 'ok'}

    print("[STARTUP] create_app: 注册路由模块", flush=True)
    app.include_router(infra_skill_router, prefix='/api/v1/medical-insurance-ai-agent')
    app.include_router(policy_knowledge_router)
    app.include_router(policy_pipeline_router)
    app.include_router(policy_qa_router, prefix='/api/v1/medical-insurance-ai-agent/policy-qa')
    app.include_router(semantic_router)
    app.include_router(semantic_alignment_router)
    app.include_router(policy_workbench_router)
    app.include_router(model_governance_router)
    app.include_router(data_governance_router)
    print("[STARTUP] create_app: 完成", flush=True)
    return app
