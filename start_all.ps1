# DoubleLayerAgent 启动脚本
# 启动全部 6 个进程

Set-Location $PSScriptRoot

Write-Host "Starting DoubleLayerAgent..." -ForegroundColor Green

# 1. SimpleThings :8010
Start-Process -NoNewWindow python `
    -ArgumentList "-m", "uvicorn", "main:app", "--port", "8010" `
    -WorkingDirectory simple_things
Write-Host "SimpleThings :8010" -ForegroundColor Gray
Start-Sleep -Seconds 1

# 2. ParkingLotAgent instances
foreach ($i in @("a","b","c")) {
    $port = if ($i -eq "a") {8011} elseif ($i -eq "b") {8012} else {8013}
    Start-Process -NoNewWindow python `
        -ArgumentList "-m", "uvicorn", "main:app", "--port", "$port" `
        -WorkingDirectory "instances/parking_$i"
    Write-Host "ParkingLotAgent $($i.ToUpper()) :$port" -ForegroundColor Gray
    Start-Sleep -Seconds 1
}

# 3. L1 Backend :8001
Start-Process -NoNewWindow python `
    -ArgumentList "-m", "uvicorn", "main:app", "--port", "8001" `
    -WorkingDirectory l1_agent
Write-Host "L1 Agent :8001" -ForegroundColor Yellow

# 4. L1 Frontend :5173
# npm on Windows is a .cmd script, not a Win32 binary — must invoke via cmd /c
Start-Process -NoNewWindow cmd `
    -ArgumentList "/c", "npm run dev" `
    -WorkingDirectory frontend
Write-Host "Frontend :5173" -ForegroundColor Cyan

Write-Host "`nAll services started. Press Ctrl+C to stop all." -ForegroundColor Green
