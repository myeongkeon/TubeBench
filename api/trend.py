import json
from datetime import datetime, timezone, timedelta
from collections import Counter
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from core.api_handler import YouTubeAPIHandler
from core import history as hist
from modules.channel_profiles import list_profiles, load_profile, save_profile, delete_profile

router = APIRouter()

TREND_DAYS     = 3
MAX_PER_CH     = 10

TREND_SYSTEM = """\
당신은 실시간 YouTube 트렌드를 분석하는 MCN 콘텐츠 전략가입니다.
경쟁채널 데이터를 바탕으로 지금 당장 올릴 수 있는 트렌드 영상을 추천합니다.
분석은 데이터 기반으로, 추천은 실행 가능하도록 구체적으로 작성하세요.\
"""

COMMENT_SYSTEM = """\
당신은 YouTube 시청자 심리 분석 전문가이자 MCN 콘텐츠 기획자입니다.
댓글 데이터에서 시청자의 니즈, 불만, 요청사항(VOC)을 파악하여
새로운 영상 기획안을 제시합니다. 분석은 구체적이고 실행 가능하게 한국어로 작성하세요.\
"""


class TrendAnalyzeRequest(BaseModel):
    youtube_api_key:  str
    my_channel_id:    str
    competitor_ids:   list[str]


class TrendStreamRequest(BaseModel):
    gemini_api_key:   Optional[str] = None
    anthropic_api_key: Optional[str] = None
    model_id:         str = "gemini-2.0-flash"
    my_channel_title: str
    summary_text:     str


class CommentStreamRequest(BaseModel):
    gemini_api_key:   Optional[str] = None
    anthropic_api_key: Optional[str] = None
    model_id:         str = "gemini-2.0-flash"
    video_title:      str
    keyword:          str
    comments:         list[dict]


class ProfileSaveRequest(BaseModel):
    youtube_api_key: str
    my_channel:      str
    competitors:     list[str]


def _velocity_score(view_count, published_at):
    pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    hours = max((datetime.now(timezone.utc) - pub).total_seconds() / 3600, 1)
    return view_count / hours


def _title_patterns(title):
    hints = []
    if any(c.isdigit() for c in title):      hints.append("숫자형")
    if "?" in title:                          hints.append("질문형")
    if any(k in title for k in ["비밀","충격","반전","놀라운","실제","진짜","최초","역대"]):
        hints.append("자극형")
    if any(k in title for k in ["방법","하는법","가이드","따라하기"]):
        hints.append("How-To형")
    if any(k in title for k in ["Top","TOP","베스트","순위","랭킹"]):
        hints.append("랭킹형")
    return hints or ["일반형"]


