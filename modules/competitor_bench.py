"""
경쟁 채널 아웃라이어(Outlier) 분석 모듈 - Step 3

핵심 분석:
  1. Outlier Detection    : 채널 평균 조회수 × N배 이상 '급상승 영상' 추출
  2. Engagement Score     : (좋아요+댓글) / 구독자수 × 100 — 채널 규모 보정
  3. Content Gap Analysis : 경쟁사 태그 합집합 - 내 채널 태그 → 미개척 키워드
  4. 제목 패턴 힌트        : 숫자형·질문형·랭킹형 등 터진 영상의 공통 패턴 추출
"""

import re
import streamlit as st
import pandas as pd
import plotly.express as px
from collections import Counter


def _mermaid_safe(text: str, max_len: int = 10) -> str:
    """Mermaid 포인트 레이블에 사용 불가한 문자 제거 후 길이 제한."""
    return re.sub(r'[:\[\]()"\'=]', '', text).strip()[:max_len] or "채널"

from core import history as hist

TAB = "competitor_bench"

from core.api_handler import YouTubeAPIHandler

ANALYZE_VIDEO_COUNT   = 50   # 경쟁사 채널당 최근 영상 수
DEFAULT_OUTLIER_MULT  = 2.0  # 기본 아웃라이어 배율 (평균 × 200%)


# ──────────────────────────────────────────────
# 데이터 처리 함수
# ──────────────────────────────────────────────

def _build_df(videos: list[dict], stats: list[dict]) -> pd.DataFrame:
    """영상 목록 + 통계 병합 → DataFrame"""
    stats_map = {s["video_id"]: s for s in stats}
    rows = []
    for v in videos:
        s = stats_map.get(v["video_id"], {})
        rows.append({
            "video_id":      v["video_id"],
            "title":         v["title"],
            "published_at":  pd.to_datetime(v["published_at"]),
            "thumbnail":     v.get("thumbnail", ""),
            "view_count":    s.get("view_count", 0),
            "like_count":    s.get("like_count", 0),
            "comment_count": s.get("comment_count", 0),
            "tags":          s.get("tags", []),
        })
    return (
        pd.DataFrame(rows)
        .sort_values("published_at", ascending=False)
        .reset_index(drop=True)
    )


def _channel_summary(df: pd.DataFrame, ch: dict, multiplier: float) -> dict:
    """채널별 요약 지표 + 아웃라이어 추출"""
    valid = df[df["view_count"] > 0].copy()
    sub   = ch["subscriber_count"]

    avg_views = valid["view_count"].mean() if not valid.empty else 0
    view_rate = (avg_views / sub * 100) if sub > 0 else 0

    # Engagement Score: 구독자 규모 보정 (채널 간 공정 비교)
    eng_score = 0.0
    if sub > 0 and not valid.empty:
        eng_score = (
            (valid["like_count"] + valid["comment_count"]) / sub * 100
        ).mean()

    # 아웃라이어: 채널 평균 조회수 × multiplier 이상
    threshold = avg_views * multiplier
    outliers  = valid[valid["view_count"] >= threshold].copy()
    if not outliers.empty:
        outliers["outlier_ratio"] = outliers["view_count"] / avg_views

    return {
        "channel_id":    ch["channel_id"],
        "title":         ch["title"],
        "thumbnail":     ch["thumbnail"],
        "subscriber":    sub,
        "avg_views":     avg_views,
        "view_rate":     view_rate,
        "eng_score":     eng_score,
        "outlier_count": len(outliers),
        "outlier_df":    outliers,
        "df":            valid,
    }


def _content_gap(my_df: pd.DataFrame, comp_dfs: list[pd.DataFrame]) -> list[tuple]:
    """
    경쟁사 태그 합집합 - 내 채널 태그 = 미개척 키워드
    Returns: [(keyword, count), ...] 상위 30개
    """
    my_tags = {t.lower() for tags in my_df["tags"] for t in tags}

    counter = Counter()
    for df in comp_dfs:
        for tags in df["tags"]:
            for t in tags:
                counter[t.lower()] += 1

    gap = {t: cnt for t, cnt in counter.items() if t not in my_tags and len(t) > 1}
    return sorted(gap.items(), key=lambda x: x[1], reverse=True)[:30]


