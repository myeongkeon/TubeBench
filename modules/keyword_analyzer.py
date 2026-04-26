"""
키워드 분석 모듈

사용자가 입력한 키워드의 바이럴·인기·트렌드 적합성을 분석하여
100점 만점으로 영상 성공 가능성을 평가합니다.

점수 구성 (100점):
  바이럴 잠재력 (30점): 상위 영상 평균 조회수  → 수요 증명
  참여도       (20점): 좋아요+댓글/조회수 비율 → 시청자 관심도
  트렌드 현황  (25점): 최근 업로드 빈도 + 조회 속도 → 지금 뜨는지
  진입 기회    (25점): 조회수 분포 균등성 (Gini 역수) → 독점 여부
"""

import statistics
from datetime import datetime, timezone

import streamlit as st
import pandas as pd

from core.api_handler import YouTubeAPIHandler
from core.ai_router import AIRunner

TAB = "keyword_analyzer"

# ──────────────────────────────────────────────
# 점수 계산
# ──────────────────────────────────────────────

def _compute_score(stats: list[dict]) -> dict:
    if not stats:
        return {"total": 0, "viral": 0, "engagement": 0, "trend": 0, "opportunity": 0,
                "avg_views": 0, "avg_eng_rate": 0.0, "avg_velocity": 0.0}

    now = datetime.now(timezone.utc)
    view_counts = [s["view_count"] for s in stats]

    # 1. 바이럴 잠재력 (30점): 상위 영상 평균 조회수
    avg_views = statistics.mean(view_counts)
    if avg_views >= 2_000_000:   viral = 30
    elif avg_views >= 1_000_000: viral = 27
    elif avg_views >= 500_000:   viral = 23
    elif avg_views >= 100_000:   viral = 18
    elif avg_views >= 50_000:    viral = 13
    elif avg_views >= 10_000:    viral = 8
    else:                        viral = 4

    # 2. 참여도 (20점): (좋아요 + 댓글) / 조회수
    eng_rates = []
    for s in stats:
        if s["view_count"] > 0:
            eng_rates.append((s["like_count"] + s["comment_count"]) / s["view_count"])
    avg_eng = statistics.mean(eng_rates) if eng_rates else 0.0

    if avg_eng >= 0.08:     engagement = 20
    elif avg_eng >= 0.05:   engagement = 17
    elif avg_eng >= 0.03:   engagement = 14
    elif avg_eng >= 0.015:  engagement = 10
    elif avg_eng >= 0.005:  engagement = 6
    else:                   engagement = 2

    # 3. 트렌드 현황 (25점)
    # 업로드 빈도 (12점): 최근 30일 내 업로드 비율
    recent_30d = sum(
        1 for s in stats
        if (now - datetime.fromisoformat(s["published_at"].replace("Z", "+00:00"))).days <= 30
    )
    freq_ratio = recent_30d / len(stats)
    if freq_ratio >= 0.6:   freq_score = 12
    elif freq_ratio >= 0.4: freq_score = 9
    elif freq_ratio >= 0.2: freq_score = 6
    else:                   freq_score = 3

    # 조회 속도 (13점): 최근 30일 영상 평균 시간당 조회수
    velocities = []
    for s in stats:
        pub = datetime.fromisoformat(s["published_at"].replace("Z", "+00:00"))
        hours = max((now - pub).total_seconds() / 3600, 1)
        if hours <= 720:  # 30일 이내
            velocities.append(s["view_count"] / hours)
    avg_vel = statistics.mean(velocities) if velocities else 0.0

    if avg_vel >= 5000:     vel_score = 13
    elif avg_vel >= 2000:   vel_score = 10
    elif avg_vel >= 500:    vel_score = 7
    elif avg_vel >= 100:    vel_score = 4
    else:                   vel_score = 1

    trend = freq_score + vel_score

    # 4. 진입 기회 (25점): 조회수 Gini 역수 (분포가 균등할수록 독점 없음 = 기회)
    sorted_v = sorted(view_counts)
    n = len(sorted_v)
    total_v = sum(sorted_v)
    if n > 1 and total_v > 0:
        cum = sum((i + 1) * v for i, v in enumerate(sorted_v))
        gini = max(0.0, min(1.0, (2 * cum) / (n * total_v) - (n + 1) / n))
        opportunity = round(25 * (1 - gini))
    else:
        opportunity = 12

    total = min(100, viral + engagement + trend + opportunity)

    return {
        "total":        total,
        "viral":        viral,
        "engagement":   engagement,
        "trend":        trend,
        "opportunity":  opportunity,
        "avg_views":    round(avg_views),
        "avg_eng_rate": round(avg_eng * 100, 2),
        "avg_velocity": round(avg_vel, 1),
    }


