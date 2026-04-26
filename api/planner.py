import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from core import history as hist

router = APIRouter()

SYSTEM_PROMPT = """\
당신은 대형 MCN의 수석 YouTube 콘텐츠 전략가이자 기획 전문가입니다.
데이터 기반 분석을 통해 클릭률(CTR)과 시청 유지율을 극대화하는 콘텐츠를 기획합니다.

## MCN Hook-Body-CTA 3단계 기획 프레임워크

**Hook (0~30초)** — 이탈 방지 오프닝
- 시청자가 "이거 끝까지 봐야겠다"고 결심하게 만드는 구간
- 효과적 패턴: 충격 사실 제시 / 역설적 질문 / 공감 유발 / 결과 미리 보여주기

**Body (본문)** — 핵심 정보 전달 + 유지율 유지
- 3~5개 핵심 포인트로 구조화 (소주제 명확히 구분)
- 중간 이탈 방지: "이후 더 놀라운 내용이…" 같은 예고 삽입
- 시각 자료 큐: 차트·자막·B-Roll 활용 포인트 구체적으로 제안

**CTA (마지막 30초)** — 행동 유도
- 구독·좋아요·댓글 직접 요청 + 이유 제시
- 다음 영상 예고로 연속 시청 유도

## 출력 형식 (반드시 아래 순서대로 작성)

### 🎯 CTR 최적화 제목 5개
숫자형 / 질문형 / 자극형 / How-To형 / 비밀폭로형 등 다양한 패턴 적용

### 🖼️ 썸네일 컨셉 3개
배경색 / 메인 텍스트 / 표정·제스처 / 보조 요소를 구체적으로 기술

### 📝 Hook-Body-CTA 스크립트 구조
각 단계별 핵심 대사 초안 + 연출 포인트 (자막, 컷 타이밍 등)

### 🏷️ 태그 추천 20개
메인 키워드 + 롱테일 키워드 혼합

### 📊 기획 효과 분석
왜 이 기획이 높은 CTR과 유지율을 만들어낼 수 있는지 MCN 데이터 관점에서 설명\
"""


class PlannerRequest(BaseModel):
    gemini_api_key:   Optional[str] = None
    anthropic_api_key: Optional[str] = None
    model_id:         str = "gemini-2.0-flash"
    topic:            str
    channel_info:     Optional[str] = None
    target_length:    Optional[str] = None
    outlier_data:     Optional[str] = None
    gap_keywords:     Optional[str] = None


def _build_prompt(req: PlannerRequest) -> str:
    parts = [f"## 기획 요청\n**주제·키워드**: {req.topic}"]
    if req.channel_info:
        parts.append(f"**채널 정보**: {req.channel_info}")
    if req.target_length and req.target_length != "미정":
        parts.append(f"**목표 영상 길이**: {req.target_length}")
    if req.outlier_data:
        parts.append(f"\n## 참고: 경쟁사 아웃라이어 영상\n{req.outlier_data.strip()}")
    if req.gap_keywords:
        parts.append(f"\n## 참고: Content Gap 키워드\n{req.gap_keywords.strip()}")
    parts.append("\n위 데이터를 바탕으로 MCN 기획 프레임워크에 맞는 완성도 높은 영상 기획안을 작성해 주세요.")
    return "\n".join(parts)


def _stream_gemini(api_key, model_id, prompt):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model    = genai.GenerativeModel(model_name=model_id, system_instruction=SYSTEM_PROMPT)
    response = model.generate_content(prompt, stream=True)
    for chunk in response:
        try:
            text = chunk.text
        except (ValueError, AttributeError):
            continue
        if text:
            yield text


def _stream_claude(api_key, model_id, prompt):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    with client.messages.stream(
        model=model_id,
        max_tokens=4096,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for chunk in stream.text_stream:
            yield chunk


def _sse_generator(req: PlannerRequest):
    prompt = _build_prompt(req)
    is_gemini = not req.model_id.startswith("claude")
    full_text = ""

    try:
        if is_gemini and req.gemini_api_key:
            for chunk in _stream_gemini(req.gemini_api_key, req.model_id, prompt):
                full_text += chunk
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        elif not is_gemini and req.anthropic_api_key:
            for chunk in _stream_claude(req.anthropic_api_key, req.model_id, prompt):
                full_text += chunk
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        else:
            yield f"data: {json.dumps({'error': 'API 키가 없습니다.'})}\n\n"
            return
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        return

    if full_text:
        hist.save_result("ai_planner", req.topic[:40], {
            "model":         req.model_id,
            "topic":         req.topic,
            "channel_info":  req.channel_info or "",
            "target_length": req.target_length or "",
            "output":        full_text,
        })

    yield f"data: {json.dumps({'done': True})}\n\n"


@router.post("/stream")
def stream(req: PlannerRequest):
    return StreamingResponse(
        _sse_generator(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
