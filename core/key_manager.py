import os
import time
from threading import Lock
from dotenv import load_dotenv

load_dotenv()


class KeyPool:
    def __init__(self, keys: list, rate_ttl: int = 60, quota_ttl: int = 86400):
        self.keys = list(keys)
        self._rate_ttl = rate_ttl
        self._quota_ttl = quota_ttl
        self._errors: dict = {}
        self._lock = Lock()

    def get(self):
        with self._lock:
            now = time.time()
            for key in self.keys:
                err = self._errors.get(key)
                if err is None:
                    return key
                ttl = self._quota_ttl if err["type"] == "quota" else self._rate_ttl
                if now - err["ts"] >= ttl:
                    del self._errors[key]
                    return key
            return None

    def mark_error(self, key: str, error_type: str = "quota"):
        with self._lock:
            self._errors[key] = {"type": error_type, "ts": time.time()}

    def reset(self):
        with self._lock:
            self._errors.clear()

    def min_rate_wait(self) -> float | None:
        """Returns minimum seconds until any rate-limited key recovers. None if no such keys."""
        now = time.time()
        with self._lock:
            waits = [
                self._rate_ttl - (now - err["ts"])
                for key, err in self._errors.items()
                if err["type"] == "rate_limit" and (self._rate_ttl - (now - err["ts"])) > 0
            ]
            return min(waits) if waits else None

    def size(self) -> int:
        return len(self.keys)

    def status(self) -> list:
        now = time.time()
        result = []
        with self._lock:
            for key in self.keys:
                err = self._errors.get(key)
                if err is None:
                    result.append({"masked": _mask(key), "status": "active", "resets_in": None})
                else:
                    ttl = self._quota_ttl if err["type"] == "quota" else self._rate_ttl
                    remaining = max(0, ttl - (now - err["ts"]))
                    if remaining <= 0:
                        result.append({"masked": _mask(key), "status": "active", "resets_in": None})
                    else:
                        result.append({
                            "masked":    _mask(key),
                            "status":    err["type"],
                            "resets_in": int(remaining),
                        })
        return result


def _mask(key: str) -> str:
    if len(key) <= 8:
        return "****"
    return key[:6] + "..." + key[-4:]


def _parse(env_var: str, fallback: str = None) -> list:
    raw = os.getenv(env_var, "")
    if not raw and fallback:
        raw = os.getenv(fallback, "")
    return [k.strip() for k in raw.split(",") if k.strip()]


youtube   = KeyPool(_parse("YOUTUBE_API_KEYS",   "YOUTUBE_API_KEY"),   rate_ttl=300,  quota_ttl=86400)
gemini    = KeyPool(_parse("GEMINI_API_KEYS",    "GEMINI_API_KEY"),    rate_ttl=60,   quota_ttl=86400)
anthropic = KeyPool(_parse("ANTHROPIC_API_KEYS", "ANTHROPIC_API_KEY"), rate_ttl=60,   quota_ttl=86400)
