"""
트렌드 기획 모듈

경쟁채널의 최근 3일 업로드를 분석해 '지금 올리면 좋을 영상'을 AI가 추천.
분석 완료 후 '댓글분석 및 기획' 기능으로 경쟁 영상 댓글에서 시청자 VOC를 파악하여
새로운 영상을 기획합니다.

MCN 관점 추가 로직:
  - 업로드 후 경과 시간 대비 조회수 → 빠르게 트렌딩 중인 영상 가중치
  - 제목 패턴 분류 → 현재 잘 먹히는 포맷 파악
  - 키워드 클러스터링 → 중복 주제 = 지금 트렌드
"""

import os
from datetime import datetime, timezone, timedelta
from collections import Counter

import streamlit as st
import pandas as pd
import google.generativeai as genai
import anthropic

from core.api_handler import YouTubeAPIHandler
from core import history as hist
from core.ai_router import AIRunner
from modules.channel_profiles import (
    list_profiles, load_profile, save_profile, delete_profile
)

TAB = "trend_planner"

# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────
TREND_DAYS     = 3      # 최근 N일 업로드 분석
MAX_PER_CH     = 10     # 채널당 최대 수집 영상
VELOCITY_HOURS = 48     # 조회수 속도 계산 기준 (업로드 후 N시간 이내)


# ──────────────────────────────────────────────
# 데이터 수집 & 분석
# ──────────────────────────────────────────────

def _fetch_recent_videos(handler: YouTubeAPIHandler, channel: dict) -> list[dict]:
    """경쟁채널에서 최근 TREND_DAYS일 영상만 추출"""
    videos = handler.get_channel_videos(
        channel["uploads_playlist_id"], max_results=MAX_PER_CH
    )
    cutoff = datetime.now(timezone.utc) - timedelta(days=TREND_DAYS)
    recent = [
        v for v in videos
        if datetime.fromisoformat(v["published_at"].replace("Z", "+00:00")) >= cutoff
    ]
    return recent


def _velocity_score(view_count: int, published_at: str) -> float:
    """업로드 후 경과 시간 대비 조회수 → 시간당 조회수(트렌딩 속도)"""
    pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    hours = max((datetime.now(timezone.utc) - pub).total_seconds() / 3600, 1)
    return view_count / hours


def _title_patterns(title: str) -> list[str]:
    hints = []
    if any(c.isdigit() for c in title):
        hints.append("숫자형")
    if "?" in title:
        hints.append("질문형")
    if any(k in title for k in ["비밀", "충격", "반전", "놀라운", "실제", "진짜", "최초", "역대"]):
        hints.append("자극형")
    if any(k in title for k in ["방법", "하는법", "하는 법", "가이드", "따라하기"]):
        hints.append("How-To형")
    if any(k in title for k in ["Top", "TOP", "베스트", "순위", "랭킹"]):
        hints.append("랭킹형")
    return hints or ["일반형"]


def _build_trend_summary(comp_data: list[dict]) -> tuple[str, pd.DataFrame]:
    """
    경쟁채널 최근 영상 → AI에 전달할 요약 텍스트 + 표시용 DataFrame 생성

    Returns:
        summary_text: AI 프롬프트에 삽입할 경쟁사 영상 요약
        df: Streamlit 표시용 DataFrame
    """
    rows = []
    for ch in comp_data:
        for v in ch["videos"]:
            velocity = _velocity_score(v["view_count"], v["published_at"])
            rows.append({
                "channel":     ch["title"],
                "title":       v["title"],
                "published_at":v["published_at"][:10],
                "view_count":  v["view_count"],
                "velocity":    round(velocity, 1),
                "patterns":    " / ".join(_title_patterns(v["title"])),
                "tags":        v.get("tags", []),
                "video_id":    v["video_id"],
                "comment_count": v.get("comment_count", 0),
            })

    df = pd.DataFrame(rows).sort_values("velocity", ascending=False).reset_index(drop=True)

    # 텍스트 요약 (AI 전달용, 토큰 절약)
    lines = []
    for _, r in df.head(15).iterrows():
        lines.append(
            f"- [{r['channel']}] \"{r['title']}\" | 조회수 {r['view_count']:,} "
            f"| 속도 {r['velocity']:.0f}회/h | 패턴: {r['patterns']}"
        )

    # 공통 태그 키워드
    all_tags = [t for r in rows for t in r["tags"]]
    top_tags = [t for t, _ in Counter(all_tags).most_common(10)]
    tag_line = "공통 태그 키워드: " + ", ".join(top_tags) if top_tags else ""

    summary_text = "\n".join(lines)
    if tag_line:
        summary_text += f"\n\n{tag_line}"

    return summary_text, df