def _title_patterns(title: str) -> list[str]:
    """제목에서 '터지는' 패턴 힌트 추출"""
    hints = []
    if any(c.isdigit() for c in title):
        hints.append("숫자 포함")
    if "?" in title:
        hints.append("질문형")
    if any(k in title for k in ["비밀", "충격", "반전", "놀라운", "실제", "진짜", "최초", "역대"]):
        hints.append("자극적 키워드")
    if any(k in title for k in ["방법", "하는법", "하는 법", "가이드", "따라하기"]):
        hints.append("How-To형")
    if any(k in title for k in ["Top", "TOP", "베스트", "순위", "랭킹", "위"]):
        hints.append("랭킹형")
    if any(k in title for k in ["vlog", "브이로그", "일상", "하루"]):
        hints.append("브이로그형")
    return hints or ["일반형"]


# ──────────────────────────────────────────────
# Streamlit UI
# ──────────────────────────────────────────────

@st.dialog("경쟁사 분석 기록", width="large")
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

    # ── 채널 비교표 ──
    rows = d.get("channels", [])
    if rows:
        st.markdown("#### 채널 지표 비교")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── Mermaid: 조회율 vs 참여도 쿼드런트 ──
    if rows:
        st.divider()
        st.caption("채널 포지션 (조회율 vs Engagement Score)")
        pts = "\n    ".join(
            f"{_mermaid_safe(r['채널명'])}: [{min(float(r['조회율(%)'].rstrip('%'))/20,0.95):.2f}, "
            f"{min(float(r['Engagement'].rstrip('%'))/0.5,0.95):.2f}]"
            for r in rows
        )
        mmd = f"""quadrantChart
    title 경쟁사 포지션 비교
    x-axis 낮은 조회율 --> 높은 조회율
    y-axis 낮은 참여도 --> 높은 참여도
    quadrant-1 최상위
    quadrant-2 팬덤 강함
    quadrant-3 성장 초기
    quadrant-4 도달 강함
    {pts}"""
        hist.render_mermaid(mmd, height=360)

    # ── Content Gap ──
    gap = d.get("gap_keywords", [])
    if gap:
        st.divider()
        st.caption("Content Gap 키워드")
        st.write(", ".join(f"`{k}`" for k, _ in gap[:20]))


