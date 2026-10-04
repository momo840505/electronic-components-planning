Set-Location $PSScriptRoot

$python = "python"
if (Test-Path ".\.venv\Scripts\python.exe") {
    $python = ".\.venv\Scripts\python.exe"
}

Write-Host "[1/2] 安裝 / 檢查 Python 套件..."
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "套件安裝失敗，請確認 Python 與網路環境。" -ForegroundColor Red
    exit 1
}

Write-Host "[2/2] 啟動 Planner Decision Dashboard..."
Write-Host "網址通常是 http://localhost:8501"
& $python -m streamlit run app/app.py
