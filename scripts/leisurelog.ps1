# LeisureLog 启动 / 停止 / 开机自启
# 用法（一般直接双击项目根目录的 .bat 即可）：
#   leisurelog.ps1 -Action start|stop|restart|status|enable-autostart|disable-autostart [-Port 8001] [-NoBrowser]
param(
    [ValidateSet('start', 'stop', 'restart', 'status', 'enable-autostart', 'disable-autostart')]
    [string]$Action = 'start',
    [int]$Port = 8001,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$Url = "http://127.0.0.1:$Port"
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$LogDir = Join-Path $Root 'data\logs'
$Shortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'LeisureLog.lnk'

function Test-Running {
    try {
        $health = Invoke-RestMethod -Uri "$Url/health" -TimeoutSec 2
        return $health.status -eq 'ok'
    } catch {
        return $false
    }
}

function Get-PortOwners {
    $owners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    return @($owners | Where-Object { $_ -gt 0 })
}

function Start-LeisureLog {
    if (Test-Running) {
        Write-Host "LeisureLog 已经在运行：$Url"
        return $true
    }
    if ((Get-PortOwners).Count -gt 0) {
        Write-Host "端口 $Port 已被占用，但不是正常运行的 LeisureLog。"
        Write-Host "可能是旧版本或其他程序，请先运行 stop-leisurelog.bat，或检查 data\logs\server.err.log。"
        return $false
    }
    if (-not (Test-Path -LiteralPath $Python)) {
        Write-Host "找不到 $Python"
        Write-Host '请先按 README 的“快速运行”创建虚拟环境并安装依赖。'
        return $false
    }
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $arguments = @('-m', 'uvicorn', 'leisurelog.main:create_app', '--factory',
                   '--host', '127.0.0.1', '--port', "$Port")
    Start-Process -FilePath $Python -ArgumentList $arguments -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir 'server.out.log') `
        -RedirectStandardError (Join-Path $LogDir 'server.err.log') | Out-Null
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-Running) {
            Write-Host "LeisureLog 已启动：$Url"
            return $true
        }
    }
    Write-Host '30 秒内没有启动成功。请查看 data\logs\server.err.log 里的错误信息。'
    Write-Host '如果提示数据库版本不对，需要先运行：.\.venv\Scripts\alembic.exe upgrade head'
    return $false
}

function Stop-LeisureLog {
    $owners = Get-PortOwners
    if ($owners.Count -eq 0) {
        Write-Host "端口 $Port 上没有运行中的服务。"
        return $true
    }
    if (-not (Test-Running)) {
        Write-Host "端口 $Port 上的程序不是 LeisureLog（或者没有响应），为安全起见不自动结束它。"
        foreach ($id in $owners) {
            $process = Get-Process -Id $id -ErrorAction SilentlyContinue
            if ($process) { Write-Host "  进程 $id：$($process.ProcessName)" }
        }
        return $false
    }
    foreach ($id in $owners) {
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 250
        if ((Get-PortOwners).Count -eq 0) {
            Write-Host 'LeisureLog 已停止。'
            return $true
        }
    }
    Write-Host '停止超时，请稍后再试。'
    return $false
}

function Enable-Autostart {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Shortcut)
    $link.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $link.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Action start -Port $Port -NoBrowser"
    $link.WorkingDirectory = $Root
    $link.WindowStyle = 7
    $link.Description = 'LeisureLog 登录后自动启动'
    $link.Save()
    Write-Host '已开启开机自启：登录 Windows 后，LeisureLog 会在后台自动运行（不打开浏览器）。'
    Write-Host "启动项位置：$Shortcut"
    Write-Host '提示：ActivityWatch 也需要开机自启，可以在它的托盘图标设置里打开。'
    return $true
}

function Disable-Autostart {
    if (Test-Path -LiteralPath $Shortcut) {
        Remove-Item -LiteralPath $Shortcut -Force
        Write-Host '已关闭开机自启。'
    } else {
        Write-Host '开机自启本来就是关闭的。'
    }
    return $true
}

switch ($Action) {
    'start' {
        $ok = Start-LeisureLog
        if ($ok -and -not $NoBrowser) { Start-Process $Url }
    }
    'stop' { $ok = Stop-LeisureLog }
    'restart' {
        $ok = Stop-LeisureLog
        if ($ok) { $ok = Start-LeisureLog }
        if ($ok -and -not $NoBrowser) { Start-Process $Url }
    }
    'status' {
        $ok = $true
        if (Test-Running) { Write-Host "运行中：$Url" } else { Write-Host '没有运行。' }
        if (Test-Path -LiteralPath $Shortcut) { Write-Host '开机自启：已开启' } else { Write-Host '开机自启：未开启' }
    }
    'enable-autostart' { $ok = Enable-Autostart }
    'disable-autostart' { $ok = Disable-Autostart }
}

if ($ok) { exit 0 } else { exit 1 }