def _score_label(total: int) -> tuple[str, str]:
    if total >= 80:   return "🔥 매우 강력", "#FF4B4B"
    elif total >= 65: return "⭐ 강력",      "#FF8C00"
    elif total >= 50: return "✅ 보통",      "#FFC107"
    elif total >= 35: return "⚠️ 낮음",      "#9E9E9E"
    else:             return "❌ 매우 낮음", "#607D8B"


# ──────────────────────────────────────────────
# AI 프롬프트
# ──────────────────────────────────────────────

KEYWORD_SYSTEM = """\
당신은 YouTube SEO 전문가이자 MCN 콘텐츠 전략가입니다.
키워드 분석 데이터를 바탕으로 해당 키워드의 성공 가능성과 영상 기획 방향을 제시합니다.
분석은 구체적이고 실행 가능하게, 한국어로 작성하세요.\
"""

COMMENT_SYSTEM = """\
당신은 YouTube 시청자 심리 분석 전문가이자 MCN 콘텐츠 기획자입니다.
댓글 데이터에서 시청자의 니즈, 불만, 요청사항(VOC)을 파악하여
새로운 영상 기획안을 제시합니다. 분석은 구체적이고 실행 가능하게 한국어로 작성하세요.\
"""


def _keyword_ai_prompt(keyword: str, score: dict, videos: list[dict], stats: list[dict]) -> str:
    stats_map = {s["video_id"]: s for s in stats}
    lines = []
    for v in videos[:10]:
        s = stats_map.get(v["video_id"], {})
        lines.append(
            f'- "{v["title"][:60]}" ({v["channel_title"]}) '
            f'| 조회수 {s.get("view_count", 0):,} | 좋아요 {s.get("like_count", 0):,}'
        )

    return f"""\
## 분석 키워드: "{keyword}"

## 점수 결과
- 종합 점수: {score["total"]}/100
- 바이럴 잠재력: {score["viral"]}/30 (평균 조회수 {score["avg_views"]:,}회)
- 참여도: {score["engagement"]}/20 (평균 참여율 {score["avg_eng_rate"]}%)
- 트렌드 현황: {score["trend"]}/25 (평균 조회 속도 {score["avg_velocity"]}회/h)
- 진입 기회: {score["opportunity"]}/25

## 상위 검색 결과 영상 (관련도 순 상위 10개)
{chr(10).join(lines)}

## 요청
### 1. 점수 해석
이 키워드의 성공 가능성과 각 점수 요소의 의미를 구체적으로 설명하세요.

### 2. 성공 전략 3가지
이 키워드로 경쟁에서 이기는 핵심 전략

### 3. 제목 후보 5개
클릭률 높은 제목 (숫자형·질문형·자극형·How-To형 혼합)

### 4. 주의사항
이 키워드의 위험 요소 또는 주의할 점

### 5. 최적 업로드 전략
언제, 어떤 형식(길이·포맷·썸네일 방향)으로 올리면 좋은지\
"""


def _comment_ai_prompt(video_title: str, keyword: str, comments: list[dict]) -> str:
    top = sorted(comments, key=lambda c: c["like_count"], reverse=True)[:30]
    comment_lines = [f'[좋아요 {c["like_count"]}] {c["text"]}' for c in top]

    return f"""\
## 분석 키워드: "{keyword}"
## 분석 영상: "{video_title}"

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
- **예상 반응**: 왜 이 기획이 시청자에게 먹힐 것인가

### 3. 영상 도입부 훅(Hook) 문장 3개
댓글에서 발견한 시청자 언어를 활용한 도입부 멘트\
"""


