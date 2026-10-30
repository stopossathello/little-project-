@echo off
chcp 65001 >nul
rem 雙擊這個檔案啟動 Telegram bot。bot 執行期間視窗要保持開著。
cd /d "%~dp0"

set "PY=python"
where py >nul 2>nul && set "PY=py"
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo 找不到 Python。請到 https://www.python.org/downloads/ 下載安裝，安裝時要勾選 Add python.exe to PATH。
  pause
  exit /b 1
)

echo 正在安裝或更新需要的套件…
%PY% -m pip install -q --disable-pip-version-check -r requirements.txt
%PY% -m pip install -q --disable-pip-version-check -U yt-dlp

%PY% telegram_bot.py %*
pause
