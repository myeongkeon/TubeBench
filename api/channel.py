import re
import pandas as pd
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from core.api_handler import YouTubeAPIHandler
from core.ai_stream import make_sse_gen
from core import history as hist

router = APIRouter()

ANALYZE_VIDEO_COUNT = 30
MCN_THRESHOLDS = {
    "S": {"view_rate": 10.0, "engagement": 2.0},
    "A": {"view_rate": 5.0,  "engagement": 1.0},
}

AI_SYSTEM = """\
당신은 10년 경력의 MCN 채널 전략 컨설턴트입니다.
실제 YouTube 채널 데이터를 바탕으로 해당 채널에만 적용되는 구체적이고 실행 가능한 인사이트를 제공합니다.
분석은 수치 근거를 반드시 포함하고, 일반적 조언 대신 이 채널의 데이터 패턴에서 도출된 결론을 제시하세요.
한국어로 작성하세요.\
"""


class AnalyzeRequest(BaseModel):
    channel_input: str


class AISuggestRequest(BaseModel):
    model_id:       str = "gemini-2.0-flash"
    channel_title:  str
    subscriber:     int
    grade:          str
    view_rate:      float
    avg_engagement: float
    avg_views:      int
    upload_freq:    float
    trend:          str
    top_videos:     list
    low_videos:     list
    outlier_videos: list


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
    handler = YouTubeAPIHandler()

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

    # 트렌드 방향: 최근 10개 vs 이전 영상 평균 비교
    sorted_valid = valid.sort_values("published_at")
    n = len(sorted_valid)
    recent_avg = float(sorted_valid.tail(min(10, n))["view_count"].mean())
    older_avg  = float(sorted_valid.head(max(1, n - 10))["view_count"].mean()) if n > 10 else recent_avg
    if older_avg > 0:
        trend_ratio = recent_avg / older_avg
        trend = "up" if trend_ratio >= 1.15 else "down" if trend_ratio <= 0.85 else "flat"
    else:
        trend = "flat"

    # 아웃라이어 영상 (평균 2배 이상)
    outlier_videos = (
        valid[valid["view_count"] >= avg_views * 2]
        .nlargest(5, "view_count")[["title", "view_count", "engagement_rate"]]
        .round({"engagement_rate": 2})
        .to_dict("records")
    )

    # 저성과 영상 (평균 50% 미만, 최소 5개 이상 있을 때)
    low_videos = []
    if n >= 5:
        low_videos = (
            valid[valid["view_count"] < avg_views * 0.5]
            .nsmallest(5, "view_count")[["title", "view_count", "engagement_rate"]]
            .round({"engagement_rate": 2})
            .to_dict("records")
        )

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
            "trend":          trend,
        },
        "ai_context": {
            "channel_title":    channel["title"],
            "subscriber":       sub,
            "grade":            grade,
            "view_rate":        round(view_rate, 2),
            "avg_engagement":   round(avg_engagement, 3),
            "avg_views":        round(avg_views),
            "upload_freq":      round(upload_freq, 1),
            "trend":            trend,
            "top_videos":       (
                valid.nlargest(5, "engagement_rate")[["title", "view_count", "engagement_rate"]]
                .round({"engagement_rate": 2})
                .to_dict("records")
            ),
            "low_videos":       low_videos,
            "outlier_videos":   outlier_videos,
        },
        "chart_trend":      trend_list,
        "chart_engagement": eng_list,
        "raw_videos":       raw_videos,
        "mcn_thresholds":   MCN_THRESHOLDS,
    }


def _build_ai_prompt(req: AISuggestRequest) -> str:
    trend_kor = {"up": "상승", "down": "하락", "flat": "보합"}.get(req.trend, req.trend)
    freq_str  = f"{req.upload_freq:.1f}일에 1회" if req.upload_freq > 0 else "불규칙"

    top_str = "\n".join(
        f"  - {v['title'][:40]} | 조회 {v['view_count']:,} | 참여율 {v['engagement_rate']:.2f}%"
        for v in req.top_videos
    )
    low_str = "\n".join(
        f"  - {v['title'][:40]} | 조회 {v['view_count']:,} | 참여율 {v['engagement_rate']:.2f}%"
        for v in req.low_videos
    ) or "  (데이터 없음)"
    out_str = "\n".join(
        f"  - {v['title'][:40]} | 조회 {v['view_count']:,} | 참여율 {v['engagement_rate']:.2f}%"
        for v in req.outlier_videos
    ) or "  (데이터 없음)"

    return f"""\
[채널 데이터]
채널명: {req.channel_title}
구독자: {req.subscriber:,}명
MCN 등급: {req.grade}등급
평균 조회수: {req.avg_views:,}회
조회율(조회수/구독자): {req.view_rate:.2f}%
평균 참여율: {req.avg_engagement:.3f}%
업로드 주기: {freq_str}
최근 트렌드: {trend_kor}

[참여율 상위 영상 TOP 5]
{top_str}

[저성과 영상 (평균 50% 미만)]
{low_str}

[아웃라이어 영상 (평균 2배 이상)]
{out_str}

위 데이터를 바탕으로 이 채널({req.channel_title})에만 해당하는 구체적인 개선 인사이트를 제공하세요.

다음 항목을 반드시 포함하세요:
1. **채널 현황 진단** — 수치를 인용하여 현재 성과의 강점과 약점을 구체적으로 설명
2. **고성과 콘텐츠 패턴 분석** — 상위 영상에서 발견되는 공통 패턴(제목, 주제, 형식 등)과 그 이유
3. **저성과 원인 분석** — 저성과 영상이 왜 낮은 성과를 보이는지 구체적인 가설 제시
4. **즉시 실행 가능한 개선 전략 3가지** — 이 채널의 데이터에서 도출된 전략 (일반론 금지)
5. **업로드 전략 최적화** — 현재 {freq_str} 주기와 트렌드({trend_kor}) 기반으로 업로드 빈도/타이밍 조언

수치 근거를 반드시 포함하고, 이 채널 데이터에서만 도출 가능한 인사이트를 제공하세요."""


@router.post("/ai-suggestions")
def ai_suggestions(req: AISuggestRequest):
    prompt = _build_ai_prompt(req)
    gen = make_sse_gen(req.model_id, AI_SYSTEM, prompt)
    return StreamingResponse(gen(), media_type="text/event-stream")
