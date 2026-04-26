"""
운영 채널 성과 분석 모듈 - Step 2

MCN 등급 기준:
  S등급: 구독자 대비 평균 조회율 10% 이상 AND 참여도 2% 이상
  A등급: 구독자 대비 평균 조회율 5% 이상 OR  참여도 1% 이상
  B등급: 위 기준 미달 (성장 초기 / 정체 구간)

참여도(Engagement Rate) = (좋아요 + 댓글) / 조회수 × 100  (영상별 평균)
구독자 대비 조회율(View Rate) = 평균 조회수 / 구독자수 × 100
"""

import re
import streamlit as st
import pandas as pd
import plotly.express as px

from core.api_handler import YouTubeAPIHandler
from core import history as hist

TAB = "channel_analyzer"


def _mermaid_safe(text: str, max_len: int = 20) -> str:
    """Mermaid 포인트 레이블에 사용 불가한 문자 제거 후 길이 제한."""
    return re.sub(r'[:\[\]()"\'=]', '', text).strip()[:max_len] or "채널"

# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────
ANALYZE_VIDEO_COUNT = 30  # 분석할 최근 영상 수

MCN_THRESHOLDS = {
    "S": {"view_rate": 10.0, "engagement": 2.0},
    "A": {"view_rate": 5.0,  "engagement": 1.0},
}

GRADE_STYLE = {
    "S": {"bg": "#FFD700", "label": "S등급 — 최상위 채널"},
    "A": {"bg": "#C0C0C0", "label": "A등급 — 성장형 채널"},
    "B": {"bg": "#CD7F32", "label": "B등급 — 초기 / 정체 채널"},
}

DIAGNOSIS = {
    "S": {
        "summary": "구독자 도달률과 팬덤 참여도가 모두 최상위권입니다. MCN 파트너십 협상 및 광고 단가 인상에 유리한 지표를 보유하고 있습니다.",
        "strengths": [
            "높은 구독자 도달률 → 알고리즘 노출 선순환 구조",
            "강력한 팬덤 참여도 → 댓글·좋아요 기반 커뮤니티 형성",
        ],
        "improvements": [
            "콘텐츠 다각화(쇼츠 연계)로 신규 시청자 유입 확대",
            "멤버십·굿즈 등 수익 다변화 시점 검토",
        ],
    },
    "A": {
        "summary": "성장 궤도에 있는 채널입니다. 핵심 지표를 한 단계 끌어올리면 S등급 진입이 가능합니다.",
        "strengths": [
            "안정적인 콘텐츠 생산력과 기본 팬층 확보",
        ],
        "improvements": [
            "썸네일·제목 A/B 테스트로 클릭률(CTR) 개선 → 조회율 향상",
            "영상 말미 CTA(구독·좋아요 요청) 강화로 참여도 증가",
            "업로드 일관성 유지(주 1~2회)로 알고리즘 노출 안정화",
        ],
    },
    "B": {
        "summary": "성장 초기 단계이거나 정체 구간에 있습니다. 경쟁사 아웃라이어 분석을 통해 돌파구 주제를 발굴하세요.",
        "strengths": [
            "아직 실험 여지가 넓어 콘텐츠 방향 전환이 유연함",
        ],
        "improvements": [
            "Hook 강화: 첫 30초 시청 지속률 개선이 이탈률의 핵심 원인",
            "경쟁사 아웃라이어 영상 분석 후 주제 전략 전면 재수립",
            "업로드 빈도 조정 — 양보다 질 집중(주 1회 고품질)",
        ],
    },
}


# ──────────────────────────────────────────────
# 데이터 처리 함수
# ──────────────────────────────────────────────

def _build_dataframe(videos: list[dict], stats: list[dict]) -> pd.DataFrame:
    """영상 목록 + 통계를 병합한 분석용 DataFrame 반환"""
    stats_map = {s["video_id"]: s for s in stats}
    rows = []
    for v in videos:
        s = stats_map.get(v["video_id"], {})
        rows.append({
            "video_id":     v["video_id"],
            "title":        v["title"],
            "published_at": pd.to_datetime(v["published_at"]),
            "view_count":   s.get("view_count", 0),
            "like_count":   s.get("like_count", 0),
            "comment_count":s.get("comment_count", 0),
            "tags":         s.get("tags", []),
        })
    df = pd.DataFrame(rows).sort_values("published_at").reset_index(drop=True)

    # 참여도 계산 (조회수 0 영상은 제외)
    valid = df["view_count"] > 0
    df.loc[valid, "engagement_rate"] = (
        (df.loc[valid, "like_count"] + df.loc[valid, "comment_count"])
        / df.loc[valid, "view_count"] * 100
    )
    df["engagement_rate"] = df["engagement_rate"].fillna(0)
    return df