@router.post("/analyze")
def analyze(req: TrendAnalyzeRequest):
    handler  = YouTubeAPIHandler(api_key=req.youtube_api_key)
    cutoff   = datetime.now(timezone.utc) - timedelta(days=TREND_DAYS)
    errors   = []
    comp_data = []

    # My channel info
    my_channel_title = req.my_channel_id
    try:
        my_id   = handler.resolve_channel_id(req.my_channel_id)
        my_info = handler.get_channel_info(my_id)
        if my_info:
            my_channel_title = my_info["title"]
    except Exception as e:
        errors.append(str(e))

    for raw_id in req.competitor_ids:
        if not raw_id.strip():
            continue
        try:
            ch_id   = handler.resolve_channel_id(raw_id.strip())
            ch_info = handler.get_channel_info(ch_id)
            if not ch_info:
                continue
            videos = handler.get_channel_videos(ch_info["uploads_playlist_id"], max_results=MAX_PER_CH)
            recent_videos = [
                v for v in videos
                if datetime.fromisoformat(v["published_at"].replace("Z", "+00:00")) >= cutoff
            ]
            if not recent_videos:
                continue
            stats = handler.get_video_stats([v["video_id"] for v in recent_videos])
            stats_map = {s["video_id"]: s for s in stats}

            enriched = []
            for v in recent_videos:
                s = stats_map.get(v["video_id"], {})
                vcount = s.get("view_count", 0)
                enriched.append({
                    "video_id":     v["video_id"],
                    "title":        v["title"],
                    "published_at": v["published_at"][:10],
                    "view_count":   vcount,
                    "velocity":     round(_velocity_score(vcount, v["published_at"]), 1),
                    "patterns":     " / ".join(_title_patterns(v["title"])),
                    "tags":         s.get("tags", []),
                    "comment_count": s.get("comment_count", 0),
                })
            comp_data.append({"channel_id": ch_id, "title": ch_info["title"], "videos": enriched})
        except RuntimeError as e:
            errors.append(f"{raw_id}: {e}")

    if not comp_data:
        return {"error": "최근 3일 내 업로드 영상이 없거나 데이터를 가져오지 못했습니다.", "errors": errors}

    # Build summary for AI
    rows = []
    for ch in comp_data:
        for v in ch["videos"]:
            rows.append({**v, "channel": ch["title"]})
    rows.sort(key=lambda x: x["velocity"], reverse=True)

    lines = []
    for r in rows[:15]:
        lines.append(
            f"- [{r['channel']}] \"{r['title']}\" | 조회수 {r['view_count']:,} "
            f"| 속도 {r['velocity']:.0f}회/h | 패턴: {r['patterns']}"
        )
    all_tags = [t for r in rows for t in r["tags"]]
    top_tags = [t for t, _ in Counter(all_tags).most_common(10)]
    summary_text = "\n".join(lines)
    if top_tags:
        summary_text += f"\n\n공통 태그 키워드: {', '.join(top_tags)}"

    return {
        "my_channel_title": my_channel_title,
        "comp_data":        comp_data,
        "summary_text":     summary_text,
        "video_rows":       rows,
        "errors":           errors,
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


def _make_sse(req_model, system, prompt_text, hist_tab, hist_label, hist_extra):
    def gen():
        full_text = ""
        is_gemini = not req_model.model_id.startswith("claude")
        try:
            if is_gemini and req_model.gemini_api_key:
                for chunk in _stream_gemini(req_model.gemini_api_key, req_model.model_id, system, prompt_text):
                    full_text += chunk
                    yield f"data: {json.dumps({'text': chunk})}\n\n"
            elif not is_gemini and req_model.anthropic_api_key:
                for chunk in _stream_claude(req_model.anthropic_api_key, req_model.model_id, system, prompt_text):
                    full_text += chunk
                    yield f"data: {json.dumps({'text': chunk})}\n\n"
            else:
                yield f"data: {json.dumps({'error': 'API 키가 없습니다.'})}\n\n"
                return
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        if full_text:
            hist.save_result(hist_tab, hist_label, {**hist_extra, "output": full_text})
        yield f"data: {json.dumps({'done': True})}\n\n"
    return gen


@router.post("/stream")
def stream_trend(req: TrendStreamRequest):
    prompt = f"""\
## 내 채널
{req.my_channel_title}

## 경쟁채널 최근 {TREND_DAYS}일 업로드 현황 (조회 속도 높은 순)
{req.summary_text}

## 요청
위 경쟁채널 데이터를 MCN 전략가 관점에서 분석해 다음을 작성해 주세요.

### 📡 지금 뜨는 트렌드 키워드 TOP 5
각 키워드가 왜 지금 뜨고 있는지 근거(어느 채널, 어떤 영상) 포함

### 🎬 오늘 올리면 좋을 영상 추천 3개
각 추천마다:
- **제목 후보 3개** (숫자형·질문형·자극형 혼합)
- **왜 지금인가**: 경쟁채널 근거 + 트렌드 타이밍 설명
- **차별화 포인트**: 경쟁채널 영상과 다르게 만들 핵심 1가지

### ⚡ 긴급도
HIGH / MEDIUM / LOW 중 하나와 이유 (트렌드 수명 예측)\
"""
    gen = _make_sse(req, TREND_SYSTEM, prompt, "trend_planner",
                    req.my_channel_title[:30],
                    {"my_channel": req.my_channel_title, "competitor_count": 0, "videos_analyzed": 0})
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/comment-stream")
def stream_comment(req: CommentStreamRequest):
    top = sorted(req.comments, key=lambda c: c.get("like_count", 0), reverse=True)[:30]
    comment_lines = [f'[좋아요 {c["like_count"]}] {c["text"]}' for c in top]
    prompt = f"""\
## 분석 키워드: "{req.keyword}"
## 분석 영상: "{req.video_title}"

## 시청자 댓글 (좋아요 높은 순 상위 30개)
{chr(10).join(comment_lines)}

## 요청
### 1. 시청자 VOC 분석
- **원하는 것 TOP 5**: 시청자가 가장 많이 원하는 내용
- **불만 및 아쉬운 점**: 현재 콘텐츠에서 부족한 것
- **질문 및 요청사항**: 시청자가 명시적으로 요청하는 내용

### 2. 새로운 영상 기획안 3개
각 기획안마다:
- **제목**: 클릭률 높은 제목
- **핵심 아이디어**: 댓글 니즈를 어떻게 충족할 것인가
- **차별화 포인트**: 기존 영상과 다른 점

### 3. 영상 도입부 훅(Hook) 문장 3개
댓글에서 발견한 시청자 언어를 활용한 도입부 멘트\
"""
    gen = _make_sse(req, COMMENT_SYSTEM, prompt, "trend_planner",
                    req.video_title[:30], {"video_title": req.video_title})
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/profiles")
def get_profiles():
    return {"profiles": list_profiles()}


@router.post("/profiles/save")
def save_profile_endpoint(req: ProfileSaveRequest):
    handler = YouTubeAPIHandler(api_key=req.youtube_api_key)
    errors  = []
    try:
        my_id   = handler.resolve_channel_id(req.my_channel)
        my_info = handler.get_channel_info(my_id)
        if not my_info:
            return {"error": f"채널을 찾을 수 없습니다: {req.my_channel}"}
        my_ch = {"channel_id": my_id, "title": my_info["title"], "thumbnail": my_info["thumbnail"]}
        competitors = []
        for raw in req.competitors:
            try:
                cid  = handler.resolve_channel_id(raw.strip())
                info = handler.get_channel_info(cid)
                if info:
                    competitors.append({"channel_id": cid, "title": info["title"], "thumbnail": info["thumbnail"]})
            except RuntimeError as e:
                errors.append(str(e))
        save_profile(my_ch, competitors)
        return {"ok": True, "my_channel": my_ch, "competitors": competitors, "errors": errors}
    except RuntimeError as e:
        return {"error": str(e)}


@router.get("/profiles/{channel_id}/competitors")
def get_competitors(channel_id: str):
    profile = load_profile(channel_id)
    if not profile:
        return {"competitors": []}
    return {"competitors": profile.get("competitors", [])}


@router.delete("/profiles/{channel_id}")
def delete_profile_endpoint(channel_id: str):
    ok = delete_profile(channel_id)
    return {"ok": ok}


@router.get("/comments")
def get_comments(youtube_api_key: str, video_id: str, max_results: int = 100):
    handler  = YouTubeAPIHandler(api_key=youtube_api_key)
    comments = handler.get_video_comments(video_id, max_results=max_results)
    return {"comments": comments}