# ──────────────────────────────────────────────
# 댓글 분석 UI (재사용 가능)
# ──────────────────────────────────────────────

def _render_comment_section(handler: YouTubeAPIHandler, videos: list[dict],
                             stats: list[dict], keyword: str, section_key: str):
    st.markdown("### 💬 댓글분석 및 기획")
    st.caption("영상 댓글을 분석하여 시청자 니즈(VOC)를 파악하고 새로운 영상을 기획합니다.")

    stats_map = {s["video_id"]: s for s in stats}
    eligible = [
        v for v in videos
        if stats_map.get(v["video_id"], {}).get("comment_count", 0) > 0
    ]

    if not eligible:
        st.info("댓글을 수집할 수 있는 영상이 없습니다.")
        return

    options = {
        f'{v["title"][:55]} ({stats_map.get(v["video_id"], {}).get("view_count", 0):,}회)': v
        for v in eligible
    }
    sel_label = st.selectbox("댓글 분석할 영상 선택", list(options.keys()), key=f"{section_key}_sel")
    sel_video = options[sel_label]

    if not st.button("💬 댓글 수집 & 기획 분석", type="secondary",
                     use_container_width=True, key=f"{section_key}_btn"):
        return

    with st.spinner("댓글 수집 중..."):
        try:
            comments = handler.get_video_comments(sel_video["video_id"], max_results=100)
        except RuntimeError as e:
            st.error(f"댓글 수집 실패: {e}")
            return

    if not comments:
        st.warning("댓글이 없거나 댓글이 비활성화된 영상입니다.")
        return

    st.success(f"✅ 댓글 {len(comments)}개 수집 완료")

    with st.expander("📝 수집된 댓글 (좋아요 순)", expanded=False):
        top_comments = sorted(comments, key=lambda c: c["like_count"], reverse=True)[:20]
        for c in top_comments:
            st.markdown(f"**👍 {c['like_count']}** · {c['text'][:120]}")

    comment_box = st.empty()
    prompt = _comment_ai_prompt(sel_video["title"], keyword, comments)
    runner = AIRunner(tab_key=f"{section_key}_ai", system=COMMENT_SYSTEM, max_tokens=3000)
    runner.execute(prompt, comment_box, preferred="gemini-2.0-flash")


# ──────────────────────────────────────────────
# 메인 렌더
# ──────────────────────────────────────────────

