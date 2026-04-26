"""
AI 기반 영상 기획 모듈

지원 모델 (Gemini):
  - gemini-2.5-pro   (기본 · 사고 모델 · 최고 품질)
  - gemini-2.5-flash (사고 모델 · 빠름 · 저렴)
  - gemini-2.0-flash (초고속 · 가장 저렴)

지원 모델 (Claude):
  - claude-sonnet-4-6 (빠름 · 저렴)
"""

import streamlit as st
import anthropic
import google.generativeai as genai

from core import history as hist
from core.ai_router import AIRunner

TAB = "ai_planner"

# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────
MODEL_GEMINI_PRO   = "gemini-2.5-pro"
MODEL_GEMINI_FLASH = "gemini-2.5-flash"
MODEL_GEMINI_FAST  = "gemini-2.0-flash"
MODEL_SONNET       = "claude-sonnet-4-6"

# (label, model_id, is_gemini)
MODEL_OPTIONS = [
    (f"{MODEL_GEMINI_PRO}  (최고 품질 · 사고 모델)",        MODEL_GEMINI_PRO,   True),
    (f"{MODEL_GEMINI_FLASH}  (빠름 · 사고 모델 · 절약)",    MODEL_GEMINI_FLASH, True),
    (f"{MODEL_GEMINI_FAST}  (초고속 · 가장 저렴)",           MODEL_GEMINI_FAST,  True),
    (f"{MODEL_SONNET}  (Claude · 빠름)",                     MODEL_SONNET,       False),
]

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


# ──────────────────────────────────────────────
# 프롬프트 빌더
# ──────────────────────────────────────────────

def _build_user_prompt(
    topic: str,
    channel_info: str,
    target_length: str,
    outlier_data: str,
    gap_keywords: str,
) -> str:
    parts = [f"## 기획 요청\n**주제·키워드**: {topic}"]
    if channel_info:
        parts.append(f"**채널 정보**: {channel_info}")
    if target_length:
        parts.append(f"**목표 영상 길이**: {target_length}")
    if outlier_data:
        parts.append(f"\n## 참고: 경쟁사 아웃라이어 영상\n{outlier_data.strip()}")
    if gap_keywords:
        parts.append(f"\n## 참고: Content Gap 키워드\n{gap_keywords.strip()}")
    parts.append("\n위 데이터를 바탕으로 MCN 기획 프레임워크에 맞는 완성도 높은 영상 기획안을 작성해 주세요.")
    return "\n".join(parts)


# ──────────────────────────────────────────────
# API 호출 함수
# ──────────────────────────────────────────────

def _run_gemini(api_key: str, model_id: str, user_prompt: str, output_box) -> tuple[str, dict]:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=model_id,
        system_instruction=SYSTEM_PROMPT,
    )
    full_output = ""
    response = model.generate_content(user_prompt, stream=True)
    for chunk in response:
        try:
            text = chunk.text
        except (ValueError, AttributeError):
            continue
        if text:
            full_output += text
            output_box.markdown(full_output + "▌")

    output_box.markdown(full_output)
    usage = {}
    try:
        meta = response.usage_metadata
        usage = {
            "input":  meta.prompt_token_count,
            "output": meta.candidates_token_count,
        }
    except Exception:
        pass
    return full_output, usage


