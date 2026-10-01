r"""
app.py — Qwen3.5-9B 전용 채팅 서버 (Flask)

Qwen3.5-9B(사전 양자화 bnb 4bit 기본)를 서버 시작 시 백그라운드로 로드해 SSE 스트리밍.
PDF/엑셀 문서 첨부 질의 지원.

실행:  .venv\Scripts\python.exe app.py
브라우저:  http://127.0.0.1:5000
"""
import atexit
import json
import math
import os
import re
import shutil
import tempfile
import time
import uuid
import webbrowser
from threading import Thread, Lock, Event

import torch
from flask import Flask, Response, request, jsonify, send_file

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
torch.manual_seed(0)

# -- 모델 설정 (Qwen3.5-9B 전용) --
MODEL_KEY = "qwen35"
MODELS = {
    "qwen35": {
        "name": "Qwen3.5-9B",
        "avatar": "🔷",
        # 사전 양자화(bnb NF4) — 재양자화 없이 바로 로드. 전체 가중치는 QWEN35_MODEL_ID=Qwen/Qwen3.5-9B
        "model_id": "rectx/Qwen3.5-9B-bnb-4bit",
        "system": (
            "당신은 유용하고 정직한 AI 어시스턴트입니다.\n"
            "- 사용자가 다른 언어로 답하라고 요청하지 않는 한 모든 답변을 한국어(한글)로 작성합니다.\n"
            "- 존댓말을 사용하되, 간결하고 논리적으로 설명합니다.\n"
            "- 질문의 의도를 정확히 파악해 명확하고 실용적인 답변을 제공하되, "
            "확실하지 않은 내용은 추측하지 않고, 불확실하면 그 사실을 밝힙니다.\n"
            "- 어려운 내용은 일상 언어로 쉽게 풀어 설명하고, 필요한 경우에만 전문 용어를 씁니다.\n"
            "- 사용자의 맥락과 목적에 맞춰 실용적인 관점을 제시합니다.\n"
            "- 사실을 인용할 때는 출처를 밝히고, 기억이 불확실하면 지어내지 않습니다.\n"
            "- 의료·법률 등 전문 분야는 일반적인 정보를 제공하되 전문가 상담을 권합니다."
        ),
    },
}

_bundle = None      # {"model": ..., "tokenizer": ...} — 로드된 Qwen3.5-9B
_lock = Lock()      # GPU 모델 로드·전처리·추론 전체 직렬화 락
_load_lock = Lock() # 모델 로딩 동기화 락 (중복 로딩 방지)


def _load_model():
    """Qwen3.5-9B를 로드하여 반환. 이미 있으면 재사용."""
    global _bundle
    if _bundle is not None:
        return _bundle

    info = MODELS[MODEL_KEY]
    # 우선순위: models/qwen35 로컬 폴더 > QWEN35_MODEL_ID 환경변수 > 사전 양자화 모델
    model_id = os.environ.get("QWEN35_MODEL_ID") or info["model_id"]

    # 로컬 저장소 확인 (models/qwen35 폴더에 이미 다운로드된 경우)
    local_path = os.path.join(os.path.dirname(__file__), "models", MODEL_KEY)
    if os.path.isdir(local_path):
        model_id = local_path
        print(f"[server] using local model: {local_path}")
    else:
        print(f"[server] loading: {info['name']} ({model_id}) ...")

    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    t0 = time.perf_counter()
    tok = AutoTokenizer.from_pretrained(model_id)

    if DEVICE == "cuda":
        quant_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            quantization_config=quant_config,
            device_map={"": DEVICE},
            low_cpu_mem_usage=True,
        )
    else:
        model = AutoModelForCausalLM.from_pretrained(
            model_id, dtype=torch.bfloat16, device_map={"": DEVICE},
            low_cpu_mem_usage=True,
        )
    model.eval()
    _bundle = {"model": model, "tokenizer": tok}
    tag = "4bit" if DEVICE == "cuda" else "bf16"
    load_s = time.perf_counter() - t0
    print(f"[server] loaded: {info['name']} ({tag}, {load_s:.1f}s)")
    return _bundle


def get_model():
    """이미 로드된 모델이면 즉시 반환. 없으면 로딩 락으로 중복 로딩 방지."""
    if _bundle is not None:
        return _bundle
    with _load_lock:
        return _load_model()  # double-check: 락 대기 중 다른 스레드가 로딩 완료 가능


_load_status = {"loading": False, "error": None}


