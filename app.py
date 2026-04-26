"""
YouTube Strategy Hub - 메인 대시보드
MCN 수준의 YouTube 채널 분석 및 AI 영상 기획 플랫폼
"""

import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# 페이지 기본 설정 (반드시 첫 번째 st 호출)
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="YouTube Strategy Hub",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────
# 사이드바: 전역 API 키 설정
# ──────────────────────────────────────────────
with st.sidebar:
    st.title("📊 YouTube Strategy Hub")
    st.caption("MCN급 채널 분석 플랫폼 v0.1")
    st.divider()

    st.subheader("🔑 API 설정")

    yt_key_env        = os.getenv("YOUTUBE_API_KEY", "")
    anthropic_key_env = os.getenv("ANTHROPIC_API_KEY", "")
    gemini_key_env    = os.getenv("GEMINI_API_KEY", "")

    yt_key_input = st.text_input(
        "YouTube API Key",
        value=yt_key_env,
        type="password",
        help="Google Cloud Console → YouTube Data API v3 → 사용자 인증 정보",
    )
    gemini_key_input = st.text_input(
        "Gemini API Key",
        value=gemini_key_env,
        type="password",
        help="aistudio.google.com → Get API key (AI 기획 기본 모델)",
    )
    anthropic_key_input = st.text_input(
        "Anthropic API Key",
        value=anthropic_key_env,
        type="password",
        help="console.anthropic.com → API Keys (Claude 모델 사용 시)",
    )

    st.session_state["youtube_api_key"]  = yt_key_input or yt_key_env
    st.session_state["gemini_api_key"]   = gemini_key_input or gemini_key_env
    st.session_state["anthropic_api_key"]= anthropic_key_input or anthropic_key_env

    st.divider()

    if st.session_state["youtube_api_key"]:
        st.success("✅ YouTube API 키 설정됨")
    else:
        st.error("❌ YouTube API 키 없음")

    if st.session_state["gemini_api_key"]:
        st.success("✅ Gemini API 키 설정됨")
    else:
        st.warning("⚠️ Gemini API 키 없음 (AI 기획 기본 모델)")

    if st.session_state["anthropic_api_key"]:
        st.success("✅ Anthropic API 키 설정됨")
    else:
        st.caption("Claude 모델 미사용 시 불필요")

    st.divider()
    st.caption("💡 `.env` 파일에 키를 저장하면 앱 재시작 시 자동 로드됩니다.")

# ──────────────────────────────────────────────
# 메인 탭 구성
# ──────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📈 채널 분석",
    "🔍 경쟁사 벤치마킹",
    "💡 AI 영상 기획",
    "📡 트렌드 기획",
    "🔎 키워드 분석",
    "✍️ 카피라이팅",
    "⚙️ 시스템 설정",
])

with tab1:
    from modules.channel_analyzer import render_channel_analyzer
    render_channel_analyzer()

with tab2:
    from modules.competitor_bench import render_competitor_bench
    render_competitor_bench()

with tab3:
    from modules.planner import render_planner
    render_planner()

with tab4:
    from modules.trend_planner import render_trend_planner
    render_trend_planner()

with tab5:
    from modules.keyword_analyzer import render_keyword_analyzer
    render_keyword_analyzer()

with tab6:
    from modules.copywriter import render_copywriter
    render_copywriter()

with tab7:
    st.subheader("⚙️ 시스템 설정")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**캐시 관리**")
        if st.button("🗑️ 만료 캐시 삭제"):
            api_key = st.session_state.get("youtube_api_key")
            if api_key:
                from core.api_handler import YouTubeAPIHandler
                handler = YouTubeAPIHandler(api_key=api_key)
                deleted = handler.clear_expired_cache()
                st.success(f"만료된 캐시 {deleted}개 삭제 완료")
            else:
                st.warning("YouTube API 키를 먼저 설정하세요.")

    with col2:
        st.markdown("**API 할당량 안내**")
        st.info(
            "YouTube Data API v3 일일 할당량: **10,000 units**\n\n"
            "| 메서드 | 비용 |\n"
            "|---|---|\n"
            "| `channels.list` | 1 unit |\n"
            "| `playlistItems.list` | 1 unit |\n"
            "| `videos.list` | 1 unit |\n"
            "| `commentThreads.list` | 1 unit |\n"
            "| `search.list` | **100 units** ⚠️ |"
        )

    st.divider()
    st.markdown("**캐시 정책**")
    st.code(
        "캐시 유효 시간 : 1시간 (3,600초)\n"
        "저장 위치       : cache/*.json\n"
        "키 생성 방식    : MD5(요청 파라미터)",
        language="text",
    )
