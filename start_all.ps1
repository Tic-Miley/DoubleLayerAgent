# DoubleLayerAgent 启动脚本
# 启动全部 6 个进程，支持 Ctrl+C 优雅退出
param(
    [switch]$SkipPortCheck
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# 状态文件（供 stop_all.ps1 读取），包含 PID 和端口，消除两脚本间的端口硬编码重复
$STATE_FILE = Join-Path $PSScriptRoot ".running_state.json"

# 全局 PID + 端口列表（本会话内使用）
$Script:LaunchedPIDs  = @()
$Script:LaunchedPorts = @()

function Write-Banner {
    Write-Host "══════════════════════════════════════════" -ForegroundColor Green
    Write-Host "  DoubleLayerAgent — Starting All Services" -ForegroundColor Green
    Write-Host "══════════════════════════════════════════" -ForegroundColor Green
}

function Test-PortInUse {
    param([int]$Port)
    if ($SkipPortCheck) { return $false }
    $client = $null
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $result = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        return $result.AsyncWaitHandle.WaitOne(200)
    } catch {
        return $false
    } finally {
        if ($client) { $client.Dispose() }
    }
}

function Start-Service {
    param(
        [string]$Label,
        [string]$WorkingDirectory,
        [string]$Executable,
        [string[]]$Arguments,
        [string]$Color = "Gray",
        [int]$Port = 0
    )

    if ($Port -gt 0 -and (Test-PortInUse $Port)) {
        Write-Host "  ✗ $Label — port $Port already in use, skipping" -ForegroundColor Red
        return $null
    }

    if (-not (Test-Path $WorkingDirectory)) {
        Write-Host "  ✗ $Label — directory not found: $WorkingDirectory" -ForegroundColor Red
        return $null
    }

    try {
        $proc = Start-Process -NoNewWindow -PassThru $Executable `
            -ArgumentList $Arguments `
            -WorkingDirectory $WorkingDirectory
    } catch {
        Write-Host "  ✗ $Label — failed to start: $_" -ForegroundColor Red
        return $null
    }

    if (-not $proc) {
        Write-Host "  ✗ $Label — Start-Process returned null" -ForegroundColor Red
        return $null
    }

    $Script:LaunchedPIDs  += $proc.Id
    $Script:LaunchedPorts += $Port
    Write-Host "  ✓ $Label (PID $($proc.Id))" -ForegroundColor $Color

    # 等待端口就绪（最多 10 秒），SkipPortCheck 时跳过
    if ($Port -gt 0 -and -not $SkipPortCheck) {
        $waited = 0
        while (-not (Test-PortInUse $Port) -and $waited -lt 10) {
            Start-Sleep -Milliseconds 500
            $waited += 0.5
        }
        if (Test-PortInUse $Port) {
            Write-Host "    → listening on :$Port" -ForegroundColor DarkGray
        } else {
            Write-Host "    ⚠ port :$Port not responding after ${waited}s" -ForegroundColor Yellow
        }
    }

    return $proc
}

function Save-StateFile {
    @{
        pids  = $Script:LaunchedPIDs
        ports = $Script:LaunchedPorts
    } | ConvertTo-Json -Compress | Out-File -FilePath $STATE_FILE -Encoding UTF8 -Force
}

function Remove-StateFile {
    if (Test-Path $STATE_FILE) {
        Remove-Item $STATE_FILE -Force -ErrorAction SilentlyContinue
    }
}

function Stop-AllServices {
    Write-Host "`n Stopping all services..." -ForegroundColor Yellow
    foreach ($procId in $Script:LaunchedPIDs) {
        taskkill /PID $procId /T /F 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  ✗ Killed process tree of PID $procId" -ForegroundColor DarkGray
        } else {
            Write-Host "  - PID $procId already exited or inaccessible" -ForegroundColor DarkGray
        }
    }
    Remove-StateFile
    Write-Host "All services stopped." -ForegroundColor Green
}

# ── 主流程 ──────────────────────────────────────

Write-Banner

# 清理残留状态文件
Remove-StateFile

# 1. SimpleThings :8010
Start-Service -Label "SimpleThings :8010" `
    -WorkingDirectory "simple_things" `
    -Executable "python" `
    -Arguments "-m", "uvicorn", "main:app", "--port", "8010" `
    -Port 8010

# 2. ParkingLotAgent ×3
foreach ($i in @("a","b","c")) {
    $port = if ($i -eq "a") { 8011 } elseif ($i -eq "b") { 8012 } else { 8013 }
    Start-Service -Label "ParkingLotAgent $($i.ToUpper()) :$port" `
        -WorkingDirectory "instances/parking_$i" `
        -Executable "python" `
        -Arguments "-m", "uvicorn", "main:app", "--port", "$port" `
        -Port $port
}

# 3. L1 Backend :8001
Start-Service -Label "L1 Agent :8001" `
    -WorkingDirectory "l1_agent" `
    -Executable "python" `
    -Arguments "-m", "uvicorn", "main:app", "--port", "8001" `
    -Port 8001 `
    -Color "Yellow"

# 4. L1 Frontend :5173
Start-Service -Label "Frontend :5173" `
    -WorkingDirectory "frontend" `
    -Executable "cmd" `
    -Arguments "/c", "npm run dev" `
    -Port 5173 `
    -Color "Cyan"

# 写入状态文件（供 stop_all.ps1 使用）
Save-StateFile

Write-Host "`n All services launched. Press Ctrl+C to stop all." -ForegroundColor Green
Write-Host "  (or run .\stop_all.ps1 from another terminal)`n" -ForegroundColor DarkGray

# ── 等待 Ctrl+C ─────────────────────────────────
try {
    while ($true) {
        Start-Sleep -Seconds 1
    }
} finally {
    # Ctrl+C 触发 finally → 清理所有子进程
    Stop-AllServices
}
