import json
import statistics
from datetime import datetime, timezone
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from core.api_handler import YouTubeAPIHandler
from core import history as hist

router = APIRouter()

KEYWORD_SYSTEM = """\
당신은 YouTube SEO 전문가이자 MCN 콘텐츠 전략가입니다.
키워드 분석 데이터를 바탕으로 해당 키워드의 성공 가능성과 영상 기획 방향을 제시합니다.
분석은 구체적이고 실행 가능하게, 한국어로 작성하세요.\
"""

COMMENT_SYSTEM = """\
당신은 YouTube 시청자 심리 분석 전문가이자 MCN 콘텐츠 기획자입니다.
댓글 데이터에서 시청자의 니즈, 불만, 요청사항(VOC)을 파악하여
새로운 영상 기획안을 제시합니다. 분석은 구체적이고 실행 가능하게 한국어로 작성하세요.\
"""


class KeywordRequest(BaseModel):
    youtube_api_key: str
    keyword:         str
    max_results:     int = 20


class KeywordAIRequest(BaseModel):
    gemini_api_key:   Optional[str] = None
    anthropic_api_key: Optional[str] = None
    model_id:         str = "gemini-2.0-flash"
    keyword:          str
    score:            dict
    videos:           list[dict]
    stats:            list[dict]


class CommentAIRequest(BaseModel):
    gemini_api_key:   Optional[str] = None
    anthropic_api_key: Optional[str] = None
    model_id:         str = "gemini-2.0-flash"
    video_title:      str
    keyword:          str
    comments:         list[dict]


def _compute_score(stats):
    if not stats:
        return {"total": 0, "viral": 0, "engagement": 0, "trend": 0, "opportunity": 0,
                "avg_views": 0, "avg_eng_rate": 0.0, "avg_velocity": 0.0}

    now = datetime.now(timezone.utc)
    view_counts = [s["view_count"] for s in stats]
    avg_views = statistics.mean(view_counts)

    if avg_views >= 2_000_000:   viral = 30
    elif avg_views >= 1_000_000: viral = 27
    elif avg_views >= 500_000:   viral = 23
    elif avg_views >= 100_000:   viral = 18
    elif avg_views >= 50_000:    viral = 13
    elif avg_views >= 10_000:    viral = 8
    else:                        viral = 4

    eng_rates = []
    for s in stats:
        if s["view_count"] > 0:
            eng_rates.append((s["like_count"] + s["comment_count"]) / s["view_count"])
    avg_eng = statistics.mean(eng_rates) if eng_rates else 0.0

    if avg_eng >= 0.08:     engagement = 20
    elif avg_eng >= 0.05:   engagement = 17
    elif avg_eng >= 0.03:   engagement = 14
    elif avg_eng >= 0.015:  engagement = 10
    elif avg_eng >= 0.005:  engagement = 6
    else:                   engagement = 2

    recent_30d = sum(
        1 for s in stats
        if (now - datetime.fromisoformat(s["published_at"].replace("Z", "+00:00"))).days <= 30
    )
    freq_ratio = recent_30d / len(stats)
    if freq_ratio >= 0.6:   freq_score = 12
    elif freq_ratio >= 0.4: freq_score = 9
    elif freq_ratio >= 0.2: freq_score = 6
    else:                   freq_score = 3

    velocities = []
    for s in stats:
        pub = datetime.fromisoformat(s["published_at"].replace("Z", "+00:00"))
        hours = max((now - pub).total_seconds() / 3600, 1)
        if hours <= 720:
            velocities.append(s["view_count"] / hours)
    avg_vel = statistics.mean(velocities) if velocities else 0.0

    if avg_vel >= 5000:     vel_score = 13
    elif avg_vel >= 2000:   vel_score = 10
    elif avg_vel >= 500:    vel_score = 7
    elif avg_vel >= 100:    vel_score = 4
    else:                   vel_score = 1

    trend = freq_score + vel_score

    sorted_v = sorted(view_counts)
    n = len(sorted_v)
    total_v = sum(sorted_v)
    if n > 1 and total_v > 0:
        cum  = sum((i + 1) * v for i, v in enumerate(sorted_v))
        gini = max(0.0, min(1.0, (2 * cum) / (n * total_v) - (n + 1) / n))
        opportunity = round(25 * (1 - gini))
    else:
        opportunity = 12

    return {
        "total":        min(100, viral + engagement + trend + opportunity),
        "viral":        viral,
        "engagement":   engagement,
        "trend":        trend,
        "opportunity":  opportunity,
        "avg_views":    round(avg_views),
        "avg_eng_rate": round(avg_eng * 100, 2),
        "avg_velocity": round(avg_vel, 1),
    }