def _calc_summary(df: pd.DataFrame, subscriber_count: int) -> dict:
    """핵심 지표 요약 계산"""
    valid = df[df["view_count"] > 0]
    if valid.empty:
        return {}

    avg_views      = valid["view_count"].mean()
    avg_engagement = valid["engagement_rate"].mean()
    # 구독자가 비공개(0)인 경우 조회율 계산 불가
    view_rate      = (avg_views / subscriber_count * 100) if subscriber_count > 0 else 0

    # 업로드 빈도: 분석 기간 ÷ 영상 수 (일 단위)
    days_span = (df["published_at"].max() - df["published_at"].min()).days
    upload_freq = (days_span / len(df)) if len(df) > 1 and days_span > 0 else 0

    return {
        "avg_views":      avg_views,
        "view_rate":      view_rate,
        "avg_engagement": avg_engagement,
        "upload_freq":    upload_freq,
        "valid_df":       valid,
    }


def _get_grade(view_rate: float, engagement: float) -> str:
    s = MCN_THRESHOLDS["S"]
    a = MCN_THRESHOLDS["A"]
    if view_rate >= s["view_rate"] and engagement >= s["engagement"]:
        return "S"
    if view_rate >= a["view_rate"] or engagement >= a["engagement"]:
        return "A"
    return "B"


# ──────────────────────────────────────────────
# Streamlit UI
# ──────────────────────────────────────────────

@st.dialog("채널 분석 기록", width="large")
def _history_dialog():
    records = hist.list_results(TAB)
    if not records:
        st.info("저장된 기록이 없습니다.")
        return
    labels = [f"{r['timestamp']}  —  {r['label']}" for r in records]
    idx = st.selectbox("기록 선택", range(len(labels)), format_func=lambda i: labels[i])
    entry = hist.load_result(TAB, records[idx]["filename"])
    if not entry:
        st.error("기록을 불러올 수 없습니다.")
        return
    d = entry["data"]

    # ── 채널 헤더 ──
    c1, c2 = st.columns([1, 6])
    with c1:
        if d.get("thumbnail"):
            st.image(d["thumbnail"], width=56)
    with c2:
        grade = d.get("grade", "?")
        color = {"S": "#FFD700", "A": "#C0C0C0", "B": "#CD7F32"}.get(grade, "#eee")
        st.markdown(f"### {d.get('channel_title', '-')}")
        st.markdown(
            f"<span style='background:{color};padding:3px 10px;border-radius:5px;"
            f"font-weight:700;color:#111;'>{grade}등급</span>",
            unsafe_allow_html=True,
        )

    # ── 핵심 지표 ──
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("구독자",      f"{d.get('subscriber_count',0):,}명")
    m2.metric("평균 조회수",  f"{d.get('avg_views',0):,.0f}회")
    m3.metric("구독자 대비 조회율", f"{d.get('view_rate',0):.1f}%")
    m4.metric("평균 참여도",  f"{d.get('avg_engagement',0):.2f}%")

    # ── MCN 포지션 (Mermaid 쿼드런트) ──
    st.divider()
    st.caption("MCN 등급 포지션 — S기준(조회율 10%·참여도 2%) 대비 위치")
    vr    = min(d.get("view_rate", 0) / 20, 0.95)
    eg    = min(d.get("avg_engagement", 0) / 4, 0.95)
    label = _mermaid_safe(d.get("channel_title", "채널"), max_len=12)
    mmd = f"""quadrantChart
    title MCN 포지션 오른쪽 위가 S등급 구간
    x-axis 낮은 조회율 --> 높은 조회율
    y-axis 낮은 참여도 --> 높은 참여도
    quadrant-1 S등급 구간
    quadrant-2 A등급 참여우수
    quadrant-3 B등급 구간
    quadrant-4 A등급 조회우수
    {label}: [{vr:.2f}, {eg:.2f}]"""
    hist.render_mermaid(mmd, height=340)

    # ── 상위 영상 ──
    top = d.get("top_videos", [])
    if top:
        st.divider()
        st.caption("참여도 상위 영상")
        st.dataframe(
            pd.DataFrame(top)[["title", "view_count", "engagement_rate"]].rename(
                columns={"title": "제목", "view_count": "조회수", "engagement_rate": "참여도(%)"}
            ),
            use_container_width=True, hide_index=True,
        )