def _background_preload():
    """서버 시작과 동시에 모델을 백그라운드로 올려 첫 질문 대기 시간을 없앤다."""
    if _bundle is not None:
        return
    _load_status["loading"] = True
    print("[server] background preload started ...")
    try:
        get_model()
        print("[server] background preload finished")
    except Exception as e:
        _load_status["error"] = str(e)
        print(f"[server] background preload failed: {e}")
    finally:
        _load_status["loading"] = False


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 55 * 1024 * 1024  # 개별 파일 상한(50MB)+multipart 여유분


def _join_generation(thread):
    """스트림이 중단되어도 GPU 락을 놓기 전에 실제 추론 스레드가 끝나길 기다린다."""
    if thread is not None:
        thread.join()


def _serialize_gpu_stream(iterable):
    """모델 로드·전처리·추론을 하나의 GPU 세션으로 직렬화한다."""
    def stream():
        with _lock:
            yield from iterable
    return stream()


def _safe_generate(model, **gen_kwargs):
    """model.generate 를 별도 스레드에서 실행하되, 예외를 streamer 로 전달.

    TextIteratorStreamer 기반 스트리밍에서 generate 스레드가 예외로 죽으면
    streamer 가 종료되지 않아 메인 루프(for piece in streamer)가 무한 대기하며
    GPU 추론 락(_lock)을 영원히 점유하는 교착이 발생한다.
    이 래퍼는 예외 발생 시 streamer.end() 로 stop 신호를 밀어넣어 루프가 종료되게 한다.
    gen_kwargs 에는 'streamer' 키가 반드시 포함되어야 한다.
    """
    streamer = gen_kwargs.get("streamer")
    exc = {"err": None}

    def _run():
        try:
            model.generate(**gen_kwargs)
        except Exception as e:  # 스레드 예외는 메인으로 전파 불가 → streamer 로 신호
            import traceback
            traceback.print_exc()
            exc["err"] = str(e)
            if streamer is not None:
                try:
                    streamer.end()  # TextIteratorStreamer: stop_signal 을 큐에 push
                except Exception:
                    pass

    th = Thread(target=_run)
    th.daemon = True
    th.start()
    return th, exc


# -- 문서 업로드 저장소 (PDF/엑셀 → file_id 참조) --
MEDIA_DIR = tempfile.mkdtemp(prefix="qwen35_docs_")
_media_registry = {}  # {file_id: path}
_media_text = {}      # {file_id: 추출 텍스트} — 반복 추출 방지 캐시


def _cleanup_media():
    try:
        shutil.rmtree(MEDIA_DIR, ignore_errors=True)
    except Exception:
        pass
atexit.register(_cleanup_media)


print(f"[server] media dir: {MEDIA_DIR}  (max upload: 50MB per file)")


@app.route("/")
def index():
    return send_file(os.path.join(os.path.dirname(__file__), "index.html"))


# 브라우저 탭 파비콘 — 404 방지용 인라인 SVG (말풍선 💬)
_FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="14" fill="#3b6eff"/>'
    '<text x="32" y="44" font-size="38" text-anchor="middle">💬</text>'
    "</svg>"
)


@app.route("/favicon.ico")
def favicon():
    return Response(_FAVICON_SVG, mimetype="image/svg+xml")


def _extract_document_text(path_or_stream, ext):
    """PDF/엑셀에서 텍스트 추출. 실패 시 예외 발생."""
    if ext == ".pdf":
        import pymupdf
        doc = pymupdf.open(path_or_stream) if isinstance(path_or_stream, str) \
            else pymupdf.open(stream=path_or_stream.read(), filetype="pdf")
        try:
            return "\n".join(page.get_text() for page in doc)
        finally:
            doc.close()
    import pandas as pd
    df = pd.read_excel(path_or_stream, header=None)
    return df.to_string(index=False, header=False)


@app.route("/api/media", methods=["POST"])
def api_media_upload():
    """문서 파일 업로드 (multipart/form-data). file_id·추출 텍스트 반환."""
    if "file" not in request.files:
        return jsonify({"error": "file required"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "empty filename"}), 400

    ext = os.path.splitext(f.filename.lower())[1]
    document_exts = {".pdf", ".xlsx", ".xls"}
    if ext not in document_exts:
        return jsonify({"error": "unsupported file extension (PDF/xlsx/xls only)"}), 400

    # Reject unexpectedly large uploads even when the request stays under Flask's global limit.
    try:
        f.stream.seek(0, os.SEEK_END)
        file_size = f.stream.tell()
        f.stream.seek(0)
    except (AttributeError, OSError):
        file_size = 0
    if file_size == 0:
        return jsonify({"error": "empty file"}), 400
    max_size = 50 * 1024 * 1024
    if file_size > max_size:
        return jsonify({"error": f"file exceeds {max_size // (1024 * 1024)} MB limit"}), 413

    # Only store a document after successful text extraction; avoid broken IDs and orphan files.
    extracted_text = ""
    try:
        extracted_text = _extract_document_text(f.stream, ext)
    except Exception as e:
        print(f"[media] document extract failed: {e}")
        return jsonify({"error": f"document could not be read: {e}"}), 400

    if not extracted_text.strip():
        return jsonify({"error": "document contains no extractable text"}), 400

    f.stream.seek(0)
    file_id = uuid.uuid4().hex
    save_path = os.path.join(MEDIA_DIR, f"{file_id}{ext}")
    f.save(save_path)
    _media_registry[file_id] = save_path
    _media_text[file_id] = extracted_text
    print(f"[media] uploaded document: {f.filename} → {file_id}")
    return jsonify({"file_id": file_id, "media_type": "document", "filename": f.filename,
                    "text": extracted_text[:50000]})


