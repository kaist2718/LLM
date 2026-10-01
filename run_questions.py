r"""
run_questions.py — REASONING_QUESTIONS.md 질문 뱅크를 Qwen3.5-9B에 실행해 채점표 생성

사용법 (서버가 실행 중이어야 함 — start.bat [1]):
  .venv\Scripts\python.exe run_questions.py              # 34문항 × thinking OFF/ON
  .venv\Scripts\python.exe run_questions.py --quick      # 핵심 6문항만 빠르게
  .venv\Scripts\python.exe run_questions.py --ids Q7,Q13  # 특정 문항만
  .venv\Scripts\python.exe run_questions.py --modes off --runs 1

결과물 (results/ 폴더):
  score_sheet_*.md    — 채점표 (자동 확인 + 사람 채점 칸: 결론 2 / 과정 2 / 함정인지 1)
  answers_*.json      — 답변 전문 + 메트릭
"""
import argparse
import csv
import html
import json
import os
import re
import sys
import time
import urllib.request

# Windows 콘솔(cp949)에서 한글·특수문자 출력 깨짐 방지
for _s in ("stdout", "stderr"):
    try:
        getattr(sys, _s).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_URL = os.environ.get("APP_URL", "http://127.0.0.1:5000")
QUICK_IDS = ["Q2", "Q7", "Q13", "Q17", "Q23", "Q26"]

# 질문 뱅크 실행은 항상 한국어 답변을 받는다 (자동 확인 키워드가 한글 기준이라 영어 응답은 오답 처리됨)
KOREAN_SYSTEM = ("이 질문에 대해 반드시 한국어(한글)로만 답변하세요. "
                "수식·코드·고유명사를 제외한 모든 설명과 결론은 한국어로 작성합니다.")

# 자동 확인(키워드 정규식) — 전부 매칭되면 ✓. 참고용일 뿐 최종 채점은 사람이 한다.
AUTO_CHECK = {
    "Q1":  (r"유효하지 않",),
    "Q2":  (r"2\s*/\s*3|0\.66\d*|66\.\d",),
    "Q3":  (r"100\s*분",),
    "Q4":  (r"45\s*분", r"양쪽|양\s*끝|both ends"),
    "Q5":  (r"뭐라고|어떤 대답|대답하겠",),
    "Q6":  (r"\bA\b", r"\b7\b"),
    "Q7":  (r"8\.3|9\s*/\s*108|약\s*8(\.\d)?\s*%",),
    "Q8":  (r"1\s*/\s*2", r"1\s*/\s*3"),
    "Q9":  (r"평균\s*회귀|대조군|통제군",),
    "Q10": (r"과반|50\s*\.?\d*\s*%|50\.7",),
    "Q11": (r"생존\s*편향|추락|빠져|보이지 않",),
    "Q12": (r"\b89\b",),
    "Q13": (r"\b17\b",),
    "Q14": (r"3\s*개",),
    "Q15": (r"\b7\b",),
    "Q16": (r"온도|따뜻|열",),
    "Q17": (r"모호|둘\s*다|단정할\s*수\s*없|양쪽",),
    "Q18": (r"부력",),
    "Q19": (r"모호|두 가지|양쪽|해석",),
    "Q20": (r"기회\s*비용|보이지\s*않",),
    "Q21": (r"음속|공명|분자량|높아",),
    "Q22": (r"심슨|역설|패러독스|뒤집|구성비|가중치",),
    "Q23": (r"역설|진릿값|참과\s*거짓|부여할\s*수\s*없",),
    "Q24": (r"확신도|\d{1,3}\s*%",),
    "Q25": (r"역설|패러독스|자기참조|성립할 수 없|모순",),
    "Q26": (r"8\s*[÷/]\s*\(\s*3",),
    "Q27": (r"3\s*번|3\s*회|세\s*번",),
    "Q28": (r"4\s*(리터|L)",),
    # H. 재미있는 추론
    "Q29": (r"11\s*(번|회)|열한", r"16\s*분|16\s*\.\s*3|3시\s*16"),
    "Q30": (r"2\s*π|2π|6\.28", r"16\s*cm|15\.9|0\.1[56]"),
    "Q31": (r"존재할\s*수\s*없|존재하지\s*않|모순|성립하지\s*않|성립할\s*수\s*없",),
    "Q32": (r"같다|같은|동일|차이가\s*없",),
    "Q33": (r"같다|같은|동일|= ?1\b|1과\s*같",),
    "Q34": (r"2\s*\^\s*63|2⁶³|9\.2|9,?223",),
}


