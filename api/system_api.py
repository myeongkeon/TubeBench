from fastapi import APIRouter
from core import key_manager
from core.api_handler import YouTubeAPIHandler

router = APIRouter()


@router.get("/keys/status")
def get_keys_status():
    return {
        "youtube":   key_manager.youtube.status(),
        "gemini":    key_manager.gemini.status(),
        "anthropic": key_manager.anthropic.status(),
    }


@router.post("/keys/reset")
def reset_keys():
    key_manager.youtube.reset()
    key_manager.gemini.reset()
    key_manager.anthropic.reset()
    return {"ok": True}


@router.post("/cache/clear")
def clear_cache():
    handler = YouTubeAPIHandler()
    deleted = handler.clear_expired_cache()
    return {"deleted": deleted}
