#!/usr/bin/env python3
"""스트리밍 생성 장면을 녹화해 README용 데모 GIF를 만든다.

모델 로딩 없이 UI의 스트리밍 동작을 보여주기 위해, 실제 index.html UI에
고정된 예시 답변을 토큰 단위로 스트리밍하는 모의 서버를 붙여 촬영한다.
(웹 UI 자체는 그대로이며, 백엔드만 예시 응답으로 대체한다.)

사용법:
    .venv\\Scripts\\python.exe scripts\\capture_demo.py

결과: docs/demo.gif
의존성: pip install websocket-client pillow
"""
import base64
import json
import shutil
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from pathlib import Path

import websocket
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "demo.gif"
CHROME_PROFILE = ROOT / ".chrome-tmp"
MOCK_PORT = 5056
CDP_PORT = 9333
WINDOW = (1440, 900)
GIF_WIDTH = 960
FRAMES = 20
FRAME_INTERVAL = 0.55  # 초

QUESTION = "이 앱의 장점 3가지만 알려 줘"

ANSWER = (
    "좋은 질문이에요! **Qwen3.5-9B 로컬 채팅**의 장점은 크게 세 가지입니다.\n\n"
    "### 1. 완전한 프라이버시\n\n"
    "질문과 문서가 내 PC를 떠나지 않아요. 회사 보고서나 개인 기록도 안심하고 물어볼 수 있습니다.\n\n"
    "### 2. 비용 ZERO\n\n"
    "API 사용료 없이 전기요금만으로 무제한 대화가 가능합니다.\n\n"
    "### 3. 빠른 응답\n\n"
    "4bit 양자화 덕분에 12GB VRAM에서도 토큰이 스트리밍으로 바로바로 나옵니다.\n\n"
    "더 궁금한 점이 있으면 말씀해 주세요! 😊"
)


def start_mock_server():
    """index.html를 그대로 서빙하고 /api/chat만 예시 스트리밍으로 응답하는 모의 서버."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, body: bytes, ctype: str):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                self._send((ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/questions":
                self._send(json.dumps({"questions": []}).encode(), "application/json")
            elif path == "/api/results":
                self._send(json.dumps({"sets": []}).encode(), "application/json")
            elif path == "/api/status":
                self._send(
                    json.dumps({"loaded": True, "loading": False, "background_loading": False}).encode(),
                    "application/json",
                )
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            if self.path != "/api/chat":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            chunk_size = 2
            delay = 0.05
            for i in range(0, len(ANSWER), chunk_size):
                event = {"token": ANSWER[i : i + chunk_size]}
                self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
                time.sleep(delay)
            done = {"done": True, "metrics": {"toks_per_s": 38.6, "elapsed_ms": 5100, "para": 6}}
            self.wfile.write(f"data: {json.dumps(done)}\n\n".encode())
            self.wfile.flush()

    server = HTTPServer(("127.0.0.1", MOCK_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def find_chrome():
    for path in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ):
        if Path(path).exists():
            return path
    raise SystemExit("Chrome을 찾을 수 없습니다")


class CDP:
    """크롬 디버깅 프로토콜 최소 클라이언트 (Page.navigate / Runtime.evaluate / 스크린샷)."""

    def __init__(self, port):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        targets = json.loads(opener.open(f"http://127.0.0.1:{port}/json/list").read())
        page = next(t for t in targets if t.get("type") == "page")
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=60, http_proxy_host=None)
        self._id = 0

    def call(self, method, params=None):
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def evaluate(self, expr, await_promise=False):
        return self.call(
            "Runtime.evaluate",
            {"expression": expr, "awaitPromise": await_promise, "returnByValue": True},
        )

    def screenshot_png(self):
        data = self.call("Page.captureScreenshot", {"format": "png"})
        return base64.b64decode(data["data"])

    def close(self):
        self.ws.close()


def main():
    server = start_mock_server()
    chrome = subprocess.Popen(
        [
            find_chrome(),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-proxy-server",
            f"--user-data-dir={CHROME_PROFILE}",
            f"--remote-debugging-port={CDP_PORT}",
            "--remote-allow-origins=*",
            f"--window-size={WINDOW[0]},{WINDOW[1]}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        cdp = None
        last_err = None
        for _ in range(50):
            try:
                cdp = CDP(CDP_PORT)
                break
            except Exception as e:
                last_err = e
                time.sleep(0.3)
        if cdp is None:
            raise SystemExit(f"Chrome CDP 연결 실패: {last_err}")

        cdp.call("Page.enable")
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{MOCK_PORT}/"})
        for _ in range(50):
            state = cdp.evaluate("document.readyState")["result"].get("value")
            if state == "complete":
                break
            time.sleep(0.2)
        time.sleep(1.0)  # 초기 렌더 안정화

        # 질문 전송 (스트리밍 시작) 후 프레임 수집
        cdp.evaluate(f'submitUser({json.dumps(QUESTION, ensure_ascii=False)})')
        pngs = []
        for i in range(FRAMES):
            pngs.append(cdp.screenshot_png())
            print(f"프레임 {i + 1}/{FRAMES}")
            time.sleep(FRAME_INTERVAL)
        cdp.close()

        frames = [Image.open(BytesIO(p)).convert("RGB") for p in pngs]
        height = int(frames[0].height * GIF_WIDTH / frames[0].width)
        frames = [f.resize((GIF_WIDTH, height), Image.LANCZOS) for f in frames]
        OUT.parent.mkdir(parents=True, exist_ok=True)
        frames[0].save(
            OUT,
            save_all=True,
            append_images=frames[1:],
            duration=int(FRAME_INTERVAL * 1000),
            loop=0,
            optimize=True,
        )
        with Image.open(OUT) as gif:
            print(f"저장: {OUT} ({gif.n_frames}프레임, {OUT.stat().st_size // 1024}KB)")
    finally:
        chrome.terminate()
        try:
            chrome.wait(timeout=10)
        except subprocess.TimeoutExpired:
            chrome.kill()
        server.shutdown()
        shutil.rmtree(CHROME_PROFILE, ignore_errors=True)


if __name__ == "__main__":
    main()
