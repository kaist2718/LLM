@echo off
setlocal
chcp 65001 >nul
title Qwen3.5-9B 로컬 채팅 서버
cd /d "%~dp0"
set PYTHONUTF8=1

:menu
cls
echo ============================================
echo   Qwen3.5-9B 로컬 채팅 서버
echo ============================================
echo   [1] 서버 실행
echo   [2] 정리: 로그 파일 (*.log)
echo   [3] 정리: __pycache__
echo   [4] 정리: 내보내기 결과물
echo        (chat_*.*, all_chats_*.json)
echo   [5] 정리: 모델 캐시 (사전 양자화 + Qwen3.5-9B)
echo        (삭제 후 재실행 시 다시 받음)
echo   [6] 전체 정리 (2~5)
echo   [7] 질문 뱅크 / 채점표 생성 (run_questions.bat)
echo   [0] 종료
echo ============================================
echo   프로젝트 파일: app.py, index.html, README.md,
echo   requirements.txt, dl_qwen35.py, start.bat,
echo   run_questions.py/bat, MANUAL.md,
echo   EXPERIMENTS.md, REASONING_QUESTIONS.md
echo ============================================
set "sel="
set /p "sel=선택 >> "
if "%sel%"=="" goto menu
if "%sel:~0,1%"=="1" goto run
if "%sel:~0,1%"=="2" goto clean_logs
if "%sel:~0,1%"=="3" goto clean_pycache
if "%sel:~0,1%"=="4" goto clean_results
if "%sel:~0,1%"=="5" goto clean_models
if "%sel:~0,1%"=="6" goto clean_all
if "%sel:~0,1%"=="7" goto run_q
if "%sel:~0,1%"=="0" exit /b 0
goto menu

:run
echo.
echo   Server : http://127.0.0.1:5000
echo   브라우저가 자동으로 열립니다...
echo   (자동으로 열리지 않으면 위 URL을 직접 여세요)
echo.
echo   중지: Ctrl+C
echo.
.venv\Scripts\python.exe app.py
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] 서버 시작 실패. .venv 폴더가 있는지 확인하세요.
    echo.
    call :pause2
)
goto menu

:run_q
call run_questions.bat
goto menu

:clean_logs
call :confirm "로그 파일(*.log)을 삭제할까요?"
if errorlevel 1 goto menu
del /q *.log 2>nul
echo [OK] 로그 파일을 삭제했습니다.
call :pause2
goto menu

:clean_pycache
call :confirm "__pycache__ 폴더를 삭제할까요?"
if errorlevel 1 goto menu
if exist __pycache__ rd /s /q __pycache__
echo [OK] __pycache__를 삭제했습니다.
call :pause2
goto menu

:clean_results
call :confirm "내보내기 결과물(chat_*.*, all_chats_*.json)을 삭제할까요?"
if errorlevel 1 goto menu
del /q chat_*.html chat_*.md chat_*.json all_chats_*.json 2>nul
echo [OK] 내보내기 결과물을 삭제했습니다.
call :pause2
goto menu

:clean_models
set "HFHUB=%USERPROFILE%\.cache\huggingface\hub"
call :confirm "Qwen3.5-9B 모델 캐시를 삭제할까요?"
if errorlevel 1 goto menu
if exist "%HFHUB%\models--Qwen--Qwen3.5-9B" rd /s /q "%HFHUB%\models--Qwen--Qwen3.5-9B"
if exist "%HFHUB%\models--rectx--Qwen3.5-9B-bnb-4bit" rd /s /q "%HFHUB%\models--rectx--Qwen3.5-9B-bnb-4bit"
if exist models\qwen35 rd /s /q models\qwen35
echo [OK] 모델 캐시를 삭제했습니다.
call :pause2
goto menu

:clean_all
call :confirm "로그, __pycache__, 내보내기 결과물, 모델 캐시를 삭제할까요?"
if errorlevel 1 goto menu
del /q *.log 2>nul
if exist __pycache__ rd /s /q __pycache__
del /q chat_*.html chat_*.md chat_*.json all_chats_*.json 2>nul
set "HFHUB=%USERPROFILE%\.cache\huggingface\hub"
if exist "%HFHUB%\models--Qwen--Qwen3.5-9B" rd /s /q "%HFHUB%\models--Qwen--Qwen3.5-9B"
if exist "%HFHUB%\models--rectx--Qwen3.5-9B-bnb-4bit" rd /s /q "%HFHUB%\models--rectx--Qwen3.5-9B-bnb-4bit"
if exist models\qwen35 rd /s /q models\qwen35
echo [OK] 전체 정리 완료.
call :pause2
goto menu

:confirm
set "ans="
set /p "ans=%~1 (y/N): "
if /i "%ans:~0,1%"=="y" exit /b 0
exit /b 1

:pause2
set "x="
set /p "x=계속하려면 Enter를 누르세요... "
goto :eof
