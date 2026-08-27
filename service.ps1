param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('start', 'stop')]
    [string]$Action,

    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendRoot = Join-Path $ProjectRoot 'frontend'
$LogRoot = Join-Path $ProjectRoot 'logs'
$BackendUrl = 'http://127.0.0.1:8008/api/health'
$FrontendUrl = 'http://127.0.0.1:5178'

Set-Location $ProjectRoot
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

function Get-ListeningProcessIds {
    param([int]$Port)

    $processIds = @()
    try {
        $processIds = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique)
    } catch {}

    if ($processIds.Count -eq 0) {
        foreach ($line in (& netstat.exe -ano -p tcp 2>$null)) {
            $parts = @(($line.Trim() -split '\s+'))
            if ($parts.Count -lt 5 -or $parts[0] -ne 'TCP' -or $parts[3] -ne 'LISTENING') {
                continue
            }

            $separator = $parts[1].LastIndexOf(':')
            if ($separator -ge 0 -and $parts[1].Substring($separator + 1) -eq [string]$Port) {
                $processIds += [int]$parts[4]
            }
        }
    }

    @($processIds | Where-Object { $_ -gt 0 } | Select-Object -Unique)
}

function Test-HttpOk {
    param([string]$Url)

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Stop-ProcessTree {
    param([int]$ProcessId)

    if ($ProcessId -gt 0 -and (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
        try {
            & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
        } catch {}
    }
}

function Find-Python {
    $runtimeRoot = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
        $(if ($pythonCommand) { $pythonCommand.Source })
        'C:\c\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe'
        (Join-Path $runtimeRoot 'python\python.exe')
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique

    foreach ($candidate in $candidates) {
        try {
            & $candidate -c 'import fastapi, uvicorn' 2>$null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        } catch {}
    }

    throw 'No Python executable with uvicorn installed was found.'
}

function Find-PackageManager {
    $runtimeRoot = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'
    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    $pnpmCommand = Get-Command pnpm.cmd -ErrorAction SilentlyContinue
    $candidates = @(
        $(if ($npmCommand) { $npmCommand.Source })
        $(if ($pnpmCommand) { $pnpmCommand.Source })
        (Join-Path $runtimeRoot 'bin\fallback\pnpm.cmd')
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique

    $packageManager = $candidates | Select-Object -First 1
    if (-not $packageManager) {
        throw 'No npm.cmd or pnpm.cmd executable was found.'
    }

    $packageManager
}

function Save-ProcessId {
    param(
        [string]$Name,
        [System.Diagnostics.Process]$Process
    )

    Set-Content -LiteralPath (Join-Path $LogRoot "$Name.pid") -Value $Process.Id -Encoding Ascii
}

function Stop-Services {
    $processIds = @()

    foreach ($name in @('backend', 'frontend')) {
        $pidFile = Join-Path $LogRoot "$name.pid"
        if (Test-Path $pidFile) {
            $savedProcessId = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($savedProcessId -match '^\d+$') {
                $processIds += [int]$savedProcessId
            }
            Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        }
    }

    foreach ($port in @(8008, 5178)) {
        $processIds += @(Get-ListeningProcessIds $port)
    }

    foreach ($processId in @($processIds | Select-Object -Unique)) {
        Stop-ProcessTree -ProcessId $processId
    }

    Get-Process -Name cpolar -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue

    Start-Sleep -Milliseconds 700
    $remainingPorts = @()
    foreach ($port in @(8008, 5178)) {
        if (@(Get-ListeningProcessIds $port).Count -gt 0) {
            $remainingPorts += $port
        }
    }

    if ($remainingPorts.Count -gt 0) {
        throw "Failed to stop services on ports: $($remainingPorts -join ', ')"
    }

    Write-Host 'tbdemo services stopped.'
}

function Start-Services {
    if (-not (Test-Path (Join-Path $FrontendRoot 'node_modules'))) {
        throw 'Frontend dependencies are missing. Run npm install in the frontend directory.'
    }

    $startedProcesses = @()
    try {
        $backendReady = Test-HttpOk $BackendUrl
        if (-not $backendReady) {
            $backendOwners = @(Get-ListeningProcessIds 8008)
            if ($backendOwners.Count -gt 0) {
                throw "Port 8008 is occupied by process $($backendOwners -join ', '), but the backend health check failed."
            }

            $python = Find-Python
            Write-Host '[1/3] Starting backend on 0.0.0.0:8008...'
            $backendProcess = Start-Process -FilePath $python -ArgumentList @('-m', 'uvicorn', 'backend.app.main:app', '--host', '0.0.0.0', '--port', '8008') -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $LogRoot 'backend.log') -RedirectStandardError (Join-Path $LogRoot 'backend.err.log') -PassThru
            $startedProcesses += $backendProcess
            Save-ProcessId -Name 'backend' -Process $backendProcess
        } else {
            Write-Host '[1/3] Backend is already healthy on port 8008.'
        }

        $frontendReady = Test-HttpOk $FrontendUrl
        if (-not $frontendReady) {
            $frontendOwners = @(Get-ListeningProcessIds 5178)
            if ($frontendOwners.Count -gt 0) {
                throw "Port 5178 is occupied by process $($frontendOwners -join ', '), but the frontend health check failed."
            }

            $packageManager = Find-PackageManager
            Write-Host '[2/3] Starting frontend on 0.0.0.0:5178...'
            $frontendProcess = Start-Process -FilePath $packageManager -ArgumentList @('run', 'dev', '--', '--host', '0.0.0.0', '--port', '5178') -WorkingDirectory $FrontendRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $LogRoot 'frontend.log') -RedirectStandardError (Join-Path $LogRoot 'frontend.err.log') -PassThru
            $startedProcesses += $frontendProcess
            Save-ProcessId -Name 'frontend' -Process $frontendProcess
        } else {
            Write-Host '[2/3] Frontend is already healthy on port 5178.'
        }

        Write-Host '[3/3] Waiting for health checks...'
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            $backendReady = Test-HttpOk $BackendUrl
            $frontendReady = Test-HttpOk $FrontendUrl
            if ($backendReady -and $frontendReady) {
                break
            }
            Start-Sleep -Milliseconds 500
        }

        if (-not $backendReady -or -not $frontendReady) {
            throw "Startup timed out. Check logs in $LogRoot"
        }

        $lanAddress = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
            Select-Object -ExpandProperty IPAddress -First 1
        if (-not $lanAddress) {
            $lanAddress = 'local-ip'
        }

        Write-Host ''
        Write-Host 'Services are ready.'
        Write-Host 'Local URL: http://127.0.0.1:5178'
        Write-Host "LAN URL:   http://${lanAddress}:5178"
        Write-Host 'API docs:  http://127.0.0.1:8008/docs'
        Write-Host "Logs:      $LogRoot"

        if ($OpenBrowser) {
            Start-Process $FrontendUrl | Out-Null
        }
    } catch {
        foreach ($process in $startedProcesses) {
            if ($process -and -not $process.HasExited) {
                Stop-ProcessTree -ProcessId $process.Id
            }
        }
        Remove-Item -LiteralPath (Join-Path $LogRoot 'backend.pid') -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath (Join-Path $LogRoot 'frontend.pid') -Force -ErrorAction SilentlyContinue
        throw
    }
}

try {
    if ($Action -eq 'start') {
        Start-Services
    } else {
        Stop-Services
    }
} catch {
    Write-Error $_.Exception.Message
    exit 1
}

exit 0
