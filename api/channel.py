import re
import pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel
from core.api_handler import YouTubeAPIHandler
from core import history as hist

router = APIRouter()

ANALYZE_VIDEO_COUNT = 30
MCN_THRESHOLDS = {
    "S": {"view_rate": 10.0, "engagement": 2.0},
    "A": {"view_rate": 5.0,  "engagement": 1.0},
}
DIAGNOSIS = {
    "S": {
        "summary": "구독자 도달률과 팬덤 참여도가 모두 최상위권입니다. MCN 파트너십 협상 및 광고 단가 인상에 유리한 지표를 보유하고 있습니다.",
        "strengths": ["높은 구독자 도달률 → 알고리즘 노출 선순환 구조", "강력한 팬덤 참여도 → 댓글·좋아요 기반 커뮤니티 형성"],
        "improvements": ["콘텐츠 다각화(쇼츠 연계)로 신규 시청자 유입 확대", "멤버십·굿즈 등 수익 다변화 시점 검토"],
    },
    "A": {
        "summary": "성장 궤도에 있는 채널입니다. 핵심 지표를 한 단계 끌어올리면 S등급 진입이 가능합니다.",
        "strengths": ["안정적인 콘텐츠 생산력과 기본 팬층 확보"],
        "improvements": ["썸네일·제목 A/B 테스트로 클릭률(CTR) 개선 → 조회율 향상", "영상 말미 CTA(구독·좋아요 요청) 강화로 참여도 증가", "업로드 일관성 유지(주 1~2회)로 알고리즘 노출 안정화"],
    },
    "B": {
        "summary": "성장 초기 단계이거나 정체 구간에 있습니다. 경쟁사 아웃라이어 분석을 통해 돌파구 주제를 발굴하세요.",
        "strengths": ["아직 실험 여지가 넓어 콘텐츠 방향 전환이 유연함"],
        "improvements": ["Hook 강화: 첫 30초 시청 지속률 개선이 이탈률의 핵심 원인", "경쟁사 아웃라이어 영상 분석 후 주제 전략 전면 재수립", "업로드 빈도 조정 — 양보다 질 집중(주 1회 고품질)"],
    },
}


class AnalyzeRequest(BaseModel):
    youtube_api_key: str
    channel_input: str


def _build_df(videos, stats):
    stats_map = {s["video_id"]: s for s in stats}
    rows = []
    for v in videos:
        s = stats_map.get(v["video_id"], {})
        rows.append({
            "video_id":      v["video_id"],
            "title":         v["title"],
            "published_at":  pd.to_datetime(v["published_at"]),
            "view_count":    s.get("view_count", 0),
            "like_count":    s.get("like_count", 0),
            "comment_count": s.get("comment_count", 0),
        })
    df = pd.DataFrame(rows).sort_values("published_at").reset_index(drop=True)
    valid = df["view_count"] > 0
    df.loc[valid, "engagement_rate"] = (
        (df.loc[valid, "like_count"] + df.loc[valid, "comment_count"])
        / df.loc[valid, "view_count"] * 100
    )
    df["engagement_rate"] = df["engagement_rate"].fillna(0)
    return df


def _get_grade(view_rate, engagement):
    s, a = MCN_THRESHOLDS["S"], MCN_THRESHOLDS["A"]
    if view_rate >= s["view_rate"] and engagement >= s["engagement"]:
        return "S"
    if view_rate >= a["view_rate"] or engagement >= a["engagement"]:
        return "A"
    return "B"


@router.post("/analyze")
def analyze(req: AnalyzeRequest):
    handler = YouTubeAPIHandler(api_key=req.youtube_api_key)

    channel_id = handler.resolve_channel_id(req.channel_input)
    channel = handler.get_channel_info(channel_id)
    if not channel:
        return {"error": f"채널을 찾을 수 없습니다: {channel_id}"}

    videos = handler.get_channel_videos(channel["uploads_playlist_id"], max_results=ANALYZE_VIDEO_COUNT)
    stats  = handler.get_video_stats([v["video_id"] for v in videos])

    df = _build_df(videos, stats)
    valid = df[df["view_count"] > 0]
    if valid.empty:
        return {"error": "영상 데이터가 없습니다."}

    avg_views      = float(valid["view_count"].mean())
    avg_engagement = float(valid["engagement_rate"].mean())
    sub            = channel["subscriber_count"]
    view_rate      = (avg_views / sub * 100) if sub > 0 else 0
    days_span      = (df["published_at"].max() - df["published_at"].min()).days
    upload_freq    = (days_span / len(df)) if len(df) > 1 and days_span > 0 else 0

    grade = _get_grade(view_rate, avg_engagement)

    # Chart data
    trend_data = valid[["published_at", "view_count", "title"]].copy()
    trend_data["published_at"] = trend_data["published_at"].dt.strftime("%Y-%m-%d")
    trend_list = trend_data.to_dict("records")

    top10 = valid.nlargest(10, "engagement_rate").copy()
    top10["short_title"] = top10["title"].str[:30]
    eng_list = top10[["short_title", "title", "engagement_rate", "view_count"]].to_dict("records")

    # Raw table
    disp = df[["title", "published_at", "view_count", "like_count", "comment_count", "engagement_rate"]].copy()
    disp["published_at"] = disp["published_at"].dt.strftime("%Y-%m-%d")
    disp["engagement_rate"] = disp["engagement_rate"].round(2)
    raw_videos = disp.to_dict("records")

    # History
    top_videos_hist = (
        valid.nlargest(10, "engagement_rate")[["title", "view_count", "engagement_rate"]]
        .round({"engagement_rate": 2})
        .to_dict("records")
    )
    hist.save_result("channel_analyzer", channel["title"], {
        "channel_id":       channel_id,
        "channel_title":    channel["title"],
        "thumbnail":        channel["thumbnail"],
        "subscriber_count": sub,
        "avg_views":        round(avg_views),
        "view_rate":        round(view_rate, 2),
        "avg_engagement":   round(avg_engagement, 3),
        "upload_freq":      round(upload_freq, 1),
        "grade":            grade,
        "top_videos":       top_videos_hist,
    })

    return {
        "channel": {
            "id":               channel_id,
            "title":            channel["title"],
            "thumbnail":        channel["thumbnail"],
            "subscriber_count": sub,
            "video_count":      channel["video_count"],
            "published_at":     channel["published_at"][:10],
        },
        "stats": {
            "avg_views":      round(avg_views),
            "view_rate":      round(view_rate, 2),
            "avg_engagement": round(avg_engagement, 3),
            "upload_freq":    round(upload_freq, 1),
            "grade":          grade,
        },
        "diagnosis": DIAGNOSIS[grade],
        "chart_trend":      trend_list,
        "chart_engagement": eng_list,
        "raw_videos":       raw_videos,
        "mcn_thresholds":   MCN_THRESHOLDS,
    }
