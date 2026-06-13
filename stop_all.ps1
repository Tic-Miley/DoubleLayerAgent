# DoubleLayerAgent 停止脚本
# 读取 .running_state.json，杀掉所有记录的进程树
# 兼容旧的 .running_pids 文件格式
param(
    [switch]$Force  # 即使没有状态文件也尝试按端口杀
)

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$STATE_FILE = Join-Path $PSScriptRoot ".running_state.json"
$PID_FILE   = Join-Path $PSScriptRoot ".running_pids"   # 旧格式兼容

Write-Host "Stopping DoubleLayerAgent services..." -ForegroundColor Yellow

$pids  = @()
$ports = @()

if (Test-Path $STATE_FILE) {
    # ── 新格式：JSON ──────────────────────────────
    try {
        $state = Get-Content $STATE_FILE -Encoding UTF8 -Raw | ConvertFrom-Json
        $pids  = @($state.pids)
        $ports = @($state.ports)
    } catch {
        Write-Host "  ⚠ Failed to parse $STATE_FILE: $_" -ForegroundColor Yellow
    }
} elseif (Test-Path $PID_FILE) {
    # ── 旧格式兼容：纯文本 PID 列表 ──────────────
    $pids = @(Get-Content $PID_FILE -Encoding UTF8 | Where-Object { $_ -match '^\d+$' })
    # 端口回退到默认值
    $ports = @(8010, 8011, 8012, 8013, 8001, 5173)
    Write-Host "  (legacy PID file, using default ports)" -ForegroundColor DarkGray
}

# ── 按 PID 清理 ──────────────────────────────────
foreach ($pid in $pids) {
    taskkill /PID $pid /T /F 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✗ Killed process tree of PID $pid" -ForegroundColor DarkGray
    } else {
        Write-Host "  - PID $pid already exited or inaccessible" -ForegroundColor DarkGray
    }
}

if ($pids.Count -gt 0) {
    Remove-Item $STATE_FILE -Force -ErrorAction SilentlyContinue
    Remove-Item $PID_FILE   -Force -ErrorAction SilentlyContinue
}

# ── Force 模式：按端口兜底清理 ──────────────────
if ($Force -and $ports.Count -gt 0) {
    Write-Host "`nForce mode: killing by port..." -ForegroundColor Yellow
    foreach ($port in $ports) {
        $line = netstat -ano 2>$null | Select-String ":$port " | Select-String "LISTENING"
        if ($line) {
            $pid = ($line -split '\s+')[-1]
            taskkill /PID $pid /T /F 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  ✗ Killed listener on :$port (PID $pid)" -ForegroundColor DarkGray
            }
        }
    }
} elseif ($Force) {
    Write-Host "  No port list available, nothing to force-kill" -ForegroundColor Yellow
}

Write-Host "Done." -ForegroundColor Green
