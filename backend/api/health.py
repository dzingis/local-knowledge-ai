from fastapi import APIRouter

from backend.config.settings import get_settings

router = APIRouter(tags=['health'])


@router.get('/health')
def health() -> dict:
    settings = get_settings()
    return {
        'status': 'ok',
        'services': {
            'sql': 'starting',
            'qdrant': 'starting',
            'ollama': 'starting',
        },
        'config': {
            'app_name': settings.app_name,
            'app_version': settings.app_version,
        },
    }