def _build_trend_prompt(my_channel_title: str, summary_text: str) -> str:
    return f"""\
## 내 채널
{my_channel_title}

## 경쟁채널 최근 {TREND_DAYS}일 업로드 현황 (조회 속도 높은 순)
{summary_text}

## 요청
위 경쟁채널 데이터를 MCN 전략가 관점에서 분석해 다음을 작성해 주세요.

### 📡 지금 뜨는 트렌드 키워드 TOP 5
각 키워드가 왜 지금 뜨고 있는지 근거(어느 채널, 어떤 영상) 포함

### 🎬 오늘 올리면 좋을 영상 추천 3개
각 추천마다:
- **제목 후보 3개** (숫자형·질문형·자극형 혼합)
- **왜 지금인가**: 경쟁채널 근거 + 트렌드 타이밍 설명
- **차별화 포인트**: 경쟁채널 영상과 다르게 만들 핵심 1가지

### ⚡ 긴급도
HIGH / MEDIUM / LOW 중 하나와 이유 (트렌드 수명 예측)\
"""


# ──────────────────────────────────────────────
# AI 호출
# ──────────────────────────────────────────────

TREND_SYSTEM = """\
당신은 실시간 YouTube 트렌드를 분석하는 MCN 콘텐츠 전략가입니다.
경쟁채널 데이터를 바탕으로 지금 당장 올릴 수 있는 트렌드 영상을 추천합니다.
분석은 데이터 기반으로, 추천은 실행 가능하도록 구체적으로 작성하세요.\
"""

COMMENT_SYSTEM = """\
당신은 YouTube 시청자 심리 분석 전문가이자 MCN 콘텐츠 기획자입니다.
댓글 데이터에서 시청자의 니즈, 불만, 요청사항(VOC)을 파악하여
새로운 영상 기획안을 제시합니다. 분석은 구체적이고 실행 가능하게 한국어로 작성하세요.\
"""


def _run_ai(tab_key: str, prompt: str, output_box) -> str | None:
    return AIRunner(tab_key=tab_key, system=TREND_SYSTEM, max_tokens=3000).execute(
        prompt, output_box, preferred="gemini-2.0-flash"
    )


# ──────────────────────────────────────────────
# 채널 추가 다이얼로그 (팝업)
# ──────────────────────────────────────────────

@st.dialog("채널 정보 추가", width="large")
def _add_profile_dialog(handler: YouTubeAPIHandler):
    st.markdown("#### 내 채널")
    my_raw = st.text_input(
        "내 채널 ID 또는 핸들 *",
        placeholder="UCxxxxxx 또는 @handle 또는 youtube.com/@handle",
        key="dlg_my_ch",
    )

    st.markdown("#### 경쟁채널 (최대 10개)")
    left_col, right_col = st.columns(2)
    left_vals  = []
    right_vals = []
    with left_col:
        for i in range(5):
            v = st.text_input(f"경쟁채널 {i+1}", placeholder="@handle", key=f"dlg_comp_{i}")
            left_vals.append(v)
    with right_col:
        for i in range(5):
            v = st.text_input(f"경쟁채널 {i+6}", placeholder="@handle", key=f"dlg_comp_{i+5}")
            right_vals.append(v)
    comp_raws = [c.strip() for c in left_vals + right_vals if c.strip()]

    st.divider()
    if st.button("💾 저장", type="primary", use_container_width=True):
        if not my_raw.strip():
            st.warning("내 채널을 입력하세요.")
            return
        if not comp_raws:
            st.warning("경쟁채널을 1개 이상 입력하세요.")
            return
        with st.spinner("채널 정보 조회 중..."):
            try:
                my_id   = handler.resolve_channel_id(my_raw.strip())
                my_info = handler.get_channel_info(my_id)
                if not my_info:
                    st.error(f"채널을 찾을 수 없습니다: {my_raw}")
                    return
                my_ch = {
                    "channel_id": my_id,
                    "title":      my_info["title"],
                    "thumbnail":  my_info["thumbnail"],
                }
                competitors = []
                for raw in comp_raws:
                    try:
                        cid  = handler.resolve_channel_id(raw)
                        info = handler.get_channel_info(cid)
                        if info:
                            competitors.append({
                                "channel_id": cid,
                                "title":      info["title"],
                                "thumbnail":  info["thumbnail"],
                            })
                    except RuntimeError as e:
                        st.warning(f"경쟁채널 조회 실패 ({raw}): {e}")

                save_profile(my_ch, competitors)
                st.success(f"저장 완료: {my_info['title']} + 경쟁채널 {len(competitors)}개")
                st.rerun()
            except RuntimeError as e:
                st.error(f"오류: {e}")


# ──────────────────────────────────────────────
# 기록 다이얼로그
# ──────────────────────────────────────────────