def render_channel_analyzer():
    st.subheader("📈 운영 채널 성과 분석")

    api_key = st.session_state.get("youtube_api_key", "")
    if not api_key:
        st.error("❌ 사이드바에서 YouTube API 키를 먼저 입력하세요.")
        return

    if st.button("📂 최근 기록", key="ch_hist"):
        _history_dialog()

    # ── 입력 ───────────────────────────────────
    col_in, col_btn = st.columns([5, 1])
    with col_in:
        channel_raw = st.text_input(
            "채널 ID 또는 핸들",
            placeholder="UCxxxxxx  또는  @handle  또는  youtube.com/@handle",
            help="채널 ID(UC...), @핸들, YouTube URL 모두 입력 가능",
            label_visibility="collapsed",
        )
    with col_btn:
        run = st.button("🔍 분석", use_container_width=True, type="primary")

    if not channel_raw:
        st.caption("채널 ID 또는 핸들을 입력하고 [분석] 버튼을 클릭하세요.")
        return
    if not run:
        return

    # ── API 호출 ───────────────────────────────
    try:
        handler = YouTubeAPIHandler(api_key=api_key)

        with st.spinner("채널 정보 조회 중..."):
            channel_id = handler.resolve_channel_id(channel_raw)
            channel = handler.get_channel_info(channel_id)

        if not channel:
            st.error(f"채널을 찾을 수 없습니다: `{channel_id}`")
            return

        with st.spinner(f"최근 {ANALYZE_VIDEO_COUNT}개 영상 수집 중..."):
            videos = handler.get_channel_videos(
                channel["uploads_playlist_id"], max_results=ANALYZE_VIDEO_COUNT
            )
            stats = handler.get_video_stats([v["video_id"] for v in videos])

    except RuntimeError as e:
        st.error(f"API 오류: {e}")
        return

    # ── 데이터 처리 ────────────────────────────
    df = _build_dataframe(videos, stats)
    summary = _calc_summary(df, channel["subscriber_count"])

    if not summary:
        st.warning("영상 데이터가 없거나 모든 영상의 조회수가 0입니다.")
        return

    grade   = _get_grade(summary["view_rate"], summary["avg_engagement"])
    diag    = DIAGNOSIS[grade]
    style   = GRADE_STYLE[grade]

    # ══════════════════════════════════════════
    # 섹션 1: 채널 헤더
    # ══════════════════════════════════════════
    st.divider()
    c_thumb, c_info = st.columns([1, 6])
    with c_thumb:
        if channel["thumbnail"]:
            st.image(channel["thumbnail"], width=72)
    with c_info:
        st.markdown(f"### {channel['title']}")
        st.caption(
            f"채널 ID: `{channel_id}`  "
            f"| 개설일: {channel['published_at'][:10]}  "
            f"| 총 영상: {channel['video_count']:,}개"
        )

    # ══════════════════════════════════════════
    # 섹션 2: 핵심 지표 카드
    # ══════════════════════════════════════════
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("👥 구독자",          f"{channel['subscriber_count']:,}명")
    m2.metric("▶️ 평균 조회수",     f"{summary['avg_views']:,.0f}회")
    m3.metric("📊 구독자 대비 조회율", f"{summary['view_rate']:.1f}%",
              help="평균 조회수 ÷ 구독자수 × 100")
    m4.metric("💬 평균 참여도",     f"{summary['avg_engagement']:.2f}%",
              help="(좋아요+댓글) ÷ 조회수 × 100, 영상별 평균")

    # ══════════════════════════════════════════
    # 섹션 3: MCN 등급 배지
    # ══════════════════════════════════════════
    st.divider()
    st.markdown(
        f"<div style='background:{style['bg']};padding:10px 20px;border-radius:8px;"
        f"display:inline-block;color:#111;font-size:1.15rem;font-weight:700;'>"
        f"🏆 MCN {style['label']}</div>",
        unsafe_allow_html=True,
    )
    st.caption(diag["summary"])

    # MCN 기준 달성 현황
    s_thr = MCN_THRESHOLDS["S"]
    a_thr = MCN_THRESHOLDS["A"]
    prog_col1, prog_col2 = st.columns(2)
    with prog_col1:
        vr_pct = min(summary["view_rate"] / s_thr["view_rate"], 1.0)
        st.markdown(f"**조회율** {summary['view_rate']:.1f}% / S기준 {s_thr['view_rate']}%")
        st.progress(vr_pct)
    with prog_col2:
        eg_pct = min(summary["avg_engagement"] / s_thr["engagement"], 1.0)
        st.markdown(f"**참여도** {summary['avg_engagement']:.2f}% / S기준 {s_thr['engagement']}%")
        st.progress(eg_pct)

    # ══════════════════════════════════════════
    # 섹션 4: 차트
    # ══════════════════════════════════════════
    st.divider()
    ch1, ch2 = st.columns(2)

    with ch1:
        st.markdown("**📈 조회수 추이**")
        fig_trend = px.line(
            summary["valid_df"],
            x="published_at",
            y="view_count",
            markers=True,
            hover_data={"title": True, "view_count": ":,", "published_at": False},
            labels={"published_at": "업로드일", "view_count": "조회수"},
            color_discrete_sequence=["#FF4B4B"],
        )
        # 평균 조회수 기준선 추가
        fig_trend.add_hline(
            y=summary["avg_views"],
            line_dash="dot",
            line_color="gray",
            annotation_text=f"평균 {summary['avg_views']:,.0f}",
            annotation_position="top left",
        )
        fig_trend.update_layout(
            height=320, margin=dict(l=0, r=0, t=10, b=0), xaxis_title=None
        )
        st.plotly_chart(fig_trend, use_container_width=True)

    with ch2:
        st.markdown("**💬 참여도 상위 영상 Top 10**")
        top10 = summary["valid_df"].nlargest(10, "engagement_rate").copy()
        # 제목 길이 제한 (차트 가독성)
        top10["short_title"] = top10["title"].str[:28] + "…"
        fig_eng = px.bar(
            top10,
            x="engagement_rate",
            y="short_title",
            orientation="h",
            labels={"engagement_rate": "참여도 (%)", "short_title": ""},
            color="engagement_rate",
            color_continuous_scale="Reds",
            hover_data={"title": True, "engagement_rate": ":.2f"},
        )
        fig_eng.update_layout(
            height=320,
            margin=dict(l=0, r=0, t=10, b=0),
            coloraxis_showscale=False,
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig_eng, use_container_width=True)

    # ══════════════════════════════════════════
    # 섹션 5: 진단 리포트
    # ══════════════════════════════════════════
    st.divider()
    st.markdown("### 📋 MCN 진단 리포트")
    r1, r2 = st.columns(2)
    with r1:
        st.markdown("**✅ 강점**")
        for item in diag["strengths"]:
            st.markdown(f"- {item}")
    with r2:
        st.markdown("**🎯 개선 제안**")
        for item in diag["improvements"]:
            st.markdown(f"- {item}")

    # ══════════════════════════════════════════
    # 섹션 6: 원시 데이터 (접기)
    # ══════════════════════════════════════════
    with st.expander("📄 영상별 원시 데이터"):
        disp = df[["title", "published_at", "view_count", "like_count", "comment_count", "engagement_rate"]].copy()
        disp.columns = ["제목", "업로드일", "조회수", "좋아요", "댓글", "참여도(%)"]
        disp["업로드일"] = disp["업로드일"].dt.strftime("%Y-%m-%d")
        disp["참여도(%)"] = disp["참여도(%)"].round(2)
        st.dataframe(disp, use_container_width=True, hide_index=True)

    # ── 히스토리 저장 ───────────────────────────
    top_videos = (
        summary["valid_df"]
        .nlargest(10, "engagement_rate")[["title", "view_count", "engagement_rate"]]
        .round({"engagement_rate": 2})
        .to_dict("records")
    )
    hist.save_result(TAB, channel["title"], {
        "channel_id":       channel_id,
        "channel_title":    channel["title"],
        "thumbnail":        channel["thumbnail"],
        "subscriber_count": channel["subscriber_count"],
        "avg_views":        round(summary["avg_views"], 0),
        "view_rate":        round(summary["view_rate"], 2),
        "avg_engagement":   round(summary["avg_engagement"], 3),
        "upload_freq":      round(summary["upload_freq"], 1),
        "grade":            grade,
        "top_videos":       top_videos,
    })