def _run_claude(api_key: str, model_id: str, user_prompt: str, output_box) -> tuple[str, dict]:
    client = anthropic.Anthropic(api_key=api_key)
    full_output = ""
    with client.messages.stream(
        model=model_id,
        max_tokens=4096,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for chunk in stream.text_stream:
            full_output += chunk
            output_box.markdown(full_output + "▌")
        u = stream.get_final_message().usage
        usage = {
            "input":       u.input_tokens,
            "output":      u.output_tokens,
            "cache_read":  getattr(u, "cache_read_input_tokens", 0),
            "cache_write": getattr(u, "cache_creation_input_tokens", 0),
        }

    output_box.markdown(full_output)
    return full_output, usage


# ──────────────────────────────────────────────
# Streamlit UI
# ──────────────────────────────────────────────

@st.dialog("AI 기획 기록", width="large")
def _history_dialog():
    records = hist.list_results(TAB)
    if not records:
        st.info("저장된 기록이 없습니다.")
        return
    labels = [f"{r['timestamp']}  —  {r['label']}" for r in records]
    idx = st.selectbox("기록 선택", range(len(labels)), format_func=lambda i: labels[i])
    entry = hist.load_result(TAB, records[idx]["filename"])
    if not entry:
        return
    d = entry["data"]
    st.caption(f"모델: `{d.get('model','-')}` | 길이: {d.get('target_length','-')}")
    if d.get("channel_info"):
        st.caption(f"채널: {d['channel_info']}")
    st.divider()
    st.markdown(d.get("output", ""))


def render_planner():
    st.subheader("💡 AI 영상 기획기")

    if st.button("📂 최근 기록", key="planner_hist"):
        _history_dialog()

    # 할당량 초과 후 모델 선택 시 AIRunner가 session_state에 승인 데이터를 저장하고
    # st.rerun()을 호출한다. rerun 후에는 버튼 상태가 초기화되므로 이 키를 확인해
    # 버튼 가드를 우회하고 실행을 재개한다.
    _appr_key   = f"_airunner_{TAB}_approval"
    has_pending = _appr_key in st.session_state

    # ── 모델 선택 ───────────────────────────────
    st.markdown("### 🤖 AI 모델 선택")
    labels     = [o[0] for o in MODEL_OPTIONS]
    model_idx  = st.radio(
        "모델",
        range(len(labels)),
        format_func=lambda i: labels[i],
        index=0,
        label_visibility="collapsed",
    )
    _, selected_model_id, is_gemini = MODEL_OPTIONS[model_idx]

    # ── API 키 확인 (승인 대기 중엔 생략 — 이미 검증됨) ──
    if not has_pending:
        if is_gemini:
            api_key = st.session_state.get("gemini_api_key", "")
            if not api_key:
                st.error("❌ 사이드바에서 Gemini API 키를 먼저 입력하세요.")
                st.info("API 키 발급: aistudio.google.com → Get API key")
                return
        else:
            api_key = st.session_state.get("anthropic_api_key", "")
            if not api_key:
                st.error("❌ 사이드바에서 Anthropic API 키를 먼저 입력하세요.")
                st.info("API 키 발급: console.anthropic.com → API Keys")
                return

    # ── 기획 정보 입력 ──────────────────────────
    st.markdown("### 📋 기획 정보 입력")
    col_left, col_right = st.columns(2)

    with col_left:
        topic = st.text_input(
            "🎯 영상 주제 / 핵심 키워드 *",
            placeholder="예: 파이썬으로 월급 자동 계산기 만들기",
        )
        channel_info = st.text_area(
            "채널 정보 (선택)",
            placeholder="예: 30대 직장인 대상 재테크·자기계발 채널, 구독자 5만명",
            height=80,
        )

    with col_right:
        target_length = st.selectbox(
            "목표 영상 길이",
            ["미정", "쇼츠 (60초 이내)", "단편 (5~10분)", "중편 (10~20분)", "장편 (20분 이상)"],
        )

    with st.expander("📊 경쟁사 분석 결과 붙여넣기 (선택 — 더 정확한 기획 가능)", expanded=False):
        outlier_data = st.text_area(
            "경쟁사 아웃라이어 영상 제목 & 지표",
            placeholder=(
                "예:\n"
                "- '직장인이 3개월 만에 1억 모은 방법' | 조회수 230만 | 평균대비 8.2x\n"
                "- '월급 200만원으로 내 집 마련한 썰' | 조회수 180만 | 평균대비 6.1x"
            ),
            height=100,
        )
        gap_keywords = st.text_area(
            "Content Gap 키워드",
            placeholder="예: 재테크, ETF 투자, 절세, 청약 통장, 연금저축",
            height=60,
        )

    run = st.button("🚀 AI 기획 시작", type="primary", use_container_width=True)

    if not topic and not has_pending:
        st.caption("영상 주제를 입력하고 [AI 기획 시작]을 클릭하세요.")
        return
    if not run and not has_pending:
        return

    # ── 실행 ────────────────────────────────────
    length_str  = target_length if target_length != "미정" else ""
    user_prompt = _build_user_prompt(
        topic=topic,
        channel_info=channel_info,
        target_length=length_str,
        outlier_data=outlier_data,
        gap_keywords=gap_keywords,
    )

    st.divider()
    st.markdown("### 📄 기획안")
    output_box = st.empty()

    runner      = AIRunner(tab_key=TAB, system=SYSTEM_PROMPT, max_tokens=4096)
    full_output = runner.execute(user_prompt, output_box, preferred=selected_model_id)

    if full_output is None:
        return  # 승인 대기 중

    if full_output:
        # st.empty() 안의 긴 마크다운은 마우스 휠 스크롤이 막히므로
        # 스트리밍 완료 후 일반 페이지 흐름의 st.markdown()으로 교체한다.
        output_box.empty()
        st.markdown(full_output)

        safe_topic = topic[:20].replace(" ", "_").replace("/", "-")
        st.download_button(
            label="📥 기획안 다운로드 (.txt)",
            data=full_output,
            file_name=f"기획안_{safe_topic}.txt",
            mime="text/plain",
            use_container_width=True,
        )
        hist.save_result(TAB, topic[:40], {
            "topic":         topic,
            "model":         selected_model_id,
            "channel_info":  channel_info,
            "target_length": length_str or "미정",
            "output":        full_output,
        })