def render_keyword_analyzer():
    st.subheader("🔎 키워드 분석")
    st.caption("특정 키워드의 바이럴·인기·트렌드 적합성을 분석하여 영상 성공 가능성을 100점 만점으로 평가합니다.")
    st.warning(
        "⚠️ 키워드 검색은 YouTube API **100 units**을 소모합니다. "
        "(일일 할당량 10,000 units 기준 최대 100회 검색 가능)",
        icon="⚠️",
    )

    yt_key = st.session_state.get("youtube_api_key", "")
    if not yt_key:
        st.error("❌ 사이드바에서 YouTube API 키를 먼저 입력하세요.")
        return

    handler = YouTubeAPIHandler(api_key=yt_key)

    # ── 키워드 입력 ──────────────────────────────
    col_inp, col_btn = st.columns([5, 1])
    with col_inp:
        keyword = st.text_input(
            "키워드",
            placeholder="예: 주식 투자 초보, 다이어트 식단, 파이썬 강의",
            label_visibility="collapsed",
            key="kw_input",
        )
    with col_btn:
        run = st.button("🔍 분석", type="primary", use_container_width=True, disabled=not keyword)

    if run and keyword:
        # 데이터 수집 및 session_state 저장
        with st.spinner(f'"{keyword}" 키워드 검색 중... (100 units 소모)'):
            try:
                search_results = handler.search_videos_by_keyword(keyword, max_results=20)
            except RuntimeError as e:
                st.error(f"검색 실패: {e}")
                return

        if not search_results:
            st.warning("검색 결과가 없습니다. 다른 키워드를 시도하세요.")
            return

        with st.spinner("영상 통계 수집 중..."):
            try:
                stats = handler.get_video_stats([v["video_id"] for v in search_results])
            except RuntimeError as e:
                st.error(f"통계 조회 실패: {e}")
                return

        score = _compute_score(stats)
        st.session_state["kw_result"] = {
            "keyword":        keyword,
            "search_results": search_results,
            "stats":          stats,
            "score":          score,
            "ai_output":      None,
        }

    # ── 결과 표시 (세션 캐시 기반) ───────────────
    result = st.session_state.get("kw_result")
    if not result:
        return

    keyword     = result["keyword"]
    search_results = result["search_results"]
    stats       = result["stats"]
    score       = result["score"]
    total       = score["total"]
    grade, color = _score_label(total)

    st.divider()
    st.markdown(f"### 🔎 \"{keyword}\" 키워드 분석 결과")

    score_col, detail_col = st.columns([1, 2])
    with score_col:
        st.markdown(
            f"""
            <div style="text-align:center; padding:24px 16px; border-radius:14px;
                        background:linear-gradient(135deg,#1e1e2e,#2a2a3e);
                        border:2px solid {color};">
                <div style="font-size:64px; font-weight:900; color:{color}; line-height:1;">
                    {total}
                </div>
                <div style="font-size:13px; color:#aaa; margin-top:4px;">/ 100점</div>
                <div style="font-size:20px; margin-top:10px;">{grade}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with detail_col:
        st.markdown("**세부 점수**")
        for label, val, max_val, hint in [
            ("🔥 바이럴 잠재력", score["viral"],       30, f"평균 조회수 {score['avg_views']:,}회"),
            ("💬 참여도",       score["engagement"],   20, f"평균 참여율 {score['avg_eng_rate']}%"),
            ("📈 트렌드 현황",  score["trend"],        25, f"조회 속도 {score['avg_velocity']}회/h"),
            ("🚪 진입 기회",    score["opportunity"],  25, "조회수 분포 균등성"),
        ]:
            st.markdown(f"**{label}** `{val}/{max_val}` · {hint}")
            st.progress(val / max_val)

    # 상위 영상 테이블
    with st.expander("📋 검색 상위 영상 목록", expanded=False):
        stats_map = {s["video_id"]: s for s in stats}
        rows = []
        for v in search_results:
            s = stats_map.get(v["video_id"], {})
            rows.append({
                "제목":    v["title"],
                "채널":    v["channel_title"],
                "조회수":  s.get("view_count", 0),
                "좋아요":  s.get("like_count", 0),
                "댓글":    s.get("comment_count", 0),
                "업로드일": v["published_at"][:10],
            })
        df = pd.DataFrame(rows).sort_values("조회수", ascending=False).reset_index(drop=True)
        st.dataframe(df, use_container_width=True, hide_index=True)

    # ── AI 키워드 전략 분석 ──────────────────────
    st.divider()
    st.markdown("### 🤖 AI 키워드 전략 분석")

    if result.get("ai_output") is None:
        output_box = st.empty()
        prompt = _keyword_ai_prompt(keyword, score, search_results, stats)
        runner = AIRunner(tab_key=f"{TAB}_main", system=KEYWORD_SYSTEM, max_tokens=3000)
        ai_out = runner.execute(prompt, output_box, preferred="gemini-2.0-flash")
        if ai_out is None:
            return  # 승인 대기 중
        result["ai_output"] = ai_out
        st.session_state["kw_result"] = result
    else:
        st.markdown(result["ai_output"])

    # ── 댓글 분석 및 기획 ───────────────────────
    st.divider()
    _render_comment_section(
        handler=handler,
        videos=search_results,
        stats=stats,
        keyword=keyword,
        section_key=f"{TAB}_comment",
    )
