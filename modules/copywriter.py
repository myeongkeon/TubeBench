"""
YouTube 카피라이팅 모듈

제목·썸네일 텍스트·해시태그를 채널 스타일별로 생성.

스타일 분류:
  채널 스타일 : 1분 미만 / 짤컷
  주제별 스타일: 테크·일상(살림)·여행·취미·게임·예능·유머·정보
  범용        : MCN 기본 (Hook 최적화)

전문가 추가 기능:
  - 감정 트리거 선택 (호기심·공포·공감·유머·놀라움)
  - 길이 옵션 (쇼츠용 초단형 / 일반 / 검색 최적화 롱테일)
  - 제목 5종 + 썸네일 텍스트 + 해시태그 10개 동시 생성
  - A/B 테스트 관점: 각 제목에 예상 CTR 포인트 코멘트
"""

import streamlit as st
import anthropic
import google.generativeai as genai

from core import history as hist

TAB = "copywriter"

# ──────────────────────────────────────────────
# 스타일 정의
# ──────────────────────────────────────────────

STYLES: dict[str, dict] = {
    # ── 채널 스타일 ────────────────────────────
    "📺 1분 미만 스타일": {
        "group": "채널 스타일",
        "desc": (
            "초단형 쇼츠 채널 '1분 미만' 스타일. "
            "제목은 극도로 짧고(10자 이내), 충격·반전·궁금증 유발이 핵심. "
            "숫자·감탄사·물음표 적극 활용. 썸네일 텍스트도 2~4단어."
        ),
    },
    "✂️ 짤컷 스타일": {
        "group": "채널 스타일",
        "desc": (
            "밈·짤 기반 숏폼 채널 '짤컷' 스타일. "
            "인터넷 밈·유행어·공감 상황을 제목에 녹여냄. "
            "낮은 진입장벽, '이거 나 얘기인데?' 공감 유발. "
            "말투는 친근하고 캐주얼, 이모지 적극 사용."
        ),
    },
    # ── 주제별 스타일 ──────────────────────────
    "💻 테크": {
        "group": "주제별 스타일",
        "desc": (
            "IT·기술·리뷰 채널 스타일. "
            "스펙 숫자 비교, '최초·역대급·압도적' 수식어, "
            "구체적 제품명 포함, 'vs' 비교 구도 선호."
        ),
    },
    "🏠 일상·살림": {
        "group": "주제별 스타일",
        "desc": (
            "살림·라이프스타일 채널 스타일. "
            "따뜻하고 감성적인 어조, '나만 몰랐던·우리집·매일' 등 일상 밀착 키워드, "
            "공감형 상황 묘사, 절약·효율 강조."
        ),
    },
    "✈️ 여행": {
        "group": "주제별 스타일",
        "desc": (
            "여행 브이로그·정보 채널 스타일. "
            "장소명 명시 필수, 설렘·경이로움 감정 유발, "
            "'알고 가면 좋은·현지인만 아는·숨겨진' 키워드, "
            "비용·일정 숫자 포함."
        ),
    },
    "🎯 취미": {
        "group": "주제별 스타일",
        "desc": (
            "취미·DIY·커뮤니티 채널 스타일. "
            "동료 감각('같이 해봐요·따라해보세요'), 난이도 명시, "
            "'초보도 가능·쉽게·10분 만에' 진입장벽 낮추기."
        ),
    },
    "🎮 게임": {
        "group": "주제별 스타일",
        "desc": (
            "게임 채널 스타일. "
            "티어·랭크·기록 숫자 필수, '개사기·OP·무결점' 강한 표현, "
            "클리어·공략·비법 키워드, 시즌·패치 시의성 강조."
        ),
    },
    "😂 예능·유머": {
        "group": "주제별 스타일",
        "desc": (
            "예능·버라이어티·유머 채널 스타일. "
            "반전 구도, 과장된 표현, 의성어·이모지, "
            "'상상도 못한·결국·실수로' 서사 키워드."
        ),
    },
    "📰 정보·교육": {
        "group": "주제별 스타일",
        "desc": (
            "정보·교육·다큐 채널 스타일. "
            "숫자·통계·출처 기반 신뢰감, '모르면 손해·필수·진짜' 긴급성, "
            "리스트형(N가지·N단계) 구조화."
        ),
    },
    # ── 범용 ──────────────────────────────────
    "⭐ MCN 기본 (Hook 최적화)": {
        "group": "범용",
        "desc": (
            "MCN 표준 Hook 최적화 스타일. "
            "CTR·시청 유지율 모두 고려한 균형형. "
            "숫자형·질문형·자극형·How-To형·반전형 패턴을 골고루 활용."
        ),
    },
}

