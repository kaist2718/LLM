#!/usr/bin/env python3
"""저장소의 마크다운 문서를 정적 HTML 사이트로 렌더링한다 (GitHub Pages 배포용).

사용법:
    python scripts/build_docs.py [출력 디렉터리]   # 기본값: site/

의존성:
    pip install markdown

각 문서의 .md 간 링크는 생성된 .html 페이지로 자동 치환된다.
"""
import re
import shutil
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "site")

# (출력 파일명, 원본 마크다운, 내비게이션 제목)
PAGES = [
    ("index.html", "README.md", "홈"),
    ("readme-en.html", "README.en.md", "English"),
    ("manual.html", "MANUAL.md", "사용 설명서"),
    ("experiments.html", "EXPERIMENTS.md", "실험 모음"),
    ("questions.html", "REASONING_QUESTIONS.md", "질문 뱅크"),
    ("contributing.html", "CONTRIBUTING.md", "기여 가이드"),
]

# 문서 간 링크 치환 규칙 (파일명 -> 사이트 내 경로)
MD_LINKS = {
    "README.md": "index.html",
    "README.en.md": "readme-en.html",
    "MANUAL.md": "manual.html",
    "EXPERIMENTS.md": "experiments.html",
    "REASONING_QUESTIONS.md": "questions.html",
    "CONTRIBUTING.md": "contributing.html",
}

TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ color-scheme: light; }}
body {{ margin: 0; font-family: -apple-system, "Segoe UI", "Malgun Gothic", sans-serif; color: #24292f; background: #fff; line-height: 1.7; }}
nav {{ position: sticky; top: 0; background: #24292f; padding: 10px 16px; display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }}
nav a {{ color: #d0d7de; text-decoration: none; padding: 6px 12px; border-radius: 8px; font-size: 14px; }}
nav a:hover {{ background: #3a414b; color: #fff; }}
nav a.active {{ background: #0969da; color: #fff; }}
main {{ max-width: 900px; margin: 0 auto; padding: 28px 20px 72px; }}
h1, h2, h3 {{ line-height: 1.35; }}
h1 {{ border-bottom: 1px solid #d0d7de; padding-bottom: .3em; }}
h2 {{ border-bottom: 1px solid #eaecef; padding-bottom: .3em; margin-top: 2em; }}
code {{ background: #f6f8fa; padding: .15em .4em; border-radius: 6px; font-size: .9em; }}
pre {{ background: #f6f8fa; padding: 14px; border-radius: 10px; overflow-x: auto; }}
pre code {{ background: none; padding: 0; }}
table {{ border-collapse: collapse; width: 100%; display: block; overflow-x: auto; }}
th, td {{ border: 1px solid #d0d7de; padding: 7px 11px; text-align: left; }}
th {{ background: #f6f8fa; }}
img {{ max-width: 100%; }}
blockquote {{ border-left: 4px solid #d0d7de; margin: 0; padding: 2px 16px; color: #57606a; }}
footer {{ max-width: 900px; margin: 0 auto; padding: 20px; color: #57606a; font-size: 13px; border-top: 1px solid #eaecef; }}
footer a {{ color: #0969da; }}
</style>
</head>
<body>
<nav>{nav}</nav>
<main>
{body}
</main>
<footer>이 문서는 저장소의 마크다운 파일에서 자동 생성됩니다 — <a href="https://github.com/kaist2718/LLM">GitHub 저장소</a></footer>
</body>
</html>
"""


def rewrite_links(text):
    """[MANUAL.md](MANUAL.md#anchor) 같은 문서 간 링크를 사이트 내 페이지로 치환."""

    def repl(match):
        target, anchor = match.group(1), match.group(2) or ""
        name = target.rsplit("/", 1)[-1]
        if name in MD_LINKS:
            return f"]({MD_LINKS[name]}{anchor})"
        return match.group(0)

    return re.sub(r"\]\(([^)\s]+\.md)(#[^)\s]*)?\)", repl, text)


def render_nav(current):
    items = []
    for out_name, _, label in PAGES:
        cls = ' class="active"' if out_name == current else ""
        items.append(f'<a href="{out_name}"{cls}>{label}</a>')
    return "".join(items)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    for out_name, md_name, _ in PAGES:
        src = ROOT / md_name
        text = rewrite_links(src.read_text(encoding="utf-8"))
        body = markdown.markdown(text, extensions=["extra", "toc"])
        title_match = re.search(r"^#\s+(.+)$", text, re.M)
        title = title_match.group(1).strip() if title_match else md_name
        site_name = "Qwen3.5-9B 로컬 채팅"
        page_title = title if title == site_name else f"{title} · {site_name}"
        html = TEMPLATE.format(title=page_title, nav=render_nav(out_name), body=body)
        (OUT / out_name).write_text(html, encoding="utf-8")
        print(f"생성: {OUT / out_name}")

    # 정적 자산 복사 (스크린샷 경로 docs/screenshots/... 를 그대로 유지)
    if (ROOT / "docs").is_dir():
        shutil.copytree(ROOT / "docs", OUT / "docs")
    shutil.copy2(ROOT / "LICENSE", OUT / "LICENSE")
    print(f"문서 사이트 빌드 완료: {OUT}")


if __name__ == "__main__":
    main()
