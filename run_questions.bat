@echo off
setlocal
chcp 65001 >nul
title Qwen3.5-9B 질문 뱅크 / 채점표 생성
cd /d "%~dp0"
set PYTHONUTF8=1

:menu
cls
echo ============================================
echo   Qwen3.5-9B 질문 뱅크 / 채점표 생성
echo ============================================
echo   [1] 빠른 실행 - 핵심 6문항 (thinking OFF/ON)
echo   [2] 전체 실행 - 28문항 (thinking OFF/ON)
echo   [3] 특정 문항만 (예: Q5,Q9)
echo   [4] 결과 폴더 열기
echo   [5] 최신 HTML 채점표 브라우저에서 열기
echo   [0] 종료
echo ============================================
echo   ※ 서버가 실행 중이어야 합니다 (start.bat [1]).
echo      없으면 지금 시작할지 물어봅니다.
echo   ※ 진행 상황이 실시간으로 표시되고,
echo      끝나면 results 폴더에 채점표가 생깁니다.
echo ============================================
set "sel="
set /p "sel=선택 >> "
if "%sel%"=="" goto menu
if "%sel:~0,1%"=="1" goto quick
if "%sel:~0,1%"=="2" goto full
if "%sel:~0,1%"=="3" goto custom
if "%sel:~0,1%"=="4" goto openres
if "%sel:~0,1%"=="5" goto openhtml
if "%sel:~0,1%"=="0" exit /b 0
goto menu

:quick
call :ensure_server
if errorlevel 1 goto menu
echo.
echo   핵심 6문항을 실행합니다 (thinking OFF/ON, max_tokens 2048).
echo   thinking ON은 문항당 수 분이 걸릴 수 있습니다...
echo.
.venv\Scripts\python.exe run_questions.py --quick --max-tokens 2048
if errorlevel 1 (
    echo.
    echo [ERROR] 실행에 실패했습니다. 위 메시지를 확인하세요.
)
call :pause2
goto menu

:full
call :ensure_server
if errorlevel 1 goto menu
echo.
echo   전체 28문항을 실행합니다 (thinking OFF/ON, max_tokens 4096).
echo   GPU 성능에 따라 1시간 이상 걸릴 수 있습니다...
echo.
.venv\Scripts\python.exe run_questions.py --max-tokens 4096
if errorlevel 1 (
    echo.
    echo [ERROR] 실행에 실패했습니다. 위 메시지를 확인하세요.
)
call :pause2
goto menu

:custom
call :ensure_server
if errorlevel 1 goto menu
set "ids="
set /p "ids=문항 ID 입력 (예: Q5,Q9): "
if "%ids%"=="" goto menu
echo.
.venv\Scripts\python.exe run_questions.py --ids "%ids%"
if errorlevel 1 (
    echo.
    echo [ERROR] 실행에 실패했습니다. 문항 ID를 확인하세요 - Q1~Q28
)
call :pause2
goto menu

:openres
if not exist results mkdir results
explorer results
goto menu

:: 최신 채점표 HTML을 기본 브라우저에서 연다.
:openhtml
if not exist results mkdir results
set "latest="
for /f "delims=" %%f in ('dir /b /o-d results\score_sheet_*.html 2^>nul') do if not defined latest set "latest=%%f"
if not defined latest goto nohtml
start "" "results\%latest%"
echo   [OK] results\%latest% 파일을 열었습니다.
call :pause2
goto menu

:nohtml
echo   아직 생성된 HTML 채점표가 없습니다.
echo   먼저 [1]~[3] 으로 질문 뱅크를 실행하세요.
call :pause2goto menu

:: 서버가 살아있는지 확인하고, 없으면 (선택 시) 새 창에서 시작한다.
:ensure_server
.venv\Scripts\python.exe -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:5000/api/status',timeout=2)" >nul 2>&1
if not errorlevel 1 exit /b 0
echo.
echo   서버가 실행 중이지 않습니다 (http://127.0.0.1:5000).
set "ans="
set /p "ans=새 창에서 서버를 시작할까요? (y/N): "
if /i not "%ans:~0,1%"=="y" exit /b 1
start "Qwen3.5-9B 서버" cmd /k ".venv\Scripts\python.exe app.py"
echo   서버가 준비될 때까지 기다립니다 (최초 실행이면 모델 다운로드로 수 분 걸릴 수 있습니다)...
set /a tries=0
:waitloop
set /a tries+=1
timeout /t 2 /nobreak >nul
.venv\Scripts\python.exe -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:5000/api/status',timeout=2)" >nul 2>&1
if not errorlevel 1 exit /b 0
if %tries% GEQ 30 (
    echo   서버 시작 대기 시간이 초과되었습니다.
    echo   start.bat 에서 [1] 서버 실행을 먼저 해 주세요.
    exit /b 1
)
goto waitloop

:pause2
set "x="
set /p "x=계속하려면 Enter를 누르세요... "
goto :eof