EMOTION_TRIGGERS = {
    "🤔 호기심":  "시청자가 '어떻게?'라고 궁금해하게 만드는 미완성 정보 제공",
    "😱 충격·공포": "예상을 깨는 충격적 사실, '이걸 모르면 큰일' 위기감",
    "😊 공감":    "시청자의 일상 상황·감정과 즉각 연결되는 친근감",
    "😄 유머":    "가볍게 웃을 수 있는 반전·말장난·밈 감성",
    "😲 놀라움":  "기대 이상의 결과, 상식 뒤집기, '세상에 이런 일이' 감탄",
}

LENGTH_OPTIONS = {
    "일반형 (30~40자)":       "제목 30~40자, 검색 노출과 CTR 균형",
    "쇼츠 초단형 (15자 이내)": "15자 이내 초단형, 쇼츠·릴스 최적화",
    "검색 롱테일 (45자 이상)": "45자 이상, 검색 키워드 풍부하게 포함",
}

SYSTEM_PROMPT = """\
당신은 국내 최고 수준의 YouTube 카피라이터 겸 MCN 콘텐츠 전략가입니다.
채널 스타일·감정 트리거·제목 길이를 정밀하게 조합해 클릭률(CTR)을 극대화하는 제목을 생성합니다.
반드시 한국어로 작성하고, 지정된 출력 형식을 정확히 따르세요.\
"""


# ──────────────────────────────────────────────
# 프롬프트 빌더
# ──────────────────────────────────────────────