def load_questions(path):
    """REASONING_QUESTIONS.md 에서 문항(제목·난이도·질문·정답 요지)을 파싱."""
    questions, category, cur = [], "", None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            m = re.match(r"^## ([A-Z])\.\s+(.+)$", line)
            if m:
                category = f"{m.group(1)}. {m.group(2)}"
                continue
            m = re.match(r"^### (Q\d+)\.\s+(.+?)\s+\(([★☆]+)\)\s*$", line)
            if m:
                if cur:
                    questions.append(cur)
                cur = {"id": m.group(1), "title": m.group(2), "stars": m.group(3),
                       "category": category, "question": "", "answer": ""}
                continue
            if cur is None:
                continue
            if line.startswith("**질문**:"):
                cur["question"] = line.split("**질문**:", 1)[1].strip()
            elif line.startswith("**정답 요지**:"):
                cur["answer"] = line.split("**정답 요지**:", 1)[1].strip()
    if cur:
        questions.append(cur)
    # 문항 번호 순서 보장 (Q1 < Q2 < … < Q10 < … — 문서 순서와 동일)
    questions.sort(key=lambda q: int(q["id"][1:]) if q["id"][1:].isdigit() else 0)
    return questions


def api_status(url):
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/status", timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def chat_once(url, question, thinking, temperature, max_tokens, model, retries=2):
    """POST /api/chat (SSE) → (답변 텍스트, 메트릭, 오류).

    일시적 네트워크 오류(연결 거부·끊김)는 지수적 대기 후 재시도한다.
    서버가 SSE로 전달한 오류(모델 로드 실패 등)는 재시도하지 않고 그대로 반환한다.
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": question}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "thinking": thinking,
        "system": KOREAN_SYSTEM,  # 답변은 항상 한국어로
    }
    req = urllib.request.Request(
        url.rstrip("/") + "/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    last_err = None
    for attempt in range(retries + 1):
        parts, metrics, error = [], {}, None
        try:
            with urllib.request.urlopen(req, timeout=None) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        obj = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    if "token" in obj:
                        parts.append(obj["token"])
                    elif obj.get("done"):
                        metrics = obj.get("metrics", {}) or {}
                    elif "status" in obj:
                        print(f"      {obj['status']}", flush=True)
                    elif "error" in obj:
                        error = obj["error"]
            return "".join(parts), metrics, error
        except Exception as e:  # 네트워크 예외만 재시도
            last_err = e
            if attempt < retries:
                wait = 2 * (attempt + 1)
                print(f"      ⚠️ 연결 오류 — {wait}초 후 재시도 ({attempt + 1}/{retries}): {e}", flush=True)
                time.sleep(wait)
    return "", {}, f"요청 실패(재시도 {retries}회 후): {last_err}"


def auto_check(qid, text):
    pats = AUTO_CHECK.get(qid)
    if not pats:
        return ""
    return "✓" if all(re.search(p, text, re.IGNORECASE) for p in pats) else "✗"


def md_escape(text):
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _auto_pill(mark):
    if mark == "✓":
        return '<span class="pill ok">✓ 정답</span>'
    if mark == "✗":
        return '<span class="pill bad">✗ 오답</span>'
    return '<span class="pill na">-</span>'


def _mode_stats(results, mode):
    """해당 thinking 모드의 실행 집계 — 자동 정답률·속도·길이."""
    rows = [r for r in results if r["mode"] == mode]
    if not rows:
        return None
    autos = [r["auto"] for r in rows if r.get("auto")]
    ok = sum(1 for a in autos if a == "✓")
    ms = [r.get("metrics") or {} for r in rows]
    toks = [m.get("toks_per_s") for m in ms if m.get("toks_per_s")]
    elapsed = [m.get("elapsed_ms", 0) / 1000 for m in ms if m.get("elapsed_ms")]
    tokens = [m.get("tokens") for m in ms if m.get("tokens")]
    avg = lambda xs: sum(xs) / len(xs) if xs else None
    return {
        "n": len(rows),
        "auto_n": len(autos),
        "auto_ok": ok,
        "auto_rate": (ok / len(autos) * 100) if autos else None,
        "toks": avg(toks),
        "elapsed": avg(elapsed),
        "tokens": avg(tokens),
    }


def render_dashboard(questions, results):
    """thinking ON vs OFF 비교 대시보드 HTML (막대 그래프 + 문항별 판정)."""
    esc = lambda s: html.escape(str(s if s is not None else ""))
    off, on = _mode_stats(results, "OFF"), _mode_stats(results, "ON")
    if not off and not on:
        return ""

    def stat_card(label, off_v, on_v, suffix="", higher_better=True, show_verdict=True):
        def fmt(v):
            return "-" if v is None else f"{v:.1f}{suffix}"
        vals = [v for v in (off_v, on_v) if v is not None]
        mx = max(vals) if vals else 1.0

        def bar(v, cls):
            if v is None or not mx:
                w = 0
            else:
                w = min(100, max(5, round(v / mx * 100)))
            return f'<div class="bar"><div class="bar-fill {cls}" style="width:{w}%"></div></div>'

        verdict = ""
        if show_verdict and off_v is not None and on_v is not None:
            if abs(off_v - on_v) <= 1e-9:
                verdict = '<div class="verdict">우세: <b class="na">동률</b></div>'
            else:
                win_on = (on_v > off_v) == higher_better
                verdict = (f'<div class="verdict">우세: <b class="{"on" if win_on else "off"}">'
                           f'{"ON" if win_on else "OFF"}</b></div>')
        return (
            f'<div class="stat-card"><div class="stat-label">{label}</div>'
            f'<div class="stat-row"><span class="stat-name">OFF</span>'
            f'<span class="stat-val">{fmt(off_v)}</span>{bar(off_v, "off")}</div>'
            f'<div class="stat-row"><span class="stat-name">ON</span>'
            f'<span class="stat-val">{fmt(on_v)}</span>{bar(on_v, "on")}</div>'
            f"{verdict}</div>"
        )

    cards = [
        stat_card("🎯 자동 정답률 (참고용)",
                  off["auto_rate"] if off else None, on["auto_rate"] if on else None, "%"),
        stat_card("⚡ 평균 생성 속도",
                  off["toks"] if off else None, on["toks"] if on else None, " tok/s"),
        stat_card("⏱ 평균 소요 시간",
                  off["elapsed"] if off else None, on["elapsed"] if on else None, "s",
                  higher_better=False),
        stat_card("📏 평균 토큰 수",
                  off["tokens"] if off else None, on["tokens"] if on else None, "",
                  show_verdict=False),
    ]

    both = bool(off and on)
    table, headline = "", ""
    if both:
        by_q = {}
        for r in results:
            by_q.setdefault(r["id"], []).append(r)
        win = {"OFF": 0, "ON": 0, "동률": 0}
        rows_html = []
        for q in questions:
            rows = by_q.get(q["id"], [])
            o = [r for r in rows if r["mode"] == "OFF"]
            n = [r for r in rows if r["mode"] == "ON"]
            if not o and not n:
                continue

            def mark(rs):
                ks = [r["auto"] for r in rs if r.get("auto")]
                return "✓" if ks and all(k == "✓" for k in ks) else ("✗" if ks else "")

            def avg(rs, key):
                vals = [(r.get("metrics") or {}).get(key) for r in rs if (r.get("metrics") or {}).get(key)]
                return f"{sum(vals) / len(vals):.1f}" if vals else "-"

            om, nm = mark(o), mark(n)
            if om == "✓" and nm != "✓":
                verdict, cls = "OFF", "off"
            elif nm == "✓" and om != "✓":
                verdict, cls = "ON", "on"
            else:
                verdict, cls = "동률", "na"
            win[verdict] += 1
            rows_html.append(
                f"<tr><td><b>{esc(q['id'])}</b></td><td>{esc(q['title'])}</td>"
                f"<td>{_auto_pill(om)}</td><td>{_auto_pill(nm)}</td>"
                f'<td><b class="{cls}">{verdict}</b></td>'
                f"<td>{avg(o, 'toks_per_s')}</td><td>{avg(n, 'toks_per_s')}</td></tr>"
            )
        headline = (f"자동 확인 기준 판정 — <b class=\"on\">ON</b> {win['ON']}문항 · "
                    f"<b class=\"off\">OFF</b> {win['OFF']}문항 · 동률 {win['동률']}문항")
        table = (
            '\n    <table class="dash-table"><thead><tr><th>Q</th><th>제목</th><th>OFF 자동</th>'
            "<th>ON 자동</th><th>판정</th><th>OFF tok/s</th><th>ON tok/s</th></tr></thead>"
            f"\n    <tbody>{''.join(rows_html)}</tbody></table>"
        )
    else:
        headline = "thinking ON/OFF 비교는 두 모드를 모두 실행하면 표시됩니다 (예: <code>--modes off,on</code>)."

    return (
        '\n  <section class="card">\n    <h2>⚔️ thinking ON vs OFF 비교</h2>'
        f'\n    <p class="note">{headline}</p>'
        f'\n    <div class="dash-grid">{"".join(cards)}</div>'
        f"{table}\n  </section>"
    )


# 채점표 HTML에 삽입되는 대화형 채점 스크립트 (localStorage 자동 저장 · 합계 계산 · 복사 · 초기화)
GRADE_JS_TEMPLATE = r"""
<script>
(function(){
  var KEY = "qbank.grade.__SHEET_ID__";
  var saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch(e) { saved = {}; }
  var cells = [].slice.call(document.querySelectorAll("td[data-k]"));
  var hint = document.getElementById("saveHint");
  function num(v){ v = parseInt(v, 10); return isNaN(v) ? 0 : Math.max(0, Math.min(5, v)); }
  function rowSum(td){
    var tr = td.closest("tr"), s = 0;
    ["c","p","t"].forEach(function(f){
      var el = tr.querySelector('td[data-k$="' + ':' + f + '"]');
      if(el) s += num(el.textContent);
    });
    var out = tr.querySelector("td[data-sum]");
    if(out) out.textContent = s;
    return s;
  }
  function recalc(){
    document.querySelectorAll("td[data-sum]").forEach(function(td){ rowSum(td); });
    document.querySelectorAll("td[id^='sum-']").forEach(function(td){
      var qid = td.id.slice(4), off = 0, on = 0, hasOff = false, hasOn = false;
      document.querySelectorAll("td[data-sum]").forEach(function(s){
        var k = s.getAttribute("data-sum") || "";
        if(k.indexOf(qid + ":OFF:") === 0){ off += num(s.textContent); hasOff = true; }
        if(k.indexOf(qid + ":ON:") === 0){ on += num(s.textContent); hasOn = true; }
      });
      td.textContent = (hasOff ? off : "_") + " / " + (hasOn ? on : "_");
    });
  }
  cells.forEach(function(td){
    if(saved[td.dataset.k] != null) td.textContent = saved[td.dataset.k];
    td.addEventListener("input", function(){
      saved[td.dataset.k] = td.textContent.trim();
      try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch(e) {}
      if(hint) hint.textContent = "\u2714 \uc790\ub3d9 \uc800\uc7a5\ub428 " + new Date().toLocaleTimeString();
      recalc();
    });
    td.addEventListener("keydown", function(e){ if(e.key === "Enter"){ e.preventDefault(); } });
  });
  recalc();
  var resetBtn = document.getElementById("gradeReset");
  if(resetBtn) resetBtn.addEventListener("click", function(){
    if(!confirm("\uc774 \ucc44\uc810\ud450\uc5d0 \uc785\ub825\ud55c \uc810\uc218\ub97c \ubaa8\ub450 \uc9c0\uc6b0\uae4c\uc694?")) return;
    saved = {}; try { localStorage.removeItem(KEY); } catch(e) {}
    cells.forEach(function(td){ td.textContent = ""; });
    recalc();
    if(hint) hint.textContent = "\ucc44\uc810\uc774 \ucd08\uae30\ud654\ub418\uc5c8\uc2b5\ub2c8\ub2e4.";
  });
  var copyBtn = document.getElementById("gradeCopy");
  if(copyBtn) copyBtn.addEventListener("click", function(){
    var rows = ["Q\tmode\trun\tauto\tconclusion\tprocess\ttrap\tsum"];
    document.querySelectorAll("tr").forEach(function(tr){
      var sum = tr.querySelector("td[data-sum]");
      if(!sum) return;
      var k = (sum.getAttribute("data-sum")||"").split(":");
      var vals = [].slice.call(tr.querySelectorAll("td[data-k]")).map(function(td){ return td.textContent.trim(); });
      rows.push([k[0], k[1], k[2], tr.children[2].textContent.trim(), vals[0]||"", vals[1]||"", vals[2]||"", sum.textContent].join("\t"));
    });
    var text = rows.join("\n");
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(text).then(function(){ if(hint) hint.textContent = "\ud83d\udccb \ucc44\uc810\ud450\uac00 \ubcf5\uc0ac\ub418\uc5c8\uc2b5\ub2c8\ub2e4 (TSV)"; });
    }
  });
})();
</script>
"""


def write_html_sheet(path, meta, questions, results, json_name, csv_name, sheet_id=""):
    """브라우저에서 바로 채점하고 인쇄하기 좋은 단일 HTML 채점표 생성 (스타일 내장)."""
    esc = lambda s: html.escape(str(s if s is not None else ""))
    by_q = {}
    for r in results:
        by_q.setdefault(r["id"], []).append(r)

    pill = _auto_pill

    def avg_toks(rows, mode):
        vals = [x["metrics"].get("toks_per_s") for x in rows
                if x["mode"] == mode and x["metrics"].get("toks_per_s")]
        return f"{sum(vals) / len(vals):.1f}" if vals else "-"

    summary_rows, detail_sections = [], []
    for q in questions:
        rows = by_q.get(q["id"], [])
        off = "".join(pill(x["auto"]) for x in rows if x["mode"] == "OFF") or pill("")
        on = "".join(pill(x["auto"]) for x in rows if x["mode"] == "ON") or pill("")
        summary_rows.append(
            f"<tr><td><b>{esc(q['id'])}</b></td><td>{esc(q['title'])}</td>"
            f"<td class=\"stars\">{esc(q['stars'])}</td><td>{off}</td><td>{on}</td>"
            f"<td>{avg_toks(rows, 'OFF')}</td><td>{avg_toks(rows, 'ON')}</td>"
            f'<td class="sum" id="sum-{q["id"]}"></td></tr>'
        )
        if not rows:
            continue
        run_rows, details = [], []
        for r in rows:
            m = r["metrics"] or {}
            err = f" <span class=\"err\">⚠️ {esc(r['error'])}</span>" if r.get("error") else ""
            gkey = f"{q['id']}:{r['mode']}:{r['run']}"
            run_rows.append(
                f"<tr><td><b>{esc(r['mode'])}</b></td><td>{r['run']}</td><td>{pill(r['auto'])}</td>"
                f'<td class="blank" contenteditable data-k="g:{gkey}:c"></td>'
                f'<td class="blank" contenteditable data-k="g:{gkey}:p"></td>'
                f'<td class="blank" contenteditable data-k="g:{gkey}:t"></td>'
                f'<td class="sum" data-sum="{gkey}"></td>'
                f"<td>{esc(m.get('toks_per_s', '-'))}</td>"
                f"<td>{round(m.get('elapsed_ms', 0) / 1000, 1) if m else '-'}</td>"
                f"<td>{esc(m.get('tokens', '-'))}{err}</td></tr>"
            )
            body = r["text"] if r["text"] else f"(빈 답변 — 오류: {r.get('error')})"
            details.append(
                f"<details><summary>💬 {esc(r['mode'])} run {r['run']} 답변 전문</summary>"
                f"<pre>{esc(body)}</pre></details>"
            )
        detail_sections.append(
            "\n    <section class=\"card q-card\">"
            f"\n      <h3>{esc(q['id'])}. {esc(q['title'])} <span class=\"stars\">{esc(q['stars'])}</span></h3>"
            f"\n      <div class=\"cat\">{esc(q['category'])}</div>"
            f"\n      <div class=\"prompt\"><b>질문</b> {esc(q['question'])}</div>"
            f"\n      <div class=\"prompt key\"><b>정답 요지</b> {esc(q['answer'])}</div>"
            "\n      <table class=\"runs\"><thead><tr><th>모드</th><th>회차</th><th>자동</th>"
            "<th>결론(2)</th><th>과정(2)</th><th>함정인지(1)</th><th>합(5)</th>"
            "<th>tok/s</th><th>소요(s)</th><th>토큰</th></tr></thead>"
            f"\n      <tbody>{''.join(run_rows)}</tbody></table>"
            f"\n      {''.join(details)}\n    </section>"
        )

    warn = '<div class="warn">⚠️ 실행이 중단되어 일부 문항만 채점되었습니다.</div>' if meta.get("interrupted") else ""
    dash = render_dashboard(questions, results)
    off_s, on_s = _mode_stats(results, "OFF"), _mode_stats(results, "ON")
    acc_bits = []
    for _lab, _st in (("OFF", off_s), ("ON", on_s)):
        if _st and _st["auto_n"]:
            acc_bits.append(f"{_lab} {_st['auto_ok']}/{_st['auto_n']} ({round(_st['auto_ok'] / _st['auto_n'] * 100)}%)")
    acc_line = f'<p class="note">🎯 자동 확인 정답률(참고용): {" · ".join(acc_bits)}</p>' if acc_bits else ""
    grade_js = GRADE_JS_TEMPLATE.replace("__SHEET_ID__", sheet_id or "default")
    created = time.strftime("%Y-%m-%d %H:%M:%S")
    doc = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>추론력 질문 채점표 — {esc(meta.get('model_name', ''))}</title>
<style>
  :root {{ --bg:#f4f6fb; --card:#ffffff; --fg:#1c2333; --dim:#6b7690; --line:#e3e8f2; --accent:#3b6eff; --ok:#16a34a; --bad:#dc2626; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#12151d; --card:#1a1f2b; --fg:#e7ebf4; --dim:#98a2b8; --line:#2b3345; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font-family:'Segoe UI','Malgun Gothic','Noto Sans KR',sans-serif; line-height:1.6; padding:36px 16px 72px; }}
  .wrap {{ max-width:1020px; margin:0 auto; }}
  header {{ background:linear-gradient(135deg,#3b6eff,#7b5cff); color:#fff; border-radius:18px; padding:30px 32px; margin-bottom:22px; box-shadow:0 10px 28px rgba(59,110,255,.28); }}
  header h1 {{ margin:0 0 8px; font-size:23px; letter-spacing:-.3px; }}
  header .meta {{ opacity:.94; font-size:13.5px; }}
  header code {{ background:rgba(255,255,255,.18); padding:1px 7px; border-radius:6px; }}
  .badges {{ margin-top:14px; display:flex; gap:8px; flex-wrap:wrap; }}
  .badge {{ background:rgba(255,255,255,.18); border:1px solid rgba(255,255,255,.35); padding:4px 12px; border-radius:999px; font-size:12.5px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:15px; padding:22px 24px; margin-bottom:18px; box-shadow:0 2px 10px rgba(20,30,60,.05); }}
  h2 {{ font-size:16.5px; margin:0 0 14px; }}
  h3 {{ font-size:15px; margin:0 0 8px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th, td {{ border-bottom:1px solid var(--line); padding:9px 10px; text-align:left; vertical-align:top; }}
  th {{ color:var(--dim); font-weight:600; font-size:12px; white-space:nowrap; }}
  tbody tr:last-child td {{ border-bottom:none; }}
  .stars {{ color:#f59e0b; white-space:nowrap; }}
  .cat {{ color:var(--dim); font-size:12.5px; margin-bottom:10px; }}
  .pill {{ display:inline-block; padding:2px 10px; border-radius:999px; font-size:12px; font-weight:600; white-space:nowrap; }}
  .pill.ok {{ background:rgba(22,163,74,.14); color:var(--ok); }}
  .pill.bad {{ background:rgba(220,38,38,.12); color:var(--bad); }}
  .pill.na {{ background:rgba(120,130,160,.14); color:var(--dim); }}
  .dash-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(215px,1fr)); gap:13px; margin:10px 0 4px; }}
  .stat-card {{ border:1px solid var(--line); border-radius:12px; padding:14px 16px; background:rgba(120,130,160,.05); }}
  .stat-label {{ color:var(--dim); font-size:12px; margin-bottom:9px; }}
  .stat-row {{ display:flex; align-items:center; gap:8px; margin:5px 0; font-size:12.5px; }}
  .stat-name {{ width:30px; color:var(--dim); }}
  .stat-val {{ width:74px; font-weight:600; text-align:right; font-variant-numeric:tabular-nums; }}
  .bar {{ flex:1; height:9px; background:rgba(120,130,160,.15); border-radius:999px; overflow:hidden; }}
  .bar-fill {{ height:100%; border-radius:999px; }}
  .bar-fill.off {{ background:linear-gradient(90deg,#3b6eff,#6f9bff); }}
  .bar-fill.on {{ background:linear-gradient(90deg,#7b5cff,#a68cff); }}
  .verdict {{ margin-top:8px; font-size:12px; color:var(--dim); }}
  b.on {{ color:#7b5cff; }} b.off {{ color:#3b6eff; }} b.na {{ color:var(--dim); }}
  .grade-bar {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-top:12px; }}
  .gb {{ border:1px solid var(--line); background:rgba(59,110,255,.08); color:var(--fg); border-radius:9px; padding:7px 13px; font-size:12.5px; cursor:pointer; }}
  .gb:hover {{ background:rgba(59,110,255,.16); }}
  td.sum {{ text-align:center; font-weight:700; color:var(--accent); }}
  .prompt {{ background:rgba(59,110,255,.07); border-left:3px solid var(--accent); padding:10px 15px; border-radius:9px; margin:10px 0; font-size:13.5px; }}
  .prompt.key {{ background:rgba(245,158,11,.09); border-left-color:#f59e0b; }}
  .blank {{ min-width:34px; border-bottom:1.5px dashed var(--dim); background:rgba(120,130,160,.05); outline:none; }}
  .blank:focus {{ background:rgba(59,110,255,.10); }}
  .err {{ color:var(--bad); font-size:11.5px; }}
  .note {{ color:var(--dim); font-size:12.5px; margin:12px 0 0; }}
  details {{ margin:10px 0 0; border:1px solid var(--line); border-radius:10px; overflow:hidden; }}
  summary {{ cursor:pointer; padding:10px 15px; font-weight:600; font-size:13px; background:rgba(120,130,160,.08); user-select:none; }}
  summary:hover {{ background:rgba(59,110,255,.10); }}
  pre {{ margin:0; padding:15px 17px; white-space:pre-wrap; word-break:break-word; font-size:12.5px; line-height:1.65; font-family:Consolas,'D2 Coding',monospace; max-height:460px; overflow:auto; }}
  .warn {{ background:rgba(245,158,11,.12); border:1px solid rgba(245,158,11,.45); color:#b45309; padding:12px 16px; border-radius:11px; margin-bottom:16px; font-size:13px; }}
  footer {{ text-align:center; color:var(--dim); font-size:12px; margin-top:28px; }}
  @media print {{ body {{ background:#fff; padding:0; }} .no-print {{ display:none !important; }} .card {{ break-inside:avoid; box-shadow:none; }} header {{ box-shadow:none; }} details {{ break-inside:avoid; }} }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>🧠 추론력 질문 채점표</h1>
    <div class="meta">{esc(meta.get('model_name', '?'))} (<code>{esc(meta.get('model_key', '?'))}</code>) · device={esc(meta.get('device', '?'))} · 생성 {created}</div>
    <div class="badges">
      <span class="badge">🌡 온도 {esc(meta['temperature'])}</span>
      <span class="badge">📏 max_tokens {esc(meta['max_tokens'])}</span>
      <span class="badge">🤔 thinking {esc(meta['modes_text'])}</span>
      <span class="badge">🔁 회차 {esc(meta['runs'])}</span>
    </div>
  </header>
  {warn}
  <section class="card">
    <h2>📋 요약</h2>
    <table>
      <thead><tr><th>Q</th><th>제목</th><th>난이도</th><th>OFF 자동</th><th>ON 자동</th><th>OFF tok/s</th><th>ON tok/s</th><th>합계 OFF/ON</th></tr></thead>
      <tbody>{''.join(summary_rows)}</tbody>
    </table>
    {acc_line}
    <p class="note">채점 기준: 결론(2) + 과정(2) + 함정인지(1) = 5점 · 자동 확인(✓/✗)은 키워드 기반 <b>참고용</b>이며 최종 채점은 사람이 수행합니다. 점선 칸에 점수를 입력하면 합계가 자동 계산됩니다.</p>
    <div class="grade-bar no-print">
      <span class="note" id="saveHint">점선 칸에 점수를 입력하면 이 브라우저에 자동 저장됩니다.</span>
      <button id="gradeCopy" class="gb" type="button">📋 채점표 복사(TSV)</button>
      <button id="gradeReset" class="gb" type="button">↺ 채점 초기화</button>
    </div>
  </section>
  {dash}
  {''.join(detail_sections)}
  <section class="card">
    <h2>📄 데이터 파일</h2>
    <p class="note">답변 전문: <code>{esc(json_name)}</code> · 회차별 요약 CSV: <code>{esc(csv_name)}</code></p>
  </section>
  <footer>생성 {created} · run_questions.py · REASONING_QUESTIONS.md 질문 뱅크</footer>
</div>
{grade_js}
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


def write_csv_sheet(path, questions, results):
    """회차별 요약 CSV — 엑셀에서 바로 분석·채점 (UTF-8 BOM)."""
    q_by_id = {q["id"]: q for q in questions}
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "title", "stars", "category", "mode", "run", "auto",
                    "toks_per_s", "elapsed_s", "tokens", "wall_s",
                    "score_conclusion_2", "score_process_2", "score_trap_1", "error"])
        for r in results:
            q = q_by_id.get(r["id"], {})
            m = r["metrics"] or {}
            w.writerow([
                r["id"], q.get("title", ""), q.get("stars", ""), q.get("category", ""),
                r["mode"], r["run"], r.get("auto", ""),
                m.get("toks_per_s", ""), round(m.get("elapsed_ms", 0) / 1000, 1) if m else "",
                m.get("tokens", ""), r.get("wall_s", ""), "", "", "", r.get("error") or "",
            ])


def write_outputs(out_dir, meta, questions, results):
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    sheet_path = os.path.join(out_dir, f"score_sheet_{stamp}.md")
    html_path = os.path.join(out_dir, f"score_sheet_{stamp}.html")
    csv_path = os.path.join(out_dir, f"score_sheet_{stamp}.csv")
    json_path = os.path.join(out_dir, f"answers_{stamp}.json")

    by_q = {}
    for r in results:
        by_q.setdefault(r["id"], []).append(r)

    lines = []
    lines.append("# 추론력 질문 채점표\n")
    lines.append(f"- 생성: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 모델: {meta.get('model_name', '?')} (`{meta.get('model_key', '?')}`) · device={meta.get('device', '?')}")
    lines.append(f"- 생성 설정: 온도 {meta['temperature']} · max_tokens {meta['max_tokens']} · thinking {meta['modes_text']} · 회차 {meta['runs']}")
    _off, _on = _mode_stats(results, "OFF"), _mode_stats(results, "ON")
    _acc = []
    for _lab, _st in (("OFF", _off), ("ON", _on)):
        if _st and _st["auto_n"]:
            _acc.append(f"{_lab} {_st['auto_ok']}/{_st['auto_n']} ({round(_st['auto_ok'] / _st['auto_n'] * 100)}%)")
    if _acc:
        lines.append(f"- 🎯 자동 확인 정답률(참고용): {' · '.join(_acc)}")
    lines.append("- **자동 확인**은 키워드 기반 참고용입니다. 최종 채점(결론 2 / 과정 2 / 함정인지 1)은 사람이 수행하세요.")
    if meta.get("interrupted"):
        lines.append("- ⚠️ **실행이 중단되어 일부 문항만 채점되었습니다.**")
    lines.append(f"- 답변 전문 데이터: `{os.path.basename(json_path)}`\n")

    lines.append("## 요약\n")
    lines.append("| Q | 제목 | 난이도 | OFF 자동 | ON 자동 | OFF tok/s | ON tok/s | 합계 OFF/ON (사람 채점) |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for q in questions:
        rows = by_q.get(q["id"], [])
        cell = {}
        for r in rows:
            cell.setdefault(r["mode"], []).append(r)
        def avg_toks(mode):
            vals = [x["metrics"].get("toks_per_s") for x in cell.get(mode, []) if x["metrics"].get("toks_per_s")]
            return f"{sum(vals) / len(vals):.1f}" if vals else "-"
        off = " ".join(x["auto"] for x in cell.get("OFF", [])) or "-"
        on = " ".join(x["auto"] for x in cell.get("ON", [])) or "-"
        lines.append(f"| {q['id']} | {md_escape(q['title'])} | {q['stars']} | {off} | {on} | {avg_toks('OFF')} | {avg_toks('ON')} |  /  |")
    lines.append("")

    lines.append("## 상세 채점표\n")
    for q in questions:
        rows = by_q.get(q["id"], [])
        if not rows:
            continue
        lines.append(f"### {q['id']}. {q['title']} ({q['stars']}) — {q['category']}\n")
        lines.append(f"**질문**: {q['question']}\n")
        lines.append(f"**정답 요지**: {q['answer']}\n")
        lines.append("| 모드 | 회차 | 자동 | 결론(2) | 과정(2) | 함정인지(1) | 합(5) | tok/s | 소요(s) | 토큰 |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for r in rows:
            m = r["metrics"]
            err = f" ⚠️ {r['error']}" if r["error"] else ""
            lines.append(
                f"| {r['mode']} | {r['run']} | {r['auto'] or '-'} |  |  |  |  | "
                f"{m.get('toks_per_s', '-')} | {round(m.get('elapsed_ms', 0) / 1000, 1) if m else '-'} | {m.get('tokens', '-')}{err} |"
            )
        lines.append("")
        for r in rows:
            lines.append(f"<details><summary>{r['mode']} run {r['run']} 답변 전문</summary>\n")
            lines.append("```text")
            lines.append(r["text"] if r["text"] else f"(빈 답변 — 오류: {r['error']})")
            lines.append("```\n</details>\n")

    with open(sheet_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "questions": questions, "results": results}, f, ensure_ascii=False, indent=2)
    write_html_sheet(html_path, meta, questions, results,
                     os.path.basename(json_path), os.path.basename(csv_path), sheet_id=stamp)
    write_csv_sheet(csv_path, questions, results)
    return {"md": sheet_path, "html": html_path, "csv": csv_path, "json": json_path}


def main():
    ap = argparse.ArgumentParser(description="REASONING_QUESTIONS.md 질문 뱅크 실행 + 채점표 생성")
    ap.add_argument("--url", default=DEFAULT_URL, help=f"서버 URL (기본 {DEFAULT_URL})")
    ap.add_argument("--model", default="qwen35", help="모델 키 (기본 qwen35)")
    ap.add_argument("--modes", default="off,on", help="thinking 모드 (off,on 조합)")
    ap.add_argument("--runs", type=int, default=1, help="문항당 반복 횟수 (기본 1)")
    ap.add_argument("--temperature", type=float, default=0.2, help="온도 (기본 0.2 — 결정적 비교용)")
    ap.add_argument("--max-tokens", type=int, default=4096, help="최대 생성 길이 (기본 4096)")
    ap.add_argument("--quick", action="store_true", help="핵심 6문항만 실행")
    ap.add_argument("--ids", default="", help="실행할 문항 ID (예: Q7,Q13)")
    ap.add_argument("--questions", default=os.path.join(HERE, "REASONING_QUESTIONS.md"))
    ap.add_argument("--out-dir", default=os.path.join(HERE, "results"))
    ap.add_argument("--list", action="store_true", help="파싱된 문항만 출력하고 종료")
    args = ap.parse_args()

    questions = load_questions(args.questions)
    if not questions:
        print("[error] 문항을 찾지 못했습니다:", args.questions)
        return 1

    if args.ids:
        want = {s.strip().upper() for s in args.ids.split(",") if s.strip()}
        questions = [q for q in questions if q["id"] in want]
    elif args.quick:
        questions = [q for q in questions if q["id"] in QUICK_IDS]

    if args.list:
        for q in questions:
            print(f"{q['id']} ({q['stars']}) [{q['category']}] {q['title']}")
            print(f"    질문: {q['question'][:60]}...")
        print(f"총 {len(questions)}문항")
        return 0

    if not questions:
        print("[error] 선택된 문항이 없습니다")
        return 1

    modes = []
    for m in args.modes.split(","):
        m = m.strip().lower()
        if m in ("on", "true", "1"):
            modes.append(("ON", True))
        elif m in ("off", "false", "0"):
            modes.append(("OFF", False))

    status = api_status(args.url)
    if "error" in status:
        print(f"[error] 서버에 연결할 수 없습니다: {status['error']}")
        print("        서버를 먼저 실행하세요 (start.bat [1] 또는 python app.py)")
        return 1
    print(f"[server] model={status.get('model', {}).get('name')} loaded={status.get('loaded')} loading={status.get('loading')} device={status.get('device')}")

    tasks = [(q, mode_name, thinking, run)
             for q in questions for (mode_name, thinking) in modes for run in range(1, args.runs + 1)]
    print(f"[run] 총 {len(tasks)}회 실행 (문항 {len(questions)} × 모드 {len(modes)} × 회차 {args.runs})\n")

    results = []
    interrupted = False
    try:
        for i, (q, mode_name, thinking, run) in enumerate(tasks, 1):
            print(f"[{i}/{len(tasks)}] {q['id']} · thinking={mode_name} · run {run} ...", flush=True)
            t0 = time.perf_counter()
            text, metrics, error = chat_once(args.url, q["question"], thinking,
                                             args.temperature, args.max_tokens, args.model)
            wall = time.perf_counter() - t0
            auto = auto_check(q["id"], text)
            results.append({"id": q["id"], "mode": mode_name, "run": run, "thinking": thinking,
                            "text": text, "metrics": metrics, "error": error, "auto": auto,
                            "wall_s": round(wall, 1)})
            if error:
                print(f"      ⚠️ 오류: {error}")
            else:
                print(f"      완료 ({metrics.get('toks_per_s', '-')} tok/s, {wall:.1f}s) 자동확인 {auto or '-'}")
    except KeyboardInterrupt:
        # Ctrl+C 로 끊어도 지금까지 확보한 결과는 잃지 않고 채점표를 남긴다.
        interrupted = True
        print("\n\n[warn] 중단됨 — 지금까지의 결과로 채점표를 생성합니다...")

    if not results:
        print("[error] 완료된 결과가 없어 채점표를 만들지 않습니다")
        return 1

    meta = {
        "model_key": args.model,
        "model_name": status.get("model", {}).get("name", args.model),
        "device": status.get("device", "?"),
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "runs": args.runs,
        "modes_text": "/".join(m[0] for m in modes),
        "interrupted": interrupted,
    }
    paths = write_outputs(args.out_dir, meta, questions, results)
    print(f"\n[done] 채점표(HTML): {paths['html']}")
    print(f"[done] 채점표(Markdown): {paths['md']}")
    print(f"[done] 회차별 요약 CSV: {paths['csv']}")
    print(f"[done] 답변 전문: {paths['json']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