@app.route("/api/media/<file_id>", methods=["DELETE"])
def api_media_delete(file_id):
    """업로드된 문서 파일 삭제 (선택적)."""
    if not re.fullmatch(r"[0-9a-f]{32}", file_id):
        return jsonify({"error": "invalid file_id"}), 400
    path = _media_registry.pop(file_id, None)
    _media_text.pop(file_id, None)
    if path and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
    return jsonify({"ok": True})


@app.route("/api/models")
def api_models():
    return jsonify({"models": [
        {"key": k, "name": v["name"], "avatar": v["avatar"], "kind": v.get("kind", "llm")}
        for k, v in MODELS.items()
    ]})


@app.route("/api/status")
def api_status():
    """로드 상태·GPU 메모리 현황 (디버깅/관리용)."""
    gpu = None
    if DEVICE == "cuda":
        try:
            gpu = {
                "allocated_mib": int(torch.cuda.memory_allocated() / 1e6),
                "reserved_mib": int(torch.cuda.memory_reserved() / 1e6),
                "free_mib": int(torch.cuda.get_device_properties(0).total_memory / 1e6) - int(torch.cuda.memory_reserved() / 1e6),
            }
        except Exception:
            gpu = None
    return jsonify({
        "model": {"key": MODEL_KEY, "name": MODELS[MODEL_KEY]["name"]},
        "loaded": _bundle is not None,
        "loading": _load_status["loading"],
        "device": DEVICE,
        "gpu": gpu,
    })


_questions_cache = {"mtime": None, "data": None}  # 질문 뱅크 파싱 결과 캐시 (mtime 무효화)


@app.route("/api/questions")
def api_questions():
    """질문 뱅크(REASONING_QUESTIONS.md) 목록 — 웹 UI에서 클릭만으로 질문하기 위한 데이터.
    파일 mtime 기반 캐시로 매 요청마다 문서를 다시 파싱하지 않는다."""
    qpath = os.path.join(os.path.dirname(__file__), "REASONING_QUESTIONS.md")
    try:
        mtime = os.path.getmtime(qpath)
    except OSError:
        mtime = None
    if _questions_cache["data"] is not None and _questions_cache["mtime"] == mtime:
        questions = _questions_cache["data"]
    else:
        try:
            from run_questions import load_questions, AUTO_CHECK
            questions = load_questions(qpath)
        except Exception as e:
            print(f"[questions] load failed: {e}")
            return jsonify({"error": str(e)}), 500
        # 웹 UI 배치 실행의 자동 확인용 — run_questions.py 와 동일한 키워드 정규식
        for q in questions:
            q["check"] = list(AUTO_CHECK.get(q["id"], ()))
        _questions_cache["mtime"] = mtime
        _questions_cache["data"] = questions
    return jsonify({"count": len(questions), "questions": questions})


