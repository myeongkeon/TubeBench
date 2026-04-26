"""
AI 모델 라우터

할당량 초과 시 자동 폴백하지 않고, 실패한 모델을 명시하고 사용자 승인을 받은 뒤 재시도.

사용법:
    runner = AIRunner(tab_key="planner", system=SYSTEM_PROMPT, max_tokens=4096)
    output = runner.execute(user_prompt, output_box, preferred="gemini-2.5-pro")
    if output is None:
        return  # 승인 대기 중 — UI 표시됨, 함수 종료

    # output 이 "" 이면 취소 또는 오류
"""

import streamlit as st
import google.api_core.exceptions
import google.generativeai as genai
import anthropic

# (model_id, 표시명, is_gemini)
GEMINI_MODELS = [
    ("gemini-2.0-flash",  "Gemini 2.0 Flash  (초고속·무료 한도 우수)", True),
    ("gemini-2.5-flash",  "Gemini 2.5 Flash  (빠름·사고 모델)",        True),
    ("gemini-2.5-pro",    "Gemini 2.5 Pro    (최고 품질·사고 모델)",   True),
]
CLAUDE_MODEL = ("claude-sonnet-4-6", "Claude Sonnet 4.6  (Anthropic)", False)


def _available_candidates(exclude: str | None = None) -> list[tuple]:
    """현재 설정된 API 키 기준으로 사용 가능한 모델 목록 반환 (exclude 제외)"""
    gemini_key    = st.session_state.get("gemini_api_key", "")
    anthropic_key = st.session_state.get("anthropic_api_key", "")
    out = []
    if gemini_key:
        out.extend([(mid, lbl, ig) for mid, lbl, ig in GEMINI_MODELS if mid != exclude])
    if anthropic_key:
        cid, clbl, cig = CLAUDE_MODEL
        if cid != exclude:
            out.append((cid, clbl, cig))
    return out


def _stream_gemini(api_key: str, model_id: str, system: str, prompt: str, output_box) -> str:
    genai.configure(api_key=api_key)
    model    = genai.GenerativeModel(model_name=model_id, system_instruction=system)
    response = model.generate_content(prompt, stream=True)
    full = ""
    for chunk in response:
        try:
            text = chunk.text
        except (ValueError, AttributeError):
            continue
        if text:
            full += text
            output_box.markdown(full + "▌")
    output_box.markdown(full)
    return full


def _stream_claude(api_key: str, model_id: str, system: str, prompt: str,
                   max_tokens: int, output_box) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    full   = ""
    with client.messages.stream(
        model=model_id,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for chunk in stream.text_stream:
            full += chunk
            output_box.markdown(full + "▌")
    output_box.markdown(full)
    return full


class AIRunner:
    """
    탭별 AI 호출 관리자. 할당량 초과 시 사용자 승인 UI를 표시하고 None 반환.

    Args:
        tab_key   : 탭 식별 키 (session_state 충돌 방지용)
        system    : 시스템 프롬프트
        max_tokens: Claude 최대 토큰 (Gemini 무시)
    """

    def __init__(self, tab_key: str, system: str, max_tokens: int = 3000):
        self.tab_key    = tab_key
        self.system     = system
        self.max_tokens = max_tokens
        self._appr_key  = f"_airunner_{tab_key}_approval"

    # ──────────────────────────────────────────
    # 공개 API
    # ──────────────────────────────────────────

    def execute(self, user_prompt: str, output_box, preferred: str = "gemini-2.0-flash") -> str | None:
        """
        Returns:
            str  : 생성 결과 (성공, 혹은 빈 문자열이면 오류)
            None : 승인 대기 중 (승인 UI 표시됨 — 호출자는 return 해야 함)
        """
        # ── 승인된 모델로 자동 재시도 ──────────
        if appr := st.session_state.pop(self._appr_key, None):
            return self._call(appr["model_id"], appr["is_gemini"], appr["prompt"], output_box)

        # ── 최초 실행: preferred 모델 먼저 ─────
        all_candidates = _available_candidates()
        if not all_candidates:
            st.error("❌ Gemini 또는 Anthropic API 키를 사이드바에 입력하세요.")
            return ""

        # preferred 모델이 목록에 있으면 맨 앞으로
        ordered = sorted(all_candidates, key=lambda x: (x[0] != preferred))
        model_id, label, is_gemini = ordered[0]

        try:
            output_box.caption(f"모델: `{model_id}`")
            return self._call(model_id, is_gemini, user_prompt, output_box)

        except google.api_core.exceptions.ResourceExhausted:
            alts = _available_candidates(exclude=model_id)
            self._show_approval_ui(model_id, label, alts, user_prompt)
            return None

        except anthropic.RateLimitError:
            alts = _available_candidates(exclude=model_id)
            self._show_approval_ui(model_id, label, alts, user_prompt)
            return None

        except Exception as e:
            st.error(f"❌ AI 오류: {e}")
            return ""

    # ──────────────────────────────────────────
    # 내부
    # ──────────────────────────────────────────

    def _call(self, model_id: str, is_gemini: bool, prompt: str, output_box) -> str:
        gemini_key    = st.session_state.get("gemini_api_key", "")
        anthropic_key = st.session_state.get("anthropic_api_key", "")
        output_box.caption(f"모델: `{model_id}`")
        if is_gemini:
            return _stream_gemini(gemini_key, model_id, self.system, prompt, output_box)
        else:
            return _stream_claude(anthropic_key, model_id, self.system, prompt,
                                  self.max_tokens, output_box)

    def _show_approval_ui(self, failed_id: str, failed_label: str,
                          alternatives: list[tuple], prompt: str) -> None:
        st.error(
            f"### ⚠️ 할당량 초과\n\n"
            f"**`{failed_label}`** 의 무료 티어 한도에 도달했습니다.\n\n"
            f"다른 모델로 전환하시겠습니까?"
        )
        if not alternatives:
            st.warning(
                "사용 가능한 대체 모델이 없습니다.\n"
                "· 잠시 후 다시 시도하거나\n"
                "· 반대편 API 키(Gemini ↔ Anthropic)를 사이드바에 입력하세요."
            )
            return

        st.markdown("**전환할 모델을 선택하세요:**")
        cols = st.columns(min(len(alternatives), 3))
        for i, (mid, lbl, ig) in enumerate(alternatives):
            with cols[i % 3]:
                if st.button(f"✅ {lbl}", key=f"{self._appr_key}_btn_{mid}", use_container_width=True):
                    st.session_state[self._appr_key] = {
                        "model_id":  mid,
                        "is_gemini": ig,
                        "prompt":    prompt,
                    }
                    st.rerun()
