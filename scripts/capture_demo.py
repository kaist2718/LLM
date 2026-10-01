#!/usr/bin/env python3
"""스트리밍 생성 장면을 녹화해 README용 데모 GIF를 만든다.

모델 로딩 없이 UI의 스트리밍 동작을 보여주기 위해, 실제 index.html UI에
고정된 예시 답변을 토큰 단위로 스트리밍하는 모의 서버를 붙여 촬영한다.
(웹 UI 자체는 그대로이며, 백엔드만 예시 응답으로 대체한다.)

사용법:
    .venv\\Scripts\\python.exe scripts\\capture_demo.py          # 스트리밍 데모 -> docs/demo.gif
    .venv\\Scripts\\python.exe scripts\\capture_demo.py stop      # Esc 중단 데모 -> docs/demo-stop.gif

의존성: pip install websocket-client pillow
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

import websocket
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
WINDOW = (1440, 900)
GIF_WIDTH = 960
FRAME_INTERVAL = 0.55  # 초

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

# 모드별 촬영 설정 — stop 모드는 Esc 키로 생성을 중단하는 장면을 녹화한다.
MODES = {
    "stream": {
        "out": ROOT / "docs" / "demo.gif",
        "question": "이 앱의 장점 3가지만 알려 줘",
        "answer": ANSWER,
        "frames": 20,
        "stop_at": None,
    },
    "stop": {
        "out": ROOT / "docs" / "demo-stop.gif",
        "question": "인공지능의 미래에 대해 상세히 설명해 줘",
        "answer": ("인공지능의 미래는 밝습니다! 앞으로 3가지 흐름이 특히 주목받을 거예요.\n\n"
                   "**첫째, 개인화된 AI 비서입니다.** 모두의 일상에 맞춰 학습하는 비서가 보편화됩니다.\n\n"
                   "**둘째, 로컬 AI의 확산입니다.** 클라우드 없이도 기기에서 직접 추론하는 모델이 늘어납니다.\n\n"
                   "**셋째, 창작 도구와의 융합입니다.** 글쓰기·코딩·디자인 전반에 AI가 스며듭니다.\n\n"
                   "이러한 변화는 비용과 접근성을 크게 낮출 거예요. 추가로 궁금한 점이 있으면 말씀해 주세요!"),
        "frames": 16,
        "stop_at": 3.0,  # 초 — 이 시간에 Esc를 눌러 생성 중단
    },
}
CONFIG = MODES["stream"]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_mock_server(port):
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
            self.connection.settimeout(3)  # 클라이언트가 끊으면 쓰기가 오래 막히지 않도록
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
            answer = CONFIG["answer"]
            chunk_size = 2
            delay = 0.05
            try:
                for i in range(0, len(answer), chunk_size):
                    event = {"token": answer[i : i + chunk_size]}
                    self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(delay)
                done = {"done": True, "metrics": {"toks_per_s": 38.6, "elapsed_ms": 5100, "para": 6}}
                self.wfile.write(f"data: {json.dumps(done)}\n\n".encode())
                self.wfile.flush()
            except OSError:
                pass  # 클라이언트가 생성을 중단하고 연결을 끊음 (Esc 데모)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
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
        targets = json.loads(opener.open(f"http://127.0.0.1:{port}/json/list", timeout=3).read())
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
    global CONFIG
    CONFIG = MODES[sys.argv[1]] if len(sys.argv) > 1 else MODES["stream"]
    mock_port = free_port()  # 이전 실행의 잔여 프로세스와 충돌하지 않도록 매번 새 포트
    cdp_port = free_port()
    profile = ROOT / f".chrome-tmp-{os.getpid()}"  # 실행마다 고유 프로필 (락 충돌 방지)
    server = start_mock_server(mock_port)
    chrome = subprocess.Popen(
        [
            find_chrome(),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-proxy-server",
            f"--user-data-dir={profile}",
            f"--remote-debugging-port={cdp_port}",
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
        for _ in range(100):  # Chrome 냉기동 시 최대 30초 대기
            try:
                cdp = CDP(cdp_port)
                break
            except Exception as e:
                last_err = e
                time.sleep(0.3)
        if cdp is None:
            raise SystemExit(f"Chrome CDP 연결 실패: {last_err}")

        cdp.call("Page.enable")
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{mock_port}/"})
        for _ in range(50):
            state = cdp.evaluate("document.readyState")["result"].get("value")
            if state == "complete":
                break
            time.sleep(0.2)
        time.sleep(1.0)  # 초기 렌더 안정화

        # 질문 전송 (스트리밍 시작) 후 프레임 수집
        cdp.evaluate(f'submitUser({json.dumps(CONFIG["question"], ensure_ascii=False)})')
        pngs = []
        frames_n = CONFIG["frames"]
        for i in range(frames_n):
            pngs.append(cdp.screenshot_png())
            text_len = cdp.evaluate("document.body.innerText.length")["result"].get("value")
            print(f"프레임 {i + 1}/{frames_n} (화면 텍스트 {text_len}자)")
            if CONFIG["stop_at"] is not None and (i + 1) * FRAME_INTERVAL >= CONFIG["stop_at"] and len(pngs) == i + 1:
                # Esc 키 눌러 생성 중단 (한 번만)
                cdp.evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
                CONFIG["stop_at"] = None
                print("Esc 전송 — 생성 중단")
            time.sleep(FRAME_INTERVAL)
        cdp.close()

        frames = [Image.open(BytesIO(p)).convert("RGB") for p in pngs]
        height = int(frames[0].height * GIF_WIDTH / frames[0].width)
        frames = [f.resize((GIF_WIDTH, height), Image.LANCZOS) for f in frames]
        CONFIG["out"].parent.mkdir(parents=True, exist_ok=True)
        out = CONFIG["out"]
        frames[0].save(
            out,
            save_all=True,
            append_images=frames[1:],
            duration=int(FRAME_INTERVAL * 1000),
            loop=0,
            optimize=True,
        )
        with Image.open(out) as gif:
            print(f"저장: {out} ({gif.n_frames}프레임, {out.stat().st_size // 1024}KB)")
    finally:
        # 프로세스 트리 전체 종료 (자식 Chrome이 프로필을 잠그지 않도록)
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(chrome.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    main()
