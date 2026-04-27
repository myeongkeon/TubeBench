#!/usr/bin/env python3
"""
YouTube Strategy Hub - 실행기
실행: python main.py
"""

import os
import sys
import shutil
import subprocess
import threading
import time
import webbrowser

PORT = 8501
HOST = "127.0.0.1"
URL  = f"http://{HOST}:{PORT}"
DIR  = os.path.dirname(os.path.abspath(__file__))


def _open_browser():
    time.sleep(2.5)
    chrome_paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for path in chrome_paths:
        if os.path.exists(path):
            subprocess.Popen([path, "--incognito", URL])
            return
    webbrowser.open(URL)


def _find_uv():
    # 일반 PATH 검색
    uv = shutil.which("uv")
    if uv:
        return uv
    # Homebrew 설치 경로 (macOS)
    for candidate in ["/opt/homebrew/bin/uv", "/usr/local/bin/uv", "~/.cargo/bin/uv"]:
        path = os.path.expanduser(candidate)
        if os.path.isfile(path):
            return path
    return None


def main():
    os.chdir(DIR)
    sys.path.insert(0, DIR)

    print()
    print("=" * 52)
    print("   📊  YouTube Strategy Hub")
    print(f"   🌐  {URL}")
    print("   ⏹   종료하려면 Ctrl+C 를 누르세요")
    print("=" * 52)
    print()

    # 브라우저 자동 열기 (별도 스레드)
    t = threading.Thread(target=_open_browser, daemon=True)
    t.start()

    # ── 1순위: uvicorn을 직접 import (현재 Python 환경에 설치된 경우)
    try:
        import uvicorn
        uvicorn.run("server:app", host=HOST, port=PORT, reload=False, log_level="warning")
        return
    except ImportError:
        pass

    # ── 2순위: uv run 사용
    uv = _find_uv()
    if uv:
        cmd = [uv, "run", "uvicorn", "server:app",
               "--host", HOST, "--port", str(PORT),
               "--log-level", "warning"]
        try:
            subprocess.run(cmd, cwd=DIR, check=True)
            return
        except subprocess.CalledProcessError:
            pass

    # ── 3순위: python -m uvicorn
    cmd = [sys.executable, "-m", "uvicorn", "server:app",
           "--host", HOST, "--port", str(PORT)]
    try:
        subprocess.run(cmd, cwd=DIR, check=True)
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    print()
    print("❌ 서버를 시작할 수 없습니다.")
    print("   터미널에서 다음 명령어를 실행하세요:")
    print(f"   cd {DIR}")
    print("   uv run uvicorn server:app --port 8501")
    sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 YouTube Strategy Hub 종료")
