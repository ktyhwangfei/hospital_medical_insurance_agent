from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.runtime.api.mcp_routes import router as mcp_router
from src.runtime.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title='medical-insurance-ai-agent')

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

    app.include_router(router, prefix='/api/v1/medical-insurance-ai-agent')
    app.include_router(mcp_router)
    return app