@st.dialog("트렌드 기획 기록", width="large")
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
        f"채널: {d.get('my_channel','-')} | 경쟁채널 {d.get('competitor_count',0)}개 "
        f"| 영상 {d.get('videos_analyzed',0)}개 분석"
    )
    st.divider()
    st.markdown(d.get("output", ""))


# ──────────────────────────────────────────────
# 댓글 분석 섹션
# ──────────────────────────────────────────────

def _render_comment_section(handler: YouTubeAPIHandler, cached: dict):
    st.divider()
    st.markdown("### 💬 댓글분석 및 기획")
    st.caption(
        "경쟁 영상의 댓글을 분석하여 시청자 니즈(VOC)를 파악하고 "
        "새로운 영상을 기획합니다."
    )

    # 수집된 영상 플랫 리스트 구성
    all_videos = []
    for ch in cached.get("comp_data", []):
        for v in ch["videos"]:
            all_videos.append({**v, "_channel": ch["title"]})

    eligible = [v for v in all_videos if v.get("comment_count", 0) > 0]

    if not eligible:
        st.info("댓글이 있는 경쟁 영상이 없습니다. (댓글 비활성화 또는 0개)")
        return

    options = {
        f'[{v["_channel"]}] {v["title"][:50]} ({v.get("view_count", 0):,}회)': v
        for v in eligible
    }
    sel_label = st.selectbox("댓글 분석할 영상 선택", list(options.keys()),
                              key="trend_comment_sel")
    sel_video = options[sel_label]

    if not st.button("💬 댓글 수집 & 기획 분석", type="secondary",
                     use_container_width=True, key="trend_comment_btn"):
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

    # AI 댓글 분석 및 기획
    comment_box = st.empty()
    top30 = sorted(comments, key=lambda c: c["like_count"], reverse=True)[:30]
    comment_lines = [f'[좋아요 {c["like_count"]}] {c["text"]}' for c in top30]

    prompt = f"""\
## 분석 채널: "{sel_video["_channel"]}"
## 분석 영상: "{sel_video["title"]}"

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
- **차별화 포인트**: 경쟁 영상과 다른 점
- **예상 반응**: 왜 이 기획이 시청자에게 먹힐 것인가

### 3. 영상 도입부 훅(Hook) 문장 3개
댓글에서 발견한 시청자 언어를 활용한 도입부 멘트\
"""
    runner = AIRunner(tab_key="trend_comment_ai", system=COMMENT_SYSTEM, max_tokens=3000)
    runner.execute(prompt, comment_box, preferred="gemini-2.0-flash")


# ──────────────────────────────────────────────
# 메인 렌더
# ──────────────────────────────────────────────

