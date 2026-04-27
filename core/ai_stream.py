"""공통 AI 스트리밍 유틸리티 — Gemini / Claude 키 자동 로테이션 포함"""
import json
import time
from core import key_manager


def _is_quota_error(e: Exception) -> bool:
    """할당량/속도 제한 오류인지 정확히 판별 (타입 우선, 문자열 보조)"""
    # Gemini: google.api_core.exceptions.ResourceExhausted (HTTP 429)
    try:
        from google.api_core.exceptions import ResourceExhausted
        if isinstance(e, ResourceExhausted):
            return True
    except ImportError:
        pass
    # Anthropic: anthropic.RateLimitError (HTTP 429)
    try:
        import anthropic as _ant
        if isinstance(e, _ant.RateLimitError):
            return True
    except ImportError:
        pass
    # Anthropic billing / credit exhausted (HTTP 400)
    s_low = str(e).lower()
    if "credit balance" in s_low or "insufficient_quota" in s_low:
        return True
    # 최후 수단: HTTP 429 + quota 관련 단어가 함께 있어야 매칭
    s = str(e)
    if "429" in s:
        low = s.lower()
        return any(x in low for x in ["quota", "exhausted", "rate limit", "resource has been"])
    return False


def _error_type(e: Exception) -> str:
    """quota (24h) vs rate_limit (60s) 구분"""
    try:
        import anthropic as _ant
        if isinstance(e, _ant.RateLimitError):
            return "rate_limit"
    except ImportError:
        pass
    s = str(e).lower()
    # billing / credit error → treat as quota (24h)
    if "credit balance" in s or "insufficient_quota" in s:
        return "quota"
    return "quota" if any(x in s for x in ["quota", "exhausted"]) else "rate_limit"


def _stream_gemini(api_key: str, model_id: str, system: str, prompt: str):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name=model_id, system_instruction=system)
    response = model.generate_content(prompt, stream=True)
    for chunk in response:
        try:
            text = chunk.text
        except ValueError:
            # 안전 필터 차단된 청크 — 건너뜀 (할당량 오류 아님)
            continue
        except AttributeError:
            continue
        if text:
            yield text


def _stream_claude(api_key: str, model_id: str, system: str, prompt: str):
    import anthropic as ant
    client = ant.Anthropic(api_key=api_key)
    with client.messages.stream(
        model=model_id,
        max_tokens=3000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for chunk in stream.text_stream:
            yield chunk


def make_sse_gen(model_id: str, system: str, prompt: str, on_complete=None):
    """
    SSE 제너레이터 반환. 키 할당량 초과 시 다음 키로 자동 전환.
    on_complete(full_text): 스트리밍 완료 후 호출되는 콜백 (기록 저장 등)
    """
    def gen():
        is_gemini = not model_id.startswith("claude")
        pool = key_manager.gemini if is_gemini else key_manager.anthropic
        tried: set = set()
        full = ""
        waited_for_rate = False

        while True:
            key = pool.get()
            if not key or key in tried:
                # 모든 키가 rate_limit 상태라면 1회 한해 자동 대기 후 재시도
                if not waited_for_rate:
                    wait = pool.min_rate_wait()
                    if wait is not None and wait <= 65:
                        waited_for_rate = True
                        tried.clear()
                        time.sleep(wait + 1)
                        continue
                active = [k for k in pool.status() if k["status"] == "active"]
                if not active:
                    msg = "사용 가능한 AI API 키가 없습니다. 시스템 메뉴에서 키 상태를 확인하세요."
                else:
                    msg = "모든 키를 시도했지만 응답을 받지 못했습니다."
                yield f"data: {json.dumps({'error': msg})}\n\n"
                return
            tried.add(key)

            try:
                stream_fn = _stream_gemini if is_gemini else _stream_claude
                for chunk in stream_fn(key, model_id, system, prompt):
                    full += chunk
                    yield f"data: {json.dumps({'text': chunk})}\n\n"
                break  # 성공
            except Exception as e:
                if _is_quota_error(e):
                    pool.mark_error(key, _error_type(e))
                    continue  # 다음 키 시도
                # 일반 오류 (네트워크, 서버 오류 등) — 키 소진으로 처리하지 않음
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                return

        if full and on_complete:
            on_complete(full)
        yield f"data: {json.dumps({'done': True})}\n\n"

    return gen
