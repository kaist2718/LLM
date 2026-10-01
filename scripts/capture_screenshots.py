#!/usr/bin/env python3
"""로컬 서버를 띄워 README용 UI 스크린샷을 촬영한다.

사용법:
    .venv\\Scripts\\python.exe scripts\\capture_screenshots.py

결과: docs/screenshots/{chat,question-bank,score-sheet}.png
(채점표는 results/legacy/의 채점표 HTML이 있으면 함께 촬영한다.)
"""
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"
PORT = 5055
BASE = f"http://127.0.0.1:{PORT}"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
CHROME_PROFILE = ROOT / ".chrome-tmp"  # 헤드리스 전용 프로필 (기존 Chrome 인스턴스와 충돌 방지)


def find_chrome():
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    raise SystemExit("Chrome을 찾을 수 없습니다 (헤드리스 스크린샷용)")


def shot(chrome, url, out, width=1600, height=1000):
    # 참고: --virtual-time-budget은 페이지 로드 후 스크린샷 저장을 건너뛰는 경우가 있어
    #       사용하지 않는다. --no-proxy-server 없이는 로컬 서버가 프록시로 우회될 수 있다.
    result = subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-proxy-server",
            f"--user-data-dir={CHROME_PROFILE}",
            f"--window-size={width},{height}",
            f"--screenshot={out}",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not Path(out).exists():
        raise SystemExit(f"스크린샷 저장 실패 (exit {result.returncode}): {url}")
    print(f"저장: {out}")


def main():
    chrome = find_chrome()
    SHOTS.mkdir(parents=True, exist_ok=True)

    env = {
        **os.environ,
        "APP_PRELOAD": "0",  # 모델 로딩 없이 UI만 촬영
        "APP_BROWSER": "0",
        "APP_PORT": str(PORT),
        "PYTHONUTF8": "1",
    }
    server = subprocess.Popen(
        [sys.executable, str(ROOT / "app.py")],
        env=env,
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(BASE + "/", timeout=1)
                break
            except Exception:
                time.sleep(1)
        else:
            raise SystemExit("서버가 뜨지 않았습니다")

        shot(chrome, BASE + "/", SHOTS / "chat.png")
        shot(chrome, BASE + "/?panel=qbank", SHOTS / "question-bank.png")

        legacy = sorted((ROOT / "results" / "legacy").glob("score_sheet_*.html"))
        if legacy:
            shot(chrome, legacy[-1].resolve().as_uri(), SHOTS / "score-sheet.png")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(CHROME_PROFILE, ignore_errors=True)
    print("스크린샷 촬영 완료")


if __name__ == "__main__":
    main()
