from fastapi import APIRouter
from pydantic import BaseModel
from core.api_handler import YouTubeAPIHandler

router = APIRouter()


class CacheClearRequest(BaseModel):
    youtube_api_key: str


@router.post("/cache/clear")
def clear_cache(req: CacheClearRequest):
    handler = YouTubeAPIHandler(api_key=req.youtube_api_key)
    deleted = handler.clear_expired_cache()
    return {"deleted": deleted}
