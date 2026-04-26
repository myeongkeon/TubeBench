import re
import pandas as pd
from collections import Counter
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from core.api_handler import YouTubeAPIHandler
from core import history as hist

router = APIRouter()

ANALYZE_VIDEO_COUNT  = 50
DEFAULT_OUTLIER_MULT = 2.0


class CompetitorRequest(BaseModel):
    youtube_api_key:  str
    my_channel:       Optional[str] = None
    competitor_ids:   list[str]
    outlier_mult:     float = DEFAULT_OUTLIER_MULT


def _build_df(videos, stats):
    stats_map = {s["video_id"]: s for s in stats}
    rows = []
    for v in videos:
        s = stats_map.get(v["video_id"], {})
        rows.append({
            "video_id":      v["video_id"],
            "title":         v["title"],
            "published_at":  pd.to_datetime(v["published_at"]),
            "thumbnail":     v.get("thumbnail", ""),
            "view_count":    s.get("view_count", 0),
            "like_count":    s.get("like_count", 0),
            "comment_count": s.get("comment_count", 0),
            "tags":          s.get("tags", []),
        })
    return pd.DataFrame(rows).sort_values("published_at", ascending=False).reset_index(drop=True)


def _mermaid_safe(text, max_len=10):
    return re.sub(r'[:\[\]()"\'=]', '', text).strip()[:max_len] or "채널"


def _title_patterns(title):
    hints = []
    if any(c.isdigit() for c in title):      hints.append("숫자 포함")
    if "?" in title:                          hints.append("질문형")
    if any(k in title for k in ["비밀","충격","반전","놀라운","실제","진짜","최초","역대"]):
        hints.append("자극적 키워드")
    if any(k in title for k in ["방법","하는법","가이드","따라하기"]):
        hints.append("How-To형")
    if any(k in title for k in ["Top","TOP","베스트","순위","랭킹"]):
        hints.append("랭킹형")
    return hints or ["일반형"]


def _channel_summary(df, ch, multiplier):
    valid     = df[df["view_count"] > 0].copy()
    sub       = ch["subscriber_count"]
    avg_views = float(valid["view_count"].mean()) if not valid.empty else 0
    view_rate = (avg_views / sub * 100) if sub > 0 else 0
    eng_score = 0.0
    if sub > 0 and not valid.empty:
        eng_score = float(((valid["like_count"] + valid["comment_count"]) / sub * 100).mean())

    threshold = avg_views * multiplier
    outliers  = valid[valid["view_count"] >= threshold].copy()
    if not outliers.empty:
        outliers["outlier_ratio"] = outliers["view_count"] / avg_views

    outlier_list = []
    if not outliers.empty:
        for _, r in outliers.iterrows():
            outlier_list.append({
                "video_id":     r["video_id"],
                "title":        r["title"],
                "view_count":   int(r["view_count"]),
                "outlier_ratio":round(float(r["outlier_ratio"]), 1),
                "patterns":     _title_patterns(r["title"]),
                "thumbnail":    r.get("thumbnail", ""),
                "channel":      ch["title"],
            })

    return {
        "channel_id":    ch["channel_id"],
        "title":         ch["title"],
        "thumbnail":     ch["thumbnail"],
        "subscriber":    sub,
        "avg_views":     round(avg_views),
        "view_rate":     round(view_rate, 1),
        "eng_score":     round(eng_score, 2),
        "outlier_count": len(outliers),
        "outliers":      outlier_list,
        "df":            valid,
    }


def _content_gap(my_df, comp_dfs):
    my_tags = {t.lower() for tags in my_df["tags"] for t in tags}
    counter = Counter()
    for df in comp_dfs:
        for tags in df["tags"]:
            for t in tags:
                counter[t.lower()] += 1
    gap = {t: cnt for t, cnt in counter.items() if t not in my_tags and len(t) > 1}
    return sorted(gap.items(), key=lambda x: x[1], reverse=True)[:30]


@router.post("/analyze")
def analyze(req: CompetitorRequest):
    handler   = YouTubeAPIHandler(api_key=req.youtube_api_key)
    comp_data = []
    my_summary = None
    errors = []

    raw_targets = []
    if req.my_channel and req.my_channel.strip():
        raw_targets.append((req.my_channel.strip(), True))
    for cid in req.competitor_ids:
        if cid.strip():
            raw_targets.append((cid.strip(), False))

    for raw_id, is_mine in raw_targets:
        try:
            ch_id  = handler.resolve_channel_id(raw_id)
            ch_info = handler.get_channel_info(ch_id)
            if not ch_info:
                errors.append(f"채널을 찾을 수 없습니다: {raw_id}")
                continue
            videos = handler.get_channel_videos(ch_info["uploads_playlist_id"], max_results=ANALYZE_VIDEO_COUNT)
            stats  = handler.get_video_stats([v["video_id"] for v in videos])
            df     = _build_df(videos, stats)
            summ   = _channel_summary(df, ch_info, req.outlier_mult)
            if is_mine:
                my_summary = summ
            else:
                comp_data.append(summ)
        except RuntimeError as e:
            errors.append(f"API 오류 ({raw_id}): {e}")

    if not comp_data:
        return {"error": "경쟁 채널 데이터를 가져오지 못했습니다.", "errors": errors}

    # Content gap
    gap_keywords = []
    if my_summary is not None:
        gap_keywords = _content_gap(my_summary["df"], [s["df"] for s in comp_data])

    # Mermaid data for quadrant chart (send as structured data, rendered client-side)
    quadrant_points = []
    all_summaries = ([my_summary] if my_summary else []) + comp_data
    for s in all_summaries:
        quadrant_points.append({
            "label": s["title"][:12],
            "x": min(s["view_rate"] / 20, 0.95),
            "y": min(s["eng_score"] / 0.5, 0.95),
            "is_mine": s == my_summary,
        })

    # Channel comparison table
    channel_table = []
    for s in all_summaries:
        channel_table.append({
            "채널명":        s["title"],
            "구독자":        f"{s['subscriber']:,}",
            "평균 조회수":   f"{s['avg_views']:,}",
            "조회율(%)":     f"{s['view_rate']:.1f}%",
            "Engagement":    f"{s['eng_score']:.2f}%",
            "아웃라이어 수": s["outlier_count"],
            "is_mine":       s == my_summary,
        })

    all_outliers = []
    for s in comp_data:
        all_outliers.extend(s["outliers"])
    all_outliers.sort(key=lambda x: x["outlier_ratio"], reverse=True)

    # History
    hist.save_result("competitor_bench", f"경쟁사 {len(comp_data)}채널", {
        "channels":     [{k: v for k, v in r.items() if k != "is_mine"} for r in channel_table],
        "gap_keywords": gap_keywords[:20],
    })

    return {
        "channel_table":    channel_table,
        "outliers":         all_outliers,
        "gap_keywords":     gap_keywords,
        "quadrant_points":  quadrant_points,
        "errors":           errors,
    }