def render_competitor_bench():
    st.subheader("🔍 경쟁사 벤치마킹 & 아웃라이어 분석")

    api_key = st.session_state.get("youtube_api_key", "")
    if not api_key:
        st.error("❌ 사이드바에서 YouTube API 키를 먼저 입력하세요.")
        return

    if st.button("📂 최근 기록", key="comp_hist"):
        _history_dialog()

    # ── 입력 영역 ──────────────────────────────
    with st.expander("📋 분석 설정", expanded=True):
        my_ch_id = st.text_input(
            "내 채널 (선택 — 입력 시 Content Gap 분석 활성화)",
            placeholder="UCxxxxxx  또는  @handle",
        )
        st.markdown("**경쟁 채널 ID 또는 핸들 (최대 3개)**")
        c1, c2, c3 = st.columns(3)
        raw_ids = [
            c1.text_input("경쟁 채널 1", placeholder="UCxxxxxx 또는 @handle", key="comp1"),
            c2.text_input("경쟁 채널 2", placeholder="UCxxxxxx 또는 @handle", key="comp2"),
            c3.text_input("경쟁 채널 3", placeholder="UCxxxxxx 또는 @handle", key="comp3"),
        ]
        comp_ids = [cid.strip() for cid in raw_ids if cid.strip()]

        outlier_mult = st.slider(
            "아웃라이어 기준 배율 (채널 평균 조회수의 N배 이상을 '급상승'으로 판정)",
            min_value=1.5, max_value=5.0, value=DEFAULT_OUTLIER_MULT, step=0.5,
        )
        run = st.button("🚀 벤치마킹 시작", type="primary", use_container_width=True)

    if not comp_ids:
        st.caption("경쟁 채널 ID 또는 핸들을 1개 이상 입력하세요.")
        return
    if not run:
        return

    # ── 데이터 수집 ────────────────────────────
    handler    = YouTubeAPIHandler(api_key=api_key)
    comp_data  = []   # 경쟁 채널 summary 목록
    my_summary = None

    raw_targets = ([(my_ch_id.strip(), True)] if my_ch_id.strip() else []) + [
        (cid, False) for cid in comp_ids
    ]
    prog = st.progress(0, text="채널 데이터 수집 중...")

    for i, (raw_id, is_mine) in enumerate(raw_targets):
        prog.progress((i + 1) / len(raw_targets), text=f"수집 중: {raw_id}")
        try:
            ch_id   = handler.resolve_channel_id(raw_id)
            ch_info = handler.get_channel_info(ch_id)
            if not ch_info:
                st.warning(f"채널을 찾을 수 없습니다: `{raw_id}`")
                continue
            videos  = handler.get_channel_videos(
                ch_info["uploads_playlist_id"], max_results=ANALYZE_VIDEO_COUNT
            )
            stats   = handler.get_video_stats([v["video_id"] for v in videos])
            df      = _build_df(videos, stats)
            summary = _channel_summary(df, ch_info, outlier_mult)

            if is_mine:
                my_summary = summary
            else:
                comp_data.append(summary)

        except RuntimeError as e:
            st.error(f"API 오류 ({raw_id}): {e}")

    prog.empty()

    if not comp_data:
        st.error("경쟁 채널 데이터를 하나도 가져오지 못했습니다.")
        return

    # ══════════════════════════════════════════
    # 섹션 1: 채널 지표 비교 테이블
    # ══════════════════════════════════════════
    st.divider()
    st.markdown("### 📊 채널 지표 비교")

    rows = []
    for s in comp_data:
        rows.append({
            "채널명":                      s["title"],
            "구독자":                      f"{s['subscriber']:,}명",
            "평균 조회수":                 f"{s['avg_views']:,.0f}회",
            "구독자 대비 조회율":          f"{s['view_rate']:.1f}%",
            "Engagement Score":           f"{s['eng_score']:.3f}%",
            f"아웃라이어 ({outlier_mult:.1f}x)": f"{s['outlier_count']}개",
        })

    if my_summary:
        rows.insert(0, {
            "채널명":                      f"⭐ {my_summary['title']} (내 채널)",
            "구독자":                      f"{my_summary['subscriber']:,}명",
            "평균 조회수":                 f"{my_summary['avg_views']:,.0f}회",
            "구독자 대비 조회율":          f"{my_summary['view_rate']:.1f}%",
            "Engagement Score":           f"{my_summary['eng_score']:.3f}%",
            f"아웃라이어 ({outlier_mult:.1f}x)": f"{my_summary['outlier_count']}개",
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # 조회율 + Engagement Score 비교 차트
    ch_col1, ch_col2 = st.columns(2)
    with ch_col1:
        fig_vr = px.bar(
            x=[s["title"] for s in comp_data],
            y=[s["view_rate"] for s in comp_data],
            labels={"x": "채널", "y": "조회율 (%)"},
            color=[s["view_rate"] for s in comp_data],
            color_continuous_scale="Reds",
            title="구독자 대비 조회율",
        )
        if my_summary:
            fig_vr.add_hline(
                y=my_summary["view_rate"], line_dash="dot", line_color="#4B7BFF",
                annotation_text=f"내 채널 {my_summary['view_rate']:.1f}%",
                annotation_position="top right",
            )
        fig_vr.update_layout(
            height=280, margin=dict(l=0, r=0, t=40, b=0), coloraxis_showscale=False
        )
        st.plotly_chart(fig_vr, use_container_width=True)

    with ch_col2:
        fig_eg = px.bar(
            x=[s["title"] for s in comp_data],
            y=[s["eng_score"] for s in comp_data],
            labels={"x": "채널", "y": "Engagement Score (%)"},
            color=[s["eng_score"] for s in comp_data],
            color_continuous_scale="Blues",
            title="Engagement Score (구독자 규모 보정)",
        )
        if my_summary:
            fig_eg.add_hline(
                y=my_summary["eng_score"], line_dash="dot", line_color="#4B7BFF",
                annotation_text=f"내 채널 {my_summary['eng_score']:.3f}%",
                annotation_position="top right",
            )
        fig_eg.update_layout(
            height=280, margin=dict(l=0, r=0, t=40, b=0), coloraxis_showscale=False
        )
        st.plotly_chart(fig_eg, use_container_width=True)

    # ══════════════════════════════════════════
    # 섹션 2: 아웃라이어 영상 — "왜 이 영상이 터졌나?"
    # ══════════════════════════════════════════
    st.divider()
    st.markdown(f"### 🚀 아웃라이어 영상 — 왜 이 영상이 터졌나? (평균 × {outlier_mult:.1f}배 이상)")
    st.caption("Engagement Score가 높을수록 조회수 외에도 진짜 팬 반응이 강한 영상입니다.")

    for s in comp_data:
        outliers = s["outlier_df"]
        with st.expander(
            f"📺 {s['title']} — 아웃라이어 {len(outliers)}개 / 채널 평균 {s['avg_views']:,.0f}회",
            expanded=len(outliers) > 0,
        ):
            if outliers.empty:
                st.info(f"기준({outlier_mult:.1f}x) 이상 영상이 없습니다. 배율 슬라이더를 낮춰보세요.")
                continue

            for _, row in outliers.head(10).iterrows():
                patterns = _title_patterns(row["title"])
                sub      = s["subscriber"]
                eng      = (
                    (row["like_count"] + row["comment_count"]) / sub * 100
                    if sub > 0 else 0
                )

                img_col, info_col = st.columns([1, 5])
                with img_col:
                    if row["thumbnail"]:
                        st.image(row["thumbnail"], width=110)
                with info_col:
                    st.markdown(f"**{row['title']}**")
                    mc1, mc2, mc3, mc4 = st.columns(4)
                    mc1.metric("조회수",         f"{row['view_count']:,}")
                    mc2.metric("평균 대비",      f"{row['outlier_ratio']:.1f}x")
                    mc3.metric("Engagement",    f"{eng:.3f}%")
                    mc4.metric("업로드",         row["published_at"].strftime("%Y-%m-%d"))
                    st.caption(f"🔖 제목 패턴: **{'  /  '.join(patterns)}**")
                st.divider()

    # ══════════════════════════════════════════
    # 섹션 3: Content Gap 분석 (내 채널 입력 시)
    # ══════════════════════════════════════════
    st.divider()

    if my_summary:
        st.markdown("### 🎯 Content Gap 분석")
        st.caption("경쟁사가 다루지만 내 채널이 아직 다루지 않은 키워드")

        gap = _content_gap(my_summary["df"], [s["df"] for s in comp_data])

        if gap:
            gap_df = pd.DataFrame(gap, columns=["키워드", "경쟁사 사용 횟수"])
            tbl_col, bar_col = st.columns([1, 2])
            with tbl_col:
                st.dataframe(gap_df.head(15), use_container_width=True, hide_index=True)
            with bar_col:
                fig_gap = px.bar(
                    gap_df.head(15),
                    x="경쟁사 사용 횟수",
                    y="키워드",
                    orientation="h",
                    color="경쟁사 사용 횟수",
                    color_continuous_scale="Greens",
                    title="Content Gap 키워드 Top 15",
                )
                fig_gap.update_layout(
                    height=380, margin=dict(l=0, r=0, t=40, b=0),
                    coloraxis_showscale=False,
                    yaxis=dict(autorange="reversed"),
                )
                st.plotly_chart(fig_gap, use_container_width=True)

            st.success(
                "💡 위 키워드로 영상을 제작하면 경쟁사 시청자를 흡수할 수 있습니다. "
                "**Step 4 AI 기획기**에서 이 키워드를 활용해 제목·썸네일·스크립트를 자동 생성하세요."
            )
        else:
            st.success("Content Gap이 없습니다. 경쟁사 키워드를 이미 충분히 커버하고 있습니다.")
    else:
        st.info(
            "💡 **Content Gap 분석**은 '내 채널 ID'를 입력하면 활성화됩니다. "
            "경쟁사 대비 미개척 키워드를 자동으로 추출합니다."
        )

    # ── 히스토리 저장 ───────────────────────────
    ch_rows = [{
        "채널명":     s["title"],
        "구독자":     f"{s['subscriber']:,}",
        "조회율(%)":  f"{s['view_rate']:.1f}%",
        "Engagement": f"{s['eng_score']:.3f}%",
        "아웃라이어":  s["outlier_count"],
    } for s in comp_data]
    gap_kws = _content_gap(my_summary["df"], [s["df"] for s in comp_data]) if my_summary else []
    label = " vs ".join(s["title"] for s in comp_data[:2])
    hist.save_result(TAB, label, {
        "channels":     ch_rows,
        "gap_keywords": gap_kws[:20],
        "outlier_mult": outlier_mult,
    })
