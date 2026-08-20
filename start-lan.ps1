# start-lan.ps1 - 局域网一键启动：后端 0.0.0.0:8008 + 前端 0.0.0.0:5178
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# 找 Python：独立安装 -> PATH -> WorkBuddy 备用
$Candidates = @(
  (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
  (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
  'C:\c\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
) | Where-Object { $_ -and (Test-Path $_) }
$PY = $Candidates | Select-Object -First 1
if (-not $PY) {
  Write-Host '[错误] 未找到 Python，请先安装 Python 3.12'
  Read-Host '按回车退出'
  exit 1
}
if (-not (Test-Path (Join-Path $Root 'frontend\node_modules'))) {
  Write-Host '[错误] 前端依赖未安装，请先运行: cd frontend && npm install'
  Read-Host '按回车退出'
  exit 1
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root 'logs') | Out-Null

function Test-Port([int]$port) { [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) }

if (Test-Port 8008) {
  Write-Host '[提示] 后端已在运行 (8008)，跳过启动'
} else {
  Write-Host '[1/3] 启动后端 (0.0.0.0:8008) ...'
  Start-Process -FilePath $PY -ArgumentList '-m','uvicorn','backend.app.main:app','--reload','--host','0.0.0.0','--port','8008' -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Root 'logs\backend.log') -RedirectStandardError (Join-Path $Root 'logs\backend.err.log')
}

if (Test-Port 5178) {
  Write-Host '[提示] 前端已在运行 (5178)，跳过启动'
} else {
  Write-Host '[2/3] 启动前端 (0.0.0.0:5178) ...'
  Start-Process -FilePath 'npm.cmd' -ArgumentList 'run','dev' -WorkingDirectory (Join-Path $Root 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Root 'logs\frontend.log') -RedirectStandardError (Join-Path $Root 'logs\frontend.err.log')
}

Write-Host '[3/3] 等待服务就绪 ...'
$ok = $false
$beOk = $false
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 500
  try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5178' -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) { $ok = $true }
  } catch {}
  try {
    $b = Invoke-WebRequest -Uri 'http://127.0.0.1:8008/api/health' -UseBasicParsing -TimeoutSec 2
    if ($b.StatusCode -eq 200) { $beOk = $true }
  } catch {}
  if ($ok -and $beOk) { break }
}
if (-not $beOk) {
  Write-Host '[错误] 后端启动失败，请看 logsackend.err.log'
  Read-Host '按回车退出'
  exit 1
}
$lan = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1).IPAddress
if (-not $lan) { $lan = '本机IP' }

Write-Host ''
Write-Host '=============================================='
if ($ok) { Write-Host ' 启动成功！' } else { Write-Host ' 启动中，稍后刷新浏览器即可' }
Write-Host " 本机访问:  http://127.0.0.1:5178"
Write-Host " 同事访问:  http://${lan}:5178"
Write-Host " 接口文档:  http://127.0.0.1:8008/docs"
Write-Host " 日志目录:  logs\"
Write-Host " 停止服务:  双击 stop.bat"
Write-Host '=============================================='
Write-Host ''
if ($ok) { Start-Process 'http://127.0.0.1:5178' }
Start-Sleep -Seconds 8