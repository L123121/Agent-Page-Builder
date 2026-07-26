# 低代码平台 — 一键启动脚本
# 使用方式：在 PowerShell 中运行此脚本

$rootDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   低代码平台 — 启动中..." -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# 启动后端
Write-Host "`n[1/2] 启动后端 (FastAPI)..." -ForegroundColor Yellow
$backendDir = Join-Path $rootDir "backend"
$backendLog = Join-Path $rootDir "backend.log"

$backendProcess = Start-Process -PassThru -WindowStyle Hidden -FilePath "powershell" -ArgumentList "-NoExit", "-Command", "cd '$backendDir'; `$env:PIPENV_VERBOSITY = -1; if (Test-Path venv/Scripts/Activate.ps1) { . .\venv\Scripts\Activate.ps1 }; uvicorn main:app --reload --host 0.0.0.0 --port 8000 2>&1 | Tee-Object -FilePath '$backendLog'"

Start-Sleep -Seconds 3

# 启动前端
Write-Host "[2/2] 启动前端 (Vite)..." -ForegroundColor Yellow
$frontendDir = Join-Path $rootDir "frontend"
$frontendLog = Join-Path $rootDir "frontend.log"

$frontendProcess = Start-Process -PassThru -WindowStyle Hidden -FilePath "powershell" -ArgumentList "-NoExit", "-Command", "cd '$frontendDir'; npm run dev 2>&1 | Tee-Object -FilePath '$frontendLog'"

Start-Sleep -Seconds 2

Write-Host "`n============================================" -ForegroundColor Green
Write-Host "   启动完成！" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host "`n前端编辑器: http://localhost:5173" -ForegroundColor Cyan
Write-Host "后端 API:    http://localhost:8000" -ForegroundColor Cyan
Write-Host "API 文档:    http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host "`n后端日志: $backendLog" -ForegroundColor Gray
Write-Host "前端日志: $frontendLog" -ForegroundColor Gray
Write-Host "`n按任意键终止服务..." -ForegroundColor Yellow

# 等待按键后终止进程
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
Write-Host "`n正在停止服务..." -ForegroundColor Red
Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $frontendProcess.Id -Force -ErrorAction SilentlyContinue
Write-Host "服务已停止" -ForegroundColor Green