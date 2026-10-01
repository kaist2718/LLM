"""Qwen3.5-9B 사전 양자화(bnb 4bit) 가중치 다운로드 스크립트 (hf_transfer 가속).

기본 대상: rectx/Qwen3.5-9B-bnb-4bit (약 7.6GB) — 로드 시 재양자화 없이 바로 사용.
전체 가중치(약 18GB)가 필요하면 QWEN35_MODEL_ID=Qwen/Qwen3.5-9B 를 지정하세요.
"""
import os
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")

try:
    import hf_transfer  # noqa: F401
except ImportError:
    print("[dl] 경고: hf_transfer 미설치 — 'uv pip install hf_transfer' 후 다시 실행하면 빨라집니다", flush=True)

from huggingface_hub import snapshot_download

REPO = os.environ.get("QWEN35_MODEL_ID", "rectx/Qwen3.5-9B-bnb-4bit")
print(f"[dl] START: {REPO}", flush=True)
path = snapshot_download(REPO)
print(f"[dl] DONE: {path}", flush=True)