@router.post("/analyze")
def analyze(req: KeywordRequest):
    handler = YouTubeAPIHandler(api_key=req.youtube_api_key)
    videos  = handler.search_videos_by_keyword(req.keyword, max_results=req.max_results)
    if not videos:
        return {"error": f"'{req.keyword}' 키워드 검색 결과가 없습니다."}

    video_ids = [v["video_id"] for v in videos]
    stats     = handler.get_video_stats(video_ids)
    score     = _compute_score(stats)

    stats_map = {s["video_id"]: s for s in stats}
    video_list = []
    for v in videos:
        s = stats_map.get(v["video_id"], {})
        video_list.append({
            "video_id":     v["video_id"],
            "title":        v["title"],
            "channel_title": v["channel_title"],
            "published_at": v["published_at"][:10],
            "view_count":   s.get("view_count", 0),
            "like_count":   s.get("like_count", 0),
            "comment_count": s.get("comment_count", 0),
            "thumbnail":    v.get("thumbnail", ""),
        })

    return {
        "keyword": req.keyword,
        "score":   score,
        "videos":  video_list,
        "stats":   stats,
    }


def _stream_gemini(api_key, model_id, system, prompt):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name=model_id, system_instruction=system)
    response = model.generate_content(prompt, stream=True)
    for chunk in response:
        try:
            text = chunk.text
        except (ValueError, AttributeError):
            continue
        if text:
            yield text


def _stream_claude(api_key, model_id, system, prompt):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    with client.messages.stream(
        model=model_id, max_tokens=3000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for chunk in stream.text_stream:
            yield chunk


def _sse_gen(api_keys_model, system, prompt, tab, label, extra):
    def gen():
        full = ""
        is_gemini = not api_keys_model["model_id"].startswith("claude")
        try:
            if is_gemini and api_keys_model.get("gemini_api_key"):
                for chunk in _stream_gemini(api_keys_model["gemini_api_key"], api_keys_model["model_id"], system, prompt):
                    full += chunk
                    yield f"data: {json.dumps({'text': chunk})}\n\n"
            elif not is_gemini and api_keys_model.get("anthropic_api_key"):
                for chunk in _stream_claude(api_keys_model["anthropic_api_key"], api_keys_model["model_id"], system, prompt):
                    full += chunk
                    yield f"data: {json.dumps({'text': chunk})}\n\n"
            else:
                yield f"data: {json.dumps({'error': 'API 키가 없습니다.'})}\n\n"
                return
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return
        if full:
            hist.save_result(tab, label, {**extra, "output": full})
        yield f"data: {json.dumps({'done': True})}\n\n"
    return gen


@router.post("/ai-stream")
def ai_stream(req: KeywordAIRequest):
    stats_map = {s["video_id"]: s for s in req.stats}
    lines = []
    for v in req.videos[:10]:
        s = stats_map.get(v["video_id"], {})
        lines.append(
            f'- "{v["title"][:60]}" ({v.get("channel_title","")}) '
            f'| 조회수 {s.get("view_count", 0):,} | 좋아요 {s.get("like_count", 0):,}'
        )
    prompt = f"""\
## 분석 키워드: "{req.keyword}"
## 점수 결과
- 종합 점수: {req.score["total"]}/100
- 바이럴 잠재력: {req.score["viral"]}/30 (평균 조회수 {req.score["avg_views"]:,}회)
- 참여도: {req.score["engagement"]}/20 (평균 참여율 {req.score["avg_eng_rate"]}%)
- 트렌드 현황: {req.score["trend"]}/25 (평균 조회 속도 {req.score["avg_velocity"]}회/h)
- 진입 기회: {req.score["opportunity"]}/25
## 상위 검색 결과 영상
{chr(10).join(lines)}
## 요청
### 1. 점수 해석
### 2. 성공 전략 3가지
### 3. 제목 후보 5개
### 4. 주의사항
### 5. 최적 업로드 전략\
"""
    keys = {"gemini_api_key": req.gemini_api_key, "anthropic_api_key": req.anthropic_api_key,
            "model_id": req.model_id}
    gen = _sse_gen(keys, KEYWORD_SYSTEM, prompt, "keyword_analyzer", req.keyword[:30],
                   {"keyword": req.keyword, "score": req.score})
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/comment-stream")
def comment_stream(req: CommentAIRequest):
    top = sorted(req.comments, key=lambda c: c.get("like_count", 0), reverse=True)[:30]
    comment_lines = [f'[좋아요 {c["like_count"]}] {c["text"]}' for c in top]
    prompt = f"""\
## 분석 키워드: "{req.keyword}"
## 분석 영상: "{req.video_title}"
## 시청자 댓글 (좋아요 높은 순 상위 30개)
{chr(10).join(comment_lines)}
## 요청
### 1. 시청자 VOC 분석
### 2. 새로운 영상 기획안 3개
### 3. 영상 도입부 훅(Hook) 문장 3개\
"""
    keys = {"gemini_api_key": req.gemini_api_key, "anthropic_api_key": req.anthropic_api_key,
            "model_id": req.model_id}
    gen = _sse_gen(keys, COMMENT_SYSTEM, prompt, "keyword_analyzer",
                   req.video_title[:30], {"video_title": req.video_title})
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/comments")
def get_comments(youtube_api_key: str, video_id: str, max_results: int = 100):
    handler  = YouTubeAPIHandler(api_key=youtube_api_key)
    comments = handler.get_video_comments(video_id, max_results=max_results)
    return {"comments": comments}
