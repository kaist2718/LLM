# Qwen3.5-9B 로컬 채팅

Windows 단일 GPU 환경에서 Qwen3.5-9B 한 종을 사전 양자화(bnb 4bit)로 빠르게 불러오는 Flask 로컬 앱입니다. 기본 시스템 프롬프트는 범용 어시스턴트로 설정되어 있습니다. CUDA 사용 시 4bit 양자화를 적용해 SSE 스트리밍 채팅과 PDF/엑셀 문서 질의를 지원합니다.

> 📖 처음 사용한다면 [MANUAL.md](MANUAL.md)의 단계별 사용 설명서를 따라가세요 (설치·화면 사용법·질문 뱅크·문제 해결 포함).

## 모델

| 모델 | 용도·특징 | 공식 카드 / 라이선스 확인 |
|---|---|---|
| 🔮 Qwen3.5-9B | Qwen 다국어 모델(2026.3). 기본 thinking 모드, `enable_thinking`으로 켜기/끄기 전환 가능 | [Hugging Face](https://huggingface.co/Qwen/Qwen3.5-9B) |

로딩 속도를 위해 기본값으로 사전 양자화(bnb NF4) 가중치인 [rectx/Qwen3.5-9B-bnb-4bit](https://huggingface.co/rectx/Qwen3.5-9B-bnb-4bit)를 사용합니다 (약 7.6GB — 원본 18.4GB의 절반 이하, 로드 시 재양자화 없음). 원본 전체 가중치가 필요하면 `QWEN35_MODEL_ID=Qwen/Qwen3.5-9B`로 지정하면 기존처럼 로드 시 4bit 양자화합니다.

> 가중치를 비용 없이 로컬에서 내려받아 쓸 수 있다는 뜻과, 호스팅 API의 무료 할당량은 다릅니다. 라이선스는 배포·상업 이용 전에 공식 카드의 최신 전문과 사용 조건을 확인하세요. 모델 카드의 벤치마크는 버전·프롬프트·샷·평가 세팅이 달라 서로 직접 비교할 수 없습니다.

## 주요 기능

- 범용 어시스턴트 기본 프롬프트 (정직한 답변, 출처 표기·지어내지 않기 규칙 포함)
- Qwen3.5-9B 단일 모델 채팅 (서버 시작 시 백그라운드 사전 로드, `⚡ 모델 로드` 버튼 또는 최초 요청 시 로드)
- 추론(thinking) 모드 토글 (⚙️ 설정에서 켜고 끄기, 기본값 꺼짐)
- SSE 토큰 스트리밍 + 스트리밍 중 실시간 마크다운 렌더링, tok/s·소요시간 메트릭
- 말투/역할 프리셋 (간결·상세·번역·글쓰기 교정·코딩·쉬운 설명)
- PDF/엑셀 텍스트 추출 및 문서 첨부 질의 (추출 텍스트 캐시로 반복 질의 가속)
- 다중 대화(localStorage), 검색·이름 변경·고정·즐겨찾기·분기·재생성·내보내기(HTML·Markdown·JSON·인쇄/PDF)·백업 가져오기(JSON 복원)
- 다크/라이트 테마, 마크다운 렌더링과 코드 복사
- 질문 뱅크 (웹 UI 📚/Ctrl+B에서 클릭만으로 질문·결과 비교, `run_questions.bat` 원클릭 실행 → thinking ON/OFF 비교 대시보드가 포함된 HTML·Markdown·CSV 채점표 자동 생성, Ctrl+C 중단 시에도 지금까지 결과로 채점표 생성)

## 파일 구조

| 파일 | 역할 |
|---|---|
| `app.py` | Flask SSE 서버, 업로드·문서 추출, 모델 로드 및 GPU 세션 관리 |
| `index.html` | 브라우저 채팅 UI |
| `dl_qwen35.py` | 사전 양자화(bnb 4bit) 가중치 다운로드 (hf_transfer 가속) |
| `start.bat` | Windows 실행/정리 메뉴 |
| `EXPERIMENTS.md` | Qwen3.5-9B 재미있는 실험 모음 |
| `REASONING_QUESTIONS.md` | 추론력 질문 뱅크 (크리티컬 사고 테스트) |
| `run_questions.py` | 질문 뱅크 실행 + 채점표 자동 생성 |
| `run_questions.bat` | 질문 뱅크 원클릭 실행 (서버 자동 시작 포함) |
| `MANUAL.md` | 상세 사용 설명서 |
| `tests/` | 질문 뱅크 단위 테스트 (`python -m unittest discover -s tests`) |
| `.gitignore` | 가상환경·모델 가중치·실행 결과물 등 푸시 제외 규칙 |

## 설치 및 실행 (Windows, uv, Python 3.12, CUDA)

### 0. 요구 사양

| 항목 | 권장 | 최소 |
|---|---|---|
| OS | Windows 10/11 | — |
| GPU | NVIDIA CUDA GPU, VRAM 12GB (예: RTX 3060) | 8GB (짧은 대화만) |
| RAM | 32GB | 16GB |
| 디스크 | 여유 10GB (모델 7.6GB + 캐시) | 8GB |
| Python | 3.12 (`uv`가 자동 설치) | 3.10+ |

> GPU가 없어도 CPU 모드로 실행되지만 9B 모델은 매우 느립니다. NVIDIA 드라이버는 [최신 버전](https://www.nvidia.com/Download/index.aspx)을 권장합니다.

### 1. 사전 준비 (처음 한 번만)

- **Git**: [git-scm.com](https://git-scm.com/downloads)에서 설치 (또는 `winget install Git.Git`)
- **uv** (Python 패키지/가상환경 관리자): PowerShell에서 아래 한 줄 실행

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. 소스코드 내려받기

```powershell
git clone https://github.com/kaist2718/LLM.git
cd LLM
```

### 3. 가상환경 생성 + 의존성 설치

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe torch --index-url https://download.pytorch.org/whl/cu130
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

- `torch`는 CUDA 13.0용으로 설치합니다. 본인 드라이버에 맞는 CUDA 버전의 인덱스 URL(`cu126` 등)로 바꿔도 됩니다.
- (선택) 모델 다운로드 가속: `uv pip install --python .venv\Scripts\python.exe hf_transfer`
- 자세한 내용은 [MANUAL.md](MANUAL.md) 1.2절을 참고하세요.

### 4. 실행

```powershell
$env:PYTHONUTF8 = 1
.venv\Scripts\python.exe app.py
```

또는 `start.bat`를 더블클릭하고 **[1] 서버 실행**을 선택합니다.

브라우저에서 `http://127.0.0.1:5000`에 접속합니다. 모델 가중치(약 7.6GB)는 서버 시작 시 백그라운드에서 내려받아 로드되므로 첫 질문도 바로 사용할 수 있습니다. 사전 로드는 `APP_PRELOAD=0`으로 끌 수 있고, 브라우저 자동 열기는 `APP_BROWSER=0`으로 끌 수 있으며, 가중치를 미리 내려받으려면 `dl_qwen35.py`를 실행하세요. 모델 파일은 Hugging Face 라이선스에 따릅니다.

필수 패키지는 `requirements.txt`에 기록되어 있습니다. PDF는 PyMuPDF, xlsx/xls는 pandas와 openpyxl/xlrd를 사용합니다.

질문 뱅크·채점표 생성 로직의 단위 테스트는 아래로 실행합니다 (서버·GPU 불필요).

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## UI 사용

- **질문 입력**: Enter 전송, Shift+Enter 줄바꿈, Esc 생성 중단 (서버의 실제 생성도 즉시 정지되어 GPU가 바로 비워집니다).
- **생성 설정(⚙️)**: 헤더의 ⚙️ 버튼에서 온도(기본 0.7)·최대 생성 길이·말투/역할 프리셋·추론(thinking) 모드를 조정합니다.
- **말투/역할**: 설정 팝업에서 답변 스타일 프리셋을 선택하면 기본 스타일 위에 덧입혀집니다 (기본값: 기본 스타일).
- **모델 사전 로드**: 서버 시작 시 백그라운드로 모델이 자동 로드됩니다. `⚡ 모델 로드` 버튼으로 즉시 로드할 수도 있습니다.
- **질문 뱅크**: 📚 버튼 또는 **Ctrl+B** — 추론 질문 34개(A~G 추론 28 + H 재미있는 추론 6)를 번호순으로 검색·카테고리 필터로 골라 **클릭만으로 질문**하고(답변은 한국어로 강제), 여러 문항을 선택해 **한 번에 순차 실행**하며, 정답 요지를 확인하고, 📊 결과 비교 탭에서 실행 이력(자동 정답률·속도)과 **세트 간 증감(▲▼)** 을 차트로 비교합니다. 정렬(번호·난이도·제목)·난이도(★) 필터를 제공하고, **＋ 내 질문 추가**로 나만의 문항을 저장해 기존 문항과 함께 실행·삭제할 수 있습니다. 질문 본문은 목록에 항상 표시되고, 📊 결과 비교 탭에는 세트별 **정답률 추이 라인 차트**(문항 선택 가능)가 제공됩니다.
- **내보내기**: 📥 버튼에서 현재 대화를 HTML(스타일 포함 단일 문서)·Markdown·JSON으로 저장하거나, **전체 대화를 하나의 Markdown**으로 통합 저장하고, **인쇄/PDF**로 바로 출력하며, **JSON 백업 가져오기**로 대화를 복원할 수 있습니다.
- **PDF/엑셀**: 첨부 버튼 또는 드롭으로 추가. 텍스트가 추출되지 않거나 손상된 문서는 오류를 돌려줍니다.
- **편집**: 사용자 메시지를 더블클릭해 수정하면 해당 지점 뒤 답변을 재생성합니다.
- **대화 관리**: 사이드바에서 새 대화·검색·이름 변경·삭제·고정 기능을 사용할 수 있습니다.
- **파일 드롭**: PDF/엑셀은 문서로 첨부되고, 코드/텍스트 파일은 입력창에 코드블록으로 삽입됩니다.

## Qwen3.5-9B 실험 아이디어

아래는 요약입니다. 절차·기록 템플릿이 있는 전체 실험 모음은 [EXPERIMENTS.md](EXPERIMENTS.md), 모델의 추론력을 파고드는 질문 뱅크는 [REASONING_QUESTIONS.md](REASONING_QUESTIONS.md)를 참고하세요.

- **추론 모드 A/B**: ⚙️ 설정의 thinking 토글을 켜고 끄며 같은 질문 세트의 답변 품질·응답 시간·tok/s를 비교합니다.
- **생성 파라미터 스윕**: 온도(0.2~1.5)와 최대 길이를 바꾸며 창의성/정확도 트레이드오프를 기록합니다.
- **문서 질의 벤치마크**: PDF/엑셀을 첨부해 요약·추출·수치 질의 정확도를 질문 세트로 측정합니다.
- **구조화 출력**: 문서에서 표·JSON 형태로 정보를 추출시키고 스키마 준수율을 확인합니다.
- **다중 대화 일관성**: 긴 대화에서 초기 조건을 재질문해 기억·일관성을 검사합니다.
- **한국어 능력**: 번역·문법 교정·한국어 지식 질문 세트로 프리셋별 품질을 비교합니다.
- **코딩 실험**: 코딩 도우미 프리셋으로 생성·디버깅·리뷰 과제를 풀고 결과물을 HTML로 내보내 기록합니다.
- **양자화 비교**: 4bit와 8bit(bnb) 로딩을 바꿔가며 품질/VRAM/속도를 측정합니다.
- **하드웨어 실험**: `/api/status`의 GPU 메모리와 스트리밍 메트릭(tok/s, elapsed)으로 컨텍스트 길이별 사용량을 기록합니다.

## HTTP API

| 엔드포인트 | 설명 |
|---|---|
| `GET /api/models` | 모델 목록 |
| `GET /api/status` | 로드 상태(백그라운드 로딩 중 여부 포함), GPU 메모리 현황 |
| `POST /api/chat` | `{model, messages, temperature, max_tokens, system?, thinking?}` → SSE (`token`, `done`, `error`, `status`). `system`은 기본 프롬프트에 덧붙일 말투/역할 지시, `thinking`은 Qwen3.5 추론 모드(기본 false) |
| `POST /api/media` | multipart `file` 업로드 → `file_id`, 문서 추출 텍스트 |
| `DELETE /api/media/<file_id>` | 임시 업로드 파일 삭제 |
| `POST /api/preload/<key>` | 모델 동기 사전 로딩(긴 요청 대기 가능) |
| `GET /api/questions` | 질문 뱅크(REASONING_QUESTIONS.md) 문항 목록 JSON |
| `GET /api/results` | 질문 뱅크 실행 이력 요약 (웹 UI 비교 차트용) |

## GPU 메모리

Qwen3.5-9B는 4bit 양자화 시 대략 6GB 내외의 VRAM을 사용합니다 (권장 사양: 12GB VRAM · 32GB RAM 이상). 실제 사용량은 컨텍스트 길이·생성 길이·드라이버와 CUDA 런타임에 따라 달라질 수 있으므로 OOM 방지 보장은 아닙니다. 메모리 여유가 적으면 입력 길이와 최대 생성 토큰을 줄이세요. 모델은 서버 시작 시 백그라운드로 사전 로드되며, `POST /api/preload/qwen35`로 즉시 로딩할 수 있습니다.

## 평가 참고

- Qwen3.5-9B 카드의 벤치마크 수치는 해당 카드의 조건에서 보고한 점수이며 타 카드 점수와 직접 순위 비교에 쓰면 안 됩니다.
- [KMMLU-Redux / KMMLU-Pro 논문](https://arxiv.org/html/2507.08924v2)은 기존 KMMLU의 노이즈/오염 문제를 지적합니다. [Ko-H5 연구](https://aclanthology.org/2024.acl-long.177/)도 사설 테스트셋 및 누수 분석의 중요성을 다룹니다.
- 의미 있는 자체 평가는 같은 질문 세트, 동일한 생성 설정, 고정 모델 revision, blind human scoring으로 해야 합니다. 앱의 tok/s와 답변 길이는 품질 점수가 아닙니다.
