import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from core import history as hist

router = APIRouter()

SYSTEM_PROMPT = """\
당신은 국내 최고 수준의 YouTube 카피라이터 겸 MCN 콘텐츠 전략가입니다.
채널 스타일·감정 트리거·제목 길이를 정밀하게 조합해 클릭률(CTR)을 극대화하는 제목을 생성합니다.
반드시 한국어로 작성하고, 지정된 출력 형식을 정확히 따르세요.\
"""

STYLES = {
    "📺 1분 미만 스타일":    "초단형 쇼츠 채널 스타일. 제목 10자 이내, 충격·반전·궁금증 유발.",
    "✂️ 짤컷 스타일":        "밈·짤 기반 숏폼. 유행어·공감 상황, 친근하고 캐주얼.",
    "💻 테크":               "IT·기술·리뷰. 스펙 숫자 비교, '최초·역대급', 구체적 제품명.",
    "🏠 일상·살림":          "라이프스타일. 따뜻한 어조, '나만 몰랐던·우리집', 절약·효율.",
    "✈️ 여행":               "여행 브이로그. 장소명 필수, 설렘·경이로움, '현지인만 아는'.",
    "🎯 취미":               "취미·DIY. '같이 해봐요·초보도 가능·쉽게·10분 만에'.",
    "🎮 게임":               "게임. 티어·랭크·기록 숫자, '개사기·OP', 공략·비법.",
    "😂 예능·유머":          "예능·버라이어티. 반전 구도, 과장된 표현, 의성어·이모지.",
    "📰 정보·교육":          "정보·교육·다큐. 숫자·통계·출처, '모르면 손해·필수', 리스트형.",
    "⭐ MCN 기본 (Hook 최적화)": "MCN 표준 Hook 최적화. CTR·시청 유지율 균형형.",
}

EMOTION_TRIGGERS = {
    "🤔 호기심":    "시청자가 '어떻게?'라고 궁금해하게 만드는 미완성 정보 제공",
    "😱 충격·공포": "예상을 깨는 충격적 사실, '이걸 모르면 큰일' 위기감",
    "😊 공감":      "시청자의 일상 상황·감정과 즉각 연결되는 친근감",
    "😄 유머":      "가볍게 웃을 수 있는 반전·말장난·밈 감성",
    "😲 놀라움":    "기대 이상의 결과, 상식 뒤집기, '세상에 이런 일이' 감탄",
}

LENGTH_OPTIONS = {
    "일반형 (30~40자)":        "제목 30~40자, 검색 노출과 CTR 균형",
    "쇼츠 초단형 (15자 이내)": "15자 이내 초단형, 쇼츠·릴스 최적화",
    "검색 롱테일 (45자 이상)": "45자 이상, 검색 키워드 풍부하게 포함",
}


class CopywriterRequest(BaseModel):
    gemini_api_key:   Optional[str] = None
    anthropic_api_key: Optional[str] = None
    model_id:         str = "gemini-2.0-flash"
    keyword:          str
    content:          str
    style_key:        str = "⭐ MCN 기본 (Hook 최적화)"
    emotion_key:      str = "🤔 호기심"
    length_key:       str = "일반형 (30~40자)"


@router.get("/options")
def get_options():
    return {
        "styles":          list(STYLES.keys()),
        "emotion_triggers": list(EMOTION_TRIGGERS.keys()),
        "length_options":  list(LENGTH_OPTIONS.keys()),
    }


def _build_prompt(req: CopywriterRequest) -> str:
    style   = STYLES.get(req.style_key, "")
    emotion = EMOTION_TRIGGERS.get(req.emotion_key, "")
    length  = LENGTH_OPTIONS.get(req.length_key, "")
    return f"""\
## 카피라이팅 요청

**키워드**: {req.keyword}
**영상 내용**: {req.content}
**스타일**: {req.style_key} — {style}
**감정 트리거**: {req.emotion_key} — {emotion}
**제목 길이**: {req.length_key} — {length}

## 출력 형식 (반드시 아래 순서로 작성)

### 🎯 제목 후보 5개
각 제목 뒤에 한 줄로 [CTR 포인트: 이 제목이 클릭을 유도하는 핵심 이유] 작성.
패턴을 다양하게: 숫자형 / 질문형 / 자극형 / How-To형 / 반전형

### 🖼️ 썸네일 텍스트 3세트
각 세트: 메인 텍스트(3~5단어) + 서브 텍스트(2~3단어, 선택) + 배경 컬러 제안

### 🏷️ 해시태그 10개
메인 키워드 5개 + 롱테일 키워드 5개

### 💡 카피라이팅 전략 메모
선택한 스타일·감정 트리거가 이 주제에 효과적인 이유 2~3줄\
"""


def _stream_gemini(api_key, model_id, prompt):
    import google.generativeai as genai
    gemini_models = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"]
    target = model_id if model_id in gemini_models else "gemini-2.0-flash"
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name=target, system_instruction=SYSTEM_PROMPT)
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
        model=model_id, max_tokens=3000,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for chunk in stream.text_stream:
            yield chunk


def _sse_generator(req: CopywriterRequest):
    prompt    = _build_prompt(req)
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
        hist.save_result("copywriter", req.keyword[:30], {
            "keyword":   req.keyword,
            "style":     req.style_key,
            "emotion":   req.emotion_key,
            "length":    req.length_key,
            "model":     req.model_id,
            "output":    full_text,
        })
    yield f"data: {json.dumps({'done': True})}\n\n"


@router.post("/stream")
def stream(req: CopywriterRequest):
    return StreamingResponse(
        _sse_generator(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