def render_trend_planner():
    st.subheader("📡 트렌드 기획")
    st.caption(f"경쟁채널의 최근 {TREND_DAYS}일 업로드를 분석해 지금 올리면 좋을 영상을 추천합니다.")

    if st.button("📂 최근 기록", key="trend_hist"):
        _history_dialog()

    yt_key = st.session_state.get("youtube_api_key", "")
    if not yt_key:
        st.error("❌ 사이드바에서 YouTube API 키를 먼저 입력하세요.")
        return

    handler  = YouTubeAPIHandler(api_key=yt_key)
    profiles = list_profiles()

    # ── 상단: 채널 선택 바 ──────────────────────
    sel_col, add_col, del_col = st.columns([5, 1, 1])

    with sel_col:
        if not profiles:
            st.info("채널 정보가 없습니다. 오른쪽 [+ 채널 추가] 버튼을 눌러 추가하세요.")
            selected_profile = None
            chosen_id = None
        else:
            options   = {p["title"]: p["channel_id"] for p in profiles}
            chosen_title = st.selectbox(
                "내 채널 선택",
                list(options.keys()),
                label_visibility="collapsed",
            )
            chosen_id        = options[chosen_title]
            selected_profile = load_profile(chosen_id)

    with add_col:
        if st.button("➕ 채널 추가", use_container_width=True):
            _add_profile_dialog(handler)

    with del_col:
        if profiles and chosen_id:
            if st.button("🗑️ 삭제", use_container_width=True):
                delete_profile(chosen_id)
                # 삭제된 채널의 캐시 정리
                st.session_state.pop(f"trend_data_{chosen_id}", None)
                st.rerun()

    # 선택 채널 요약 정보
    if selected_profile:
        ch        = selected_profile["my_channel"]
        comp_list = selected_profile["competitors"]
        info_cols = st.columns([1, 9])
        with info_cols[0]:
            if ch.get("thumbnail"):
                st.image(ch["thumbnail"], width=36)
        with info_cols[1]:
            comp_names = " · ".join(c["title"] for c in comp_list)
            st.caption(f"경쟁채널 {len(comp_list)}개: {comp_names}")

    st.divider()

    if not selected_profile:
        return

    comp_list = selected_profile["competitors"]
    if not comp_list:
        st.warning("등록된 경쟁채널이 없습니다. 채널을 삭제 후 다시 추가하세요.")
        return

    my_title = selected_profile["my_channel"]["title"]
    cache_key = f"trend_data_{chosen_id}"

    # ── 분석 실행 버튼 ────────────────────────────
    run = st.button(
        f"🔍 최근 {TREND_DAYS}일 트렌드 분석 시작",
        type="primary",
        use_container_width=True,
    )

    if run:
        # 영상 수집
        comp_data = []
        prog = st.progress(0, text="경쟁채널 수집 중...")

        for i, comp in enumerate(comp_list):
            prog.progress((i + 1) / len(comp_list), text=f"수집 중: {comp['title']}")
            try:
                ch_info = handler.get_channel_info(comp["channel_id"])
                if not ch_info:
                    continue
                recent_videos = _fetch_recent_videos(handler, ch_info)
                if not recent_videos:
                    continue
                stats     = handler.get_video_stats([v["video_id"] for v in recent_videos])
                stats_map = {s["video_id"]: s for s in stats}
                for v in recent_videos:
                    s = stats_map.get(v["video_id"], {})
                    v["view_count"]    = s.get("view_count", 0)
                    v["comment_count"] = s.get("comment_count", 0)
                    v["tags"]          = s.get("tags", [])
                comp_data.append({"title": comp["title"], "videos": recent_videos})
            except RuntimeError as e:
                st.warning(f"{comp['title']} 수집 실패: {e}")

        prog.empty()

        if not comp_data:
            st.warning(f"최근 {TREND_DAYS}일 내 업로드된 경쟁채널 영상이 없습니다.")
            return

        summary_text, df = _build_trend_summary(comp_data)
        total_videos = sum(len(c["videos"]) for c in comp_data)

        # session_state에 저장 (AI 출력은 나중에 저장)
        st.session_state[cache_key] = {
            "comp_data":    comp_data,
            "df_records":   df.to_dict("records"),
            "summary_text": summary_text,
            "my_title":     my_title,
            "total_videos": total_videos,
            "ai_output":    None,  # 첫 실행 시 None → AI 재실행
        }

    # ── 결과 표시 (세션 캐시 기반) ──────────────
    cached = st.session_state.get(cache_key)
    if not cached:
        return

    total_videos = cached["total_videos"]
    comp_data    = cached["comp_data"]
    summary_text = cached["summary_text"]

    st.success(f"✅ {len(comp_data)}개 채널, {total_videos}개 영상 수집 완료")

    df = pd.DataFrame(cached["df_records"])
    with st.expander("📋 수집된 영상 목록 (조회 속도 높은 순)", expanded=False):
        disp = df[["channel", "title", "published_at", "view_count", "velocity", "patterns"]].copy()
        disp.columns = ["채널", "제목", "업로드일", "조회수", "속도(회/h)", "패턴"]
        st.dataframe(disp, use_container_width=True, hide_index=True)

    # ── AI 추천 ──────────────────────────────────
    st.divider()
    st.markdown("### 🤖 AI 트렌드 분석 & 영상 추천")
    gemini_key  = st.session_state.get("gemini_api_key", "")
    model_label = "gemini-2.0-flash" if gemini_key else "claude-sonnet-4-6"
    st.caption(f"분석 모델: `{model_label}`")

    if cached.get("ai_output") is None:
        output_box  = st.empty()
        prompt      = _build_trend_prompt(cached["my_title"], summary_text)
        full_output = _run_ai(TAB, prompt, output_box)

        if full_output is None:
            return  # 승인 대기 중

        if full_output:
            cached["ai_output"] = full_output
            st.session_state[cache_key] = cached

            safe_date = datetime.now().strftime("%Y%m%d")
            st.download_button(
                label="📥 트렌드 리포트 다운로드 (.txt)",
                data=full_output,
                file_name=f"트렌드리포트_{safe_date}.txt",
                mime="text/plain",
                use_container_width=True,
            )
            hist.save_result(TAB, f"{my_title} ({safe_date})", {
                "my_channel":       my_title,
                "competitor_count": len(comp_list),
                "videos_analyzed":  total_videos,
                "output":           full_output,
            })
    else:
        st.markdown(cached["ai_output"])
        safe_date = datetime.now().strftime("%Y%m%d")
        st.download_button(
            label="📥 트렌드 리포트 다운로드 (.txt)",
            data=cached["ai_output"],
            file_name=f"트렌드리포트_{safe_date}.txt",
            mime="text/plain",
            use_container_width=True,
        )

    # ── 댓글 분석 및 기획 ───────────────────────
    _render_comment_section(handler, cached)
