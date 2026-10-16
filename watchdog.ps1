# 后端守护：检测 8008 健康检查失败时自动重启服务
# 用法：
#   单次检测：powershell -File D:\demo\watchdog.ps1
#   常驻循环：powershell -File D:\demo\watchdog.ps1 -Loop   （由 start.bat 拉起）

param([switch]$Loop)

$logFile = 'D:\demo\logs\watchdog.log'
$healthUrl = 'http://127.0.0.1:8008/api/health'
$checkIntervalSeconds = 30

function Write-Log([string]$msg) {
    "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) $msg" | Add-Content -LiteralPath $logFile
    # 只保留最后 2000 行
    $lines = Get-Content -LiteralPath $logFile -ErrorAction SilentlyContinue
    if ($lines.Count -gt 2000) { $lines | Select-Object -Last 2000 | Set-Content -LiteralPath $logFile }
}

function Test-Health {
    try {
        $r = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 5
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Invoke-Recovery {
    if (Test-Health) { return $true }

    Write-Log '后端健康检查失败，尝试自动恢复...'

    $listening = $false
    try {
        $listening = @(Get-NetTCPConnection -State Listen -LocalPort 8008 -ErrorAction Stop).Count -gt 0
    } catch {}

    if ($listening) {
        # 端口被占但健康检查失败：杀掉僵死进程再重启
        try {
            Get-NetTCPConnection -State Listen -LocalPort 8008 -ErrorAction Stop |
                Select-Object -ExpandProperty OwningProcess -Unique |
                ForEach-Object { taskkill.exe /PID $_ /T /F 2>$null | Out-Null }
            Start-Sleep -Seconds 2
        } catch {}
        Write-Log '已终止 8008 端口上的僵死进程'
    }

    # 用现有 service.ps1 拉起（它自己会处理 pid/日志轮转）
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'D:\demo\service.ps1' -Action start 2>&1 |
        ForEach-Object { "$_" } | Add-Content -LiteralPath $logFile

    Start-Sleep -Seconds 10
    if (Test-Health) {
        Write-Log '恢复成功，后端已重新可用'
        return $true
    }
    Write-Log '恢复失败，等待下一轮检测'
    return $false
}

if ($Loop) {
    # 防止重复启动多个守护实例
    $mutex = New-Object System.Threading.Mutex($false, 'Global\TaobaoDemoBackendWatchdog')
    if (-not $mutex.WaitOne(0)) { exit 0 }
    Write-Log '守护进程启动（每 30 秒自检一次）'
    while ($true) {
        Invoke-Recovery | Out-Null
        Start-Sleep -Seconds $checkIntervalSeconds
    }
} else {
    Invoke-Recovery | Out-Null
    exit 0
}
