"""
채널 프로필 관리 모듈

내 채널 + 경쟁채널 목록을 profiles/{channel_id}.json 에 저장·로드.
"""

import json
from pathlib import Path
from typing import Optional

PROFILES_DIR = Path(__file__).parent.parent / "profiles"
PROFILES_DIR.mkdir(exist_ok=True)


def _profile_path(channel_id: str) -> Path:
    return PROFILES_DIR / f"{channel_id}.json"


def save_profile(my_channel: dict, competitors: list[dict]) -> None:
    """
    my_channel: {channel_id, title, thumbnail}
    competitors: [{channel_id, title, thumbnail}, ...]
    """
    data = {
        "my_channel":  my_channel,
        "competitors": competitors,
    }
    path = _profile_path(my_channel["channel_id"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_profile(channel_id: str) -> Optional[dict]:
    path = _profile_path(channel_id)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_profiles() -> list[dict]:
    """저장된 모든 프로필의 my_channel 정보 반환"""
    profiles = []
    for p in PROFILES_DIR.glob("*.json"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            profiles.append(data["my_channel"])
        except (json.JSONDecodeError, KeyError):
            continue
    return profiles


def delete_profile(channel_id: str) -> bool:
    path = _profile_path(channel_id)
    if path.exists():
        path.unlink()
        return True
    return False
