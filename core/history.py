"""
실행 결과 히스토리 저장·로드 모듈

저장 위치: history/{tab}/{YYYYMMDD_HHMMSS}.json
최대 보관: 탭당 50건 (초과 시 오래된 것부터 삭제)
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

HISTORY_DIR = Path(__file__).parent.parent / "history"
HISTORY_DIR.mkdir(exist_ok=True)
MAX_PER_TAB = 50


# ──────────────────────────────────────────────
# 저장 / 로드
# ──────────────────────────────────────────────

def save_result(tab: str, label: str, data: dict) -> str:
    """결과를 JSON으로 저장. 반환값: 파일명"""
    tab_dir = HISTORY_DIR / tab
    tab_dir.mkdir(exist_ok=True)

    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{ts}.json"
    payload  = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "label":     label,
        "tab":       tab,
        "data":      data,
    }
    with open(tab_dir / filename, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    _prune(tab_dir)
    return filename


def list_results(tab: str, limit: int = 30) -> list[dict]:
    """최신 순으로 최대 limit개 반환. 각 항목: {filename, timestamp, label}"""
    tab_dir = HISTORY_DIR / tab
    if not tab_dir.exists():
        return []
    files = sorted(tab_dir.glob("*.json"), reverse=True)[:limit]
    out   = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fp:
                meta = json.load(fp)
            out.append({
                "filename":  f.name,
                "timestamp": meta.get("timestamp", f.stem),
                "label":     meta.get("label", "-"),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return out


def load_result(tab: str, filename: str) -> Optional[dict]:
    path = HISTORY_DIR / tab / filename
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _prune(tab_dir: Path) -> None:
    files = sorted(tab_dir.glob("*.json"), reverse=True)
    for old in files[MAX_PER_TAB:]:
        old.unlink(missing_ok=True)
