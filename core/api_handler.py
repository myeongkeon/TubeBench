"""
YouTube Data API v3 연동 및 로컬 JSON 캐싱 모듈

설계 원칙:
- API 할당량(10,000 units/일) 절약을 위해 TTL 기반 파일 캐싱 적용
- search.list(100 units) 대신 playlistItems.list(1 unit) 사용
- LLM 전달량 최소화를 위해 필요 필드만 추출
"""

import json
import hashlib
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

# ──────────────────────────────────────────────
# 상수 설정
# ──────────────────────────────────────────────
CACHE_DIR = Path(__file__).parent.parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

CACHE_TTL_SECONDS = 3600       # 캐시 유효 시간: 1시간
YOUTUBE_API_SERVICE = "youtube"
YOUTUBE_API_VERSION = "v3"
MAX_TAGS_PER_VIDEO = 10        # LLM 전달량 제한
MAX_DESCRIPTION_CHARS = 200    # 영상 설명 최대 길이


class YouTubeAPIHandler:
    """
    YouTube Data API v3 클라이언트 with 로컬 JSON 캐싱.

    사용 예:
        handler = YouTubeAPIHandler()
        channel = handler.get_channel_info("UCxxxxxx")
        videos  = handler.get_channel_videos(channel["uploads_playlist_id"])
        stats   = handler.get_video_stats([v["video_id"] for v in videos])
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "YOUTUBE_API_KEY가 설정되지 않았습니다.\n"
                ".env 파일에 YOUTUBE_API_KEY=<키값> 을 추가하세요."
            )
        self._client = None  # 첫 호출 시 초기화 (Lazy init)

    # ──────────────────────────────────────────────
    # API 클라이언트
    # ──────────────────────────────────────────────

    @property
    def client(self):
        """API 클라이언트 Lazy 초기화 - 불필요한 연결 비용 방지"""
        if self._client is None:
            self._client = build(
                YOUTUBE_API_SERVICE,
                YOUTUBE_API_VERSION,
                developerKey=self.api_key,
                cache_discovery=False,  # 파일시스템 캐시 경고 억제
            )
        return self._client

    # ──────────────────────────────────────────────
    # 캐시 유틸리티
    # ──────────────────────────────────────────────

    def _cache_key(self, **params) -> str:
        """요청 파라미터 → MD5 해시 키 (캐시 파일명에 사용)"""
        raw = json.dumps(params, sort_keys=True)
        return hashlib.md5(raw.encode()).hexdigest()

    def _load_cache(self, key: str) -> Optional[dict | list]:
        """캐시 로드. 파일 없거나 TTL 초과 시 None 반환"""
        path = CACHE_DIR / f"{key}.json"
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        if time.time() - cached["timestamp"] > CACHE_TTL_SECONDS:
            return None  # 만료
        return cached["data"]

    def _save_cache(self, key: str, data: dict | list) -> None:
        """데이터를 타임스탬프와 함께 JSON 캐시로 저장"""
        path = CACHE_DIR / f"{key}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time(), "data": data}, f, ensure_ascii=False, indent=2)

    # ──────────────────────────────────────────────
    # 채널 ID 변환
    # ──────────────────────────────────────────────

    def resolve_channel_id(self, raw: str) -> str:
        """
        채널 핸들·URL·ID를 채널 ID(UC...)로 변환.
        Quota 비용: 캐시 미스 시 1 unit

        지원 형식:
          UCxxxxxx          → 그대로 반환
          @handle           → forHandle 조회
          youtube.com/@h    → forHandle 조회
          youtube.com/c/h   → forHandle 조회
          youtube.com/user/h→ forHandle 조회
        """
        raw = raw.strip().rstrip("/")

        # 이미 채널 ID
        if raw.startswith("UC") and " " not in raw:
            return raw

        # URL에서 핸들/경로 추출
        for prefix in ("https://www.youtube.com", "https://youtube.com",
                       "http://www.youtube.com", "http://youtube.com",
                       "www.youtube.com", "youtube.com"):
            if raw.startswith(prefix):
                raw = raw[len(prefix):].lstrip("/")
                break

        # /c/handle 또는 /user/handle → handle 부분만
        for seg in ("c/", "user/"):
            if raw.startswith(seg):
                raw = raw[len(seg):]
                break

        # @ 없으면 붙이기
        handle = raw if raw.startswith("@") else f"@{raw}"

        cache_key = self._cache_key(method="resolve_handle", handle=handle)
        if (cached := self._load_cache(cache_key)) is not None:
            return cached

        try:
            response = (
                self.client.channels()
                .list(part="id", forHandle=handle)
                .execute()
            )
        except HttpError as e:
            raise RuntimeError(f"핸들 변환 실패 ({handle}): {e}") from e

        items = response.get("items", [])
        if not items:
            raise RuntimeError(f"채널을 찾을 수 없습니다: {handle}")

        channel_id = items[0]["id"]
        self._save_cache(cache_key, channel_id)
        return channel_id

    # ──────────────────────────────────────────────
    # YouTube API 메서드
    # ──────────────────────────────────────────────

    def get_channel_info(self, channel_id: str) -> Optional[dict]:
        """
        채널 기본 정보 및 통계 조회.
        Quota 비용: 1 unit

        Returns:
            dict with keys: channel_id, title, description, subscriber_count,
                            view_count, video_count, uploads_playlist_id, thumbnail
        """
        cache_key = self._cache_key(method="channel_info", channel_id=channel_id)
        if (cached := self._load_cache(cache_key)) is not None:
            return cached

        try:
            response = (
                self.client.channels()
                .list(part="snippet,statistics,contentDetails", id=channel_id)
                .execute()
            )
        except HttpError as e:
            raise RuntimeError(f"채널 정보 조회 실패 (channel_id={channel_id}): {e}") from e

        if not response.get("items"):
            return None  # 존재하지 않는 채널

        item = response["items"][0]
        result = {
            "channel_id": channel_id,
            "title": item["snippet"]["title"],
            "description": item["snippet"]["description"][:500],
            "published_at": item["snippet"]["publishedAt"],
            "thumbnail": item["snippet"]["thumbnails"].get("default", {}).get("url", ""),
            "subscriber_count": int(item["statistics"].get("subscriberCount", 0)),
            "view_count": int(item["statistics"].get("viewCount", 0)),
            "video_count": int(item["statistics"].get("videoCount", 0)),
            # 업로드 재생목록 ID → get_channel_videos()에 전달
            "uploads_playlist_id": item["contentDetails"]["relatedPlaylists"]["uploads"],
        }
        self._save_cache(cache_key, result)
        return result

    def get_channel_videos(self, uploads_playlist_id: str, max_results: int = 50) -> list[dict]:
        """
        채널 업로드 재생목록에서 최근 영상 목록 조회.
        Quota 비용: 1 unit/page (search.list 100 units 대비 99% 절약)

        Args:
            uploads_playlist_id: get_channel_info()의 "uploads_playlist_id" 값
            max_results: 최대 조회 영상 수 (기본 50, 최대 500)

        Returns:
            list of dicts with keys: video_id, title, published_at, thumbnail, description
        """
        cache_key = self._cache_key(
            method="channel_videos",
            playlist_id=uploads_playlist_id,
            max_results=max_results,
        )
        if (cached := self._load_cache(cache_key)) is not None:
            return cached

        videos = []
        next_page_token = None

        try:
            while len(videos) < max_results:
                batch_size = min(50, max_results - len(videos))
                response = (
                    self.client.playlistItems()
                    .list(
                        part="snippet",
                        playlistId=uploads_playlist_id,
                        maxResults=batch_size,
                        pageToken=next_page_token,
                    )
                    .execute()
                )

                for item in response.get("items", []):
                    snippet = item["snippet"]
                    videos.append({
                        "video_id": snippet["resourceId"]["videoId"],
                        "title": snippet["title"],
                        "published_at": snippet["publishedAt"],
                        "thumbnail": snippet["thumbnails"].get("medium", {}).get("url", ""),
                        "description": snippet["description"][:MAX_DESCRIPTION_CHARS],
                    })

                next_page_token = response.get("nextPageToken")
                if not next_page_token:
                    break

        except HttpError as e:
            raise RuntimeError(f"영상 목록 조회 실패: {e}") from e

        self._save_cache(cache_key, videos)
        return videos

    def get_video_stats(self, video_ids: list[str]) -> list[dict]:
        """
        영상 상세 통계 일괄 조회 (조회수, 좋아요, 댓글수, 태그 등).
        Quota 비용: 1 unit / 50 videos

        Args:
            video_ids: 조회할 영상 ID 목록

        Returns:
            list of dicts with keys: video_id, title, published_at, duration,
                                     view_count, like_count, comment_count, tags
        """
        if not video_ids:
            return []

        cache_key = self._cache_key(method="video_stats", video_ids=sorted(video_ids))
        if (cached := self._load_cache(cache_key)) is not None:
            return cached

        all_stats = []
        try:
            # API는 한 번에 최대 50개 처리 → 배치 분할
            for i in range(0, len(video_ids), 50):
                batch = video_ids[i : i + 50]
                response = (
                    self.client.videos()
                    .list(
                        part="statistics,contentDetails,snippet",
                        id=",".join(batch),
                    )
                    .execute()
                )

                for item in response.get("items", []):
                    stats = item.get("statistics", {})
                    all_stats.append({
                        "video_id": item["id"],
                        "title": item["snippet"]["title"],
                        "published_at": item["snippet"]["publishedAt"],
                        "duration": item["contentDetails"]["duration"],  # ISO 8601 형식
                        "view_count": int(stats.get("viewCount", 0)),
                        "like_count": int(stats.get("likeCount", 0)),
                        "comment_count": int(stats.get("commentCount", 0)),
                        # LLM 전달량 제한: 태그 최대 10개만 보관
                        "tags": item["snippet"].get("tags", [])[:MAX_TAGS_PER_VIDEO],
                    })

        except HttpError as e:
            raise RuntimeError(f"영상 통계 조회 실패: {e}") from e

        self._save_cache(cache_key, all_stats)
        return all_stats

    def clear_expired_cache(self) -> int:
        """만료된 캐시 파일 삭제. 삭제된 파일 수 반환"""
        deleted = 0
        for cache_file in CACHE_DIR.glob("*.json"):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if time.time() - cached["timestamp"] > CACHE_TTL_SECONDS:
                    cache_file.unlink()
                    deleted += 1
            except (json.JSONDecodeError, KeyError):
                # 손상된 캐시 파일도 삭제
                cache_file.unlink()
                deleted += 1
        return deleted
