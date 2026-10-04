@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo Planner Decision Dashboard
echo ========================================

if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
) else (
    set PYTHON=python
)

echo [1/2] 安裝 / 檢查 Python 套件...
%PYTHON% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo 套件安裝失敗，請確認 Python 與網路環境。
    pause
    exit /b 1
)

echo.
echo [2/2] 啟動 Streamlit Dashboard...
echo 開啟後網址通常是 http://localhost:8501
echo 若要停止，回到此視窗按 Ctrl+C。
echo.
%PYTHON% -m streamlit run app\app.py

pause