def _build_prompt(
    keyword: str,
    content: str,
    style_key: str,
    emotion_key: str,
    length_key: str,
) -> str:
    style   = STYLES[style_key]
    emotion = EMOTION_TRIGGERS[emotion_key]
    length  = LENGTH_OPTIONS[length_key]

    return f"""\
## 카피라이팅 요청

**키워드**: {keyword}
**영상 내용**: {content}
**스타일**: {style_key} — {style['desc']}
**감정 트리거**: {emotion_key} — {emotion}
**제목 길이**: {length_key} — {length}

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


# ──────────────────────────────────────────────
# AI 호출
# ──────────────────────────────────────────────

_GEMINI_FALLBACK = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"]


def _run_ai(prompt: str, output_box) -> str:
    import google.api_core.exceptions

    gemini_key    = st.session_state.get("gemini_api_key", "")
    anthropic_key = st.session_state.get("anthropic_api_key", "")
    full_output   = ""

    if gemini_key:
        genai.configure(api_key=gemini_key)
        for model_name in _GEMINI_FALLBACK:
            try:
                model    = genai.GenerativeModel(model_name=model_name, system_instruction=SYSTEM_PROMPT)
                response = model.generate_content(prompt, stream=True)
                output_box.caption(f"모델: `{model_name}`")
                for chunk in response:
                    try:
                        text = chunk.text
                    except (ValueError, AttributeError):
                        continue
                    if text:
                        full_output += text
                        output_box.markdown(full_output + "▌")
                break
            except google.api_core.exceptions.ResourceExhausted:
                st.warning(f"`{model_name}` 할당량 초과, 다음 모델 시도 중...")
                continue
            except Exception as e:
                st.error(f"❌ Gemini 오류: {e}")
                return ""
        else:
            st.error(
                "❌ 모든 Gemini 모델의 무료 할당량을 초과했습니다.\n\n"
                "잠시 후 다시 시도하거나 Anthropic API 키를 사이드바에 입력해 Claude로 전환하세요."
            )
            return ""
    elif anthropic_key:
        client = anthropic.Anthropic(api_key=anthropic_key)
        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for chunk in stream.text_stream:
                full_output += chunk
                output_box.markdown(full_output + "▌")
    else:
        st.error("❌ 사이드바에서 Gemini 또는 Anthropic API 키를 입력하세요.")
        return ""

    output_box.markdown(full_output)
    return full_output


# ──────────────────────────────────────────────
# Streamlit UI
# ──────────────────────────────────────────────

@st.dialog("카피라이팅 기록", width="large")
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
    st.caption(
        f"스타일: {d.get('style','-')} | 트리거: {d.get('emotion','-')} | 길이: {d.get('length','-')}"
    )
    st.caption(f"내용: {d.get('content','')[:80]}")
    st.divider()
    st.markdown(d.get("output", ""))


def render_copywriter():
    st.subheader("✍️ 카피라이팅")
    st.caption("키워드·내용·스타일을 선택하면 제목·썸네일 텍스트·해시태그를 자동 생성합니다.")

    if st.button("📂 최근 기록", key="copy_hist"):
        _history_dialog()

    # ── 입력 ────────────────────────────────────
    col_l, col_r = st.columns(2)

    with col_l:
        keyword = st.text_input(
            "🔑 핵심 키워드 *",
            placeholder="예: 갤럭시 S25, 국물 요리, 방콕 여행",
        )
        content = st.text_area(
            "📝 영상 내용 요약 *",
            placeholder="예: 갤럭시 S25를 1달 써본 솔직 후기. 배터리·카메라·발열 집중 테스트",
            height=100,
        )

    with col_r:
        # 스타일 선택 — 그룹별로 구분
        groups: dict[str, list] = {}
        for key, val in STYLES.items():
            groups.setdefault(val["group"], []).append(key)

        style_key = st.selectbox(
            "🎨 스타일 선택 *",
            options=list(STYLES.keys()),
            format_func=lambda k: k,
            help="채널 스타일 또는 주제별 스타일 선택",
        )

        emotion_key = st.selectbox(
            "💥 감정 트리거",
            options=list(EMOTION_TRIGGERS.keys()),
            index=0,
        )

        length_key = st.selectbox(
            "📏 제목 길이",
            options=list(LENGTH_OPTIONS.keys()),
            index=0,
        )

    # 스타일 설명 미리보기
    st.caption(f"📌 선택 스타일: {STYLES[style_key]['desc']}")

    run = st.button("✍️ 카피 생성", type="primary", use_container_width=True)

    if not keyword or not content:
        st.caption("키워드와 영상 내용을 입력하고 [카피 생성]을 클릭하세요.")
        return
    if not run:
        return

    # ── 실행 ────────────────────────────────────
    st.divider()
    st.markdown(f"### 📋 카피라이팅 결과 — {style_key}")
    output_box  = st.empty()
    prompt      = _build_prompt(keyword, content, style_key, emotion_key, length_key)
    full_output = _run_ai(prompt, output_box)

    if full_output:
        safe_kw = keyword[:15].replace(" ", "_")
        st.download_button(
            label="📥 결과 다운로드 (.txt)",
            data=full_output,
            file_name=f"카피_{safe_kw}.txt",
            mime="text/plain",
            use_container_width=True,
        )
        hist.save_result(TAB, f"{keyword[:20]} / {style_key}", {
            "keyword": keyword,
            "content": content,
            "style":   style_key,
            "emotion": emotion_key,
            "length":  length_key,
            "output":  full_output,
        })
