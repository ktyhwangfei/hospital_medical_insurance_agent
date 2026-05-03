from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.runtime.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title='medical-insurance-ai-agent')

    @app.get('/health')
    def health() -> dict[str, str]:
        return {'status': 'ok'}

    @app.get('/')
    def index() -> FileResponse:
        return FileResponse(Path(__file__).parent.parent.parent / 'static' / 'index.html')

    app.include_router(router, prefix='/api/v1/medical-insurance-ai-agent')
    return app
