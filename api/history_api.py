from fastapi import APIRouter
from core import history as hist

router = APIRouter()

TABS = [
    "channel_analyzer",
    "competitor_bench",
    "ai_planner",
    "trend_planner",
    "keyword_analyzer",
    "copywriter",
]


@router.get("/{tab}")
def list_history(tab: str, limit: int = 30):
    if tab not in TABS:
        return {"error": f"알 수 없는 탭: {tab}"}
    return {"records": hist.list_results(tab, limit=limit)}


@router.get("/{tab}/{filename}")
def get_history(tab: str, filename: str):
    if tab not in TABS:
        return {"error": f"알 수 없는 탭: {tab}"}
    entry = hist.load_result(tab, filename)
    if not entry:
        return {"error": "기록을 찾을 수 없습니다."}
    return entry