@app.route("/api/results")
def api_results():
    """질문 뱅크 실행 이력(results/answers_*.json) 요약 — 웹 UI 비교 차트용."""
    out_dir = os.path.join(os.path.dirname(__file__), "results")
    sets = []
    if os.path.isdir(out_dir):
        names = sorted(
            (n for n in os.listdir(out_dir) if n.startswith("answers_") and n.endswith(".json")),
            reverse=True,
        )
        for name in names[:50]:  # 최근 50회까지만
            try:
                with open(os.path.join(out_dir, name), encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            slim = []
            for r in data.get("results") or []:
                m = r.get("metrics") or {}
                slim.append({
                    "id": r.get("id"),
                    "mode": r.get("mode"),
                    "run": r.get("run"),
                    "auto": r.get("auto") or "",
                    "error": r.get("error"),
                    "toks_per_s": m.get("toks_per_s"),
                    "elapsed_ms": m.get("elapsed_ms"),
                    "tokens": m.get("tokens"),
                    "wall_s": r.get("wall_s"),
                })
            sets.append({"file": name, "meta": data.get("meta") or {}, "results": slim})
    return jsonify({"count": len(sets), "sets": sets})


@app.route("/api/preload/<key>", methods=["POST"])
def api_preload(key):
    """모델을 미리 로딩. 첫 요청 대기 시간을 줄이려고 사용."""
    if key not in MODELS:
        return jsonify({"error": f"unknown model: {key}"}), 404
    info = MODELS[key]
    try:
        with _lock:
            get_model()
    except Exception as e:
        return jsonify({"error": str(e), "loaded": False}), 500
    return jsonify({"key": key, "name": info["name"], "loaded": True})


def _sse(obj):
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _request_object():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None
    return data


def _bounded_number(data, key, default, lower, upper, cast=float):
    raw = data.get(key, default)
    try:
        if isinstance(raw, bool):
            raise ValueError("boolean is not a numeric setting")
        value = cast(raw)
        if not math.isfinite(float(value)):
            raise ValueError("numeric setting must be finite")
    except (TypeError, ValueError, OverflowError):
        value = default
    return max(lower, min(upper, value))


def answer_metrics(text):
    cite = len(re.findall(r"\[\d{1,2}\]", text))
    para = len([p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]) or 1
    return {"cite": cite, "para": para}


def _collect_document_texts(file_ids):
    """document_file_ids → 추출 텍스트 리스트 (실패한 항목은 건너뜀)."""
    doc_texts = []
    for fid in file_ids:
        cached = _media_text.get(fid)
        if cached:
            doc_texts.append(cached)
            continue
        path = _media_registry.get(fid)
        if not path:
            continue
        try:
            text = _extract_document_text(path, os.path.splitext(path)[1])
            _media_text[fid] = text
            doc_texts.append(text)
        except Exception as ex:
            print(f"[chat] document read failed: {ex}")
    # 첨부 문서가 대화 문맥을 과도하게 키우지 않도록 메시지당 제한.
    if sum(len(t) for t in doc_texts) > 50000:
        doc_texts = ["\n".join(doc_texts)[:50000]]
    return doc_texts


@app.route("/api/chat", methods=["POST"])
def chat():
    data = _request_object()
    if data is None:
        return jsonify({"error": "JSON object required"}), 400
    model_key = data.get("model", MODEL_KEY)
    if not isinstance(model_key, str) or model_key not in MODELS:
        return jsonify({"error": f"unknown model: {model_key}"}), 400
    messages = data.get("messages", [])
    if not isinstance(messages, list) or len(messages) > 100 or any(not isinstance(msg, dict) for msg in messages):
        return jsonify({"error": "messages must be a list of at most 100 objects"}), 400
    for msg in messages:
        content = msg.get("content", "")
        if not isinstance(content, str):
            return jsonify({"error": "each message content must be a string"}), 400
        if len(content) > 100000:
            return jsonify({"error": "message content exceeds 100000 characters"}), 413
        ids = msg.get("document_file_ids", [])
        if not isinstance(ids, list) or len(ids) > 20 or any(not isinstance(fid, str) or not re.fullmatch(r"[0-9a-f]{32}", fid) for fid in ids):
            return jsonify({"error": "document_file_ids must be a list of at most 20 valid file IDs"}), 400
    temperature = _bounded_number(data, "temperature", 0.7, 0.1, 2.0)
    max_tokens = _bounded_number(data, "max_tokens", 2048, 64, 32768, int)
    # 선택: 기본 시스템 프롬프트에 덧붙일 말투/역할 지시 (UI의 말투/역할 프리셋)
    extra_system = data.get("system", "")
    thinking = bool(data.get("thinking", False))  # Qwen3.5 추론(thinking) 모드
    if not isinstance(extra_system, str) or len(extra_system) > 2000:
        return jsonify({"error": "system must be a string of at most 2000 characters"}), 400

    info = MODELS[model_key]
    print(f"[chat] model_key={model_key} name={info['name']} loaded={_bundle is not None}")

    def event_stream():
        # ---- 모델 로딩 ----
        if _bundle is None:
            yield _sse({"status": f"⏳ {info['name']} 로딩 중... (백그라운드 사전 로드가 끝나는 대로 시작됩니다)"})
        try:
            m = get_model()
        except Exception as e:
            yield _sse({"error": f"모델 로드 실패: {e}"})
            return
        tok = m["tokenizer"]

        system_text = info["system"]
        if extra_system.strip():
            system_text += "\n\n" + extra_system.strip()
        msgs = [{"role": "system", "content": system_text}]
        for msg in messages:
            role = "assistant" if msg.get("role") == "assistant" else "user"
            content = msg.get("content", "")
            # 첨부된 문서 파일 텍스트 삽입 (document_file_ids)
            if msg.get("document_file_ids"):
                doc_texts = _collect_document_texts(msg["document_file_ids"])
                if doc_texts:
                    content = f"첨부된 문서 내용:\n{chr(10).join(doc_texts)}\n\n사용자 질문: {content}"
            msgs.append({"role": role, "content": content})

        try:
            # Qwen3.5: 기본 thinking 모드 — 비활성화하려면 enable_thinking=False
            prompt_text = tok.apply_chat_template(
                msgs, tokenize=False, add_generation_prompt=True, enable_thinking=thinking)
        except TypeError:  # enable_thinking 미지원 템플릿 대비
            prompt_text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        inputs = tok(prompt_text, return_tensors="pt").to(DEVICE)

        # ---- 생성 (GPU 세션 락 내부에서 호출) ----
        from transformers import TextIteratorStreamer, StoppingCriteria, StoppingCriteriaList

        stop_event = Event()  # 클라이언트 중단(Esc)/연결 해제 신호

        class _StopOnEvent(StoppingCriteria):
            """stop_event 가 켜지면 generate 루프를 즉시 종료하는 스톱 신호."""
            def __call__(self, input_ids, scores, **kwargs):
                return stop_event.is_set()

        try:
            acc = []
            streamer = TextIteratorStreamer(tok, skip_prompt=True, skip_special_tokens=True)
            gen_kwargs = dict(
                **inputs, streamer=streamer, max_new_tokens=max_tokens,
                do_sample=True, temperature=max(0.1, temperature), top_p=0.9,
                pad_token_id=tok.eos_token_id,
                stopping_criteria=StoppingCriteriaList([_StopOnEvent()]),
            )
            t0 = time.perf_counter()
            n_tokens = 0
            _gen_th, gen_exc = _safe_generate(m["model"], **gen_kwargs)
            try:
                for piece in streamer:
                    if piece:
                        acc.append(piece)
                        n_tokens += len(tok(piece, add_special_tokens=False).get("input_ids", []))
                        yield _sse({"token": piece})
                elapsed = time.perf_counter() - t0
            finally:
                # 스트림이 끊기면(중단·새로고침·탭 닫기) GPU 생성 스레드를 즉시 세우고
                # 끝날 때까지 기다려 다음 요청이 빨리 GPU 락을 넘겨받게 한다.
                stop_event.set()
                _join_generation(_gen_th)
            if gen_exc["err"]:
                yield _sse({"error": f"생성 중 오류: {gen_exc['err']}"})
            else:
                metrics = answer_metrics("".join(acc)) if acc else {}
                metrics["elapsed_ms"] = int(elapsed * 1000)
                metrics["tokens"] = n_tokens
                metrics["toks_per_s"] = round(n_tokens / elapsed, 1) if elapsed > 0 else 0
                yield _sse({"done": True, "metrics": metrics})
        except Exception as e:
            yield _sse({"error": str(e)})
        finally:
            _join_generation(locals().get("_gen_th"))  # 안전장치 (이미 조인된 경우 noop)

    return Response(_serialize_gpu_stream(event_stream()), mimetype="text/event-stream; charset=utf-8")


def _open_browser(host, port):
    """서버 시작 후 2초 뒤 브라우저 자동 열기."""
    time.sleep(2)
    url = f"http://{host}:{port}"
    try:
        webbrowser.open(url)
        print(f"[server] 브라우저 열기 완료: {url}")
    except Exception as e:
        print(f"[server] 브라우저 자동 열기 실패 (수동 접속): {url} ({e})")


def main():
    print(f"[server] device = {DEVICE}")
    for k, v in MODELS.items():
        print(f"[server] model[{k}] = {v['name']} ({v['model_id']})")
    host = os.environ.get("APP_HOST", "127.0.0.1")
    port = int(os.environ.get("APP_PORT", "5000"))
    print(f"[server] ready -> http://{host}:{port}")
    # 모델 백그라운드 사전 로드 (APP_PRELOAD=0 으로 비활성화)
    if os.environ.get("APP_PRELOAD", "1") != "0":
        Thread(target=_background_preload, daemon=True).start()
    # 브라우저 자동 열기 (백그라운드 스레드) — APP_BROWSER=0 으로 비활성화
    if os.environ.get("APP_BROWSER", "1") != "0":
        Thread(target=_open_browser, args=(host, port), daemon=True).start()
    app.run(host=host, port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
