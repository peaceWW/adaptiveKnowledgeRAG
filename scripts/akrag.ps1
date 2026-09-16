# Adaptive Knowledge RAG — Windows 项目管理脚本
# 用法: .\scripts\akrag.ps1 <deploy|start|stop|restart|status|infra-up|infra-down|logs> [-WithInfra] [-All]

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("deploy", "start", "stop", "restart", "status", "infra-up", "infra-down", "logs")]
    [string]$Command = "status",
    [switch]$WithInfra,
    [switch]$All
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RunDir = Join-Path $Root ".run"
$FrontendDir = Join-Path $Root "frontend"
$BackendPidFile = Join-Path $RunDir "backend.pid"
$FrontendPidFile = Join-Path $RunDir "frontend.pid"
$BackendPort = 8000
$FrontendPort = 5173

function Write-Info($message) { Write-Host "[akrag] $message" -ForegroundColor Cyan }
function Write-Ok($message) { Write-Host "[akrag] $message" -ForegroundColor Green }
function Write-Warn($message) { Write-Host "[akrag] $message" -ForegroundColor Yellow }
function Write-Err($message) { Write-Host "[akrag] $message" -ForegroundColor Red }

function Add-PathDir([string]$Dir) {
    if ($Dir -and (Test-Path $Dir) -and ($env:PATH -notlike "*$Dir*")) {
        $env:PATH = "$Dir;$env:PATH"
    }
}

function Initialize-ToolPath {
    $pythonRoot = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path $pythonRoot) {
        Get-ChildItem $pythonRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            Add-PathDir $_.FullName
            Add-PathDir (Join-Path $_.FullName "Scripts")
        }
    }
    @(
        "$env:USERPROFILE\.local\bin",
        "$env:USERPROFILE\.cargo\bin",
        "$env:LOCALAPPDATA\uv",
        "C:\Program Files\nodejs",
        "$env:APPDATA\npm"
    ) | ForEach-Object { Add-PathDir $_ }
}

function Get-PythonExe {
    $pythonRoot = Join-Path $env:LOCALAPPDATA "Programs\Python"
    if (Test-Path $pythonRoot) {
        $found = Get-ChildItem $pythonRoot -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "python.exe" } |
            Where-Object { Test-Path $_ } |
            Select-Object -First 1
        if ($found) { return $found }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike "*WindowsApps*") {
        return $cmd.Source
    }
    return $null
}

function Ensure-Uv {
    if (Test-CommandExists "uv") { return }
    Write-Info "未找到 uv，尝试自动安装"
    $python = Get-PythonExe
    if ($python) {
        & $python -m pip install uv
        Initialize-ToolPath
        if (Test-CommandExists "uv") { return }
    }
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        Initialize-ToolPath
    } catch {
        Write-Warn $_.Exception.Message
    }
    if (-not (Test-CommandExists "uv")) {
        throw "未找到 uv。请先安装: https://docs.astral.sh/uv/getting-started/installation/"
    }
}

Initialize-ToolPath

function Ensure-RunDir {
    New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
}

function Test-CommandExists([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-PortListening([int]$Port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        return [bool]$conn
    } catch {
        $client = New-Object System.Net.Sockets.TcpClient
        try {
            $client.Connect("127.0.0.1", $Port)
            $client.Close()
            return $true
        } catch {
            return $false
        }
    }
}

function Get-PortPids([int]$Port) {
    $pids = @()
    try {
        $pids = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique)
    } catch {
        $pids = @()
    }
    return $pids
}

function Stop-Port([int]$Port) {
    foreach ($procId in Get-PortPids $Port) {
        if ($procId -and $procId -ne 0) {
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}

function Stop-PidFile([string]$PidFile) {
    if (Test-Path $PidFile) {
        $procId = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
        if ($procId) {
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
}

function Test-Docker {
    if (-not (Test-CommandExists "docker")) { return $false }
    $out = Join-Path $env:TEMP "akrag-docker-info.out"
    $err = Join-Path $env:TEMP "akrag-docker-info.err"
    try {
        $proc = Start-Process -FilePath "docker" -ArgumentList @("info") -WindowStyle Hidden -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
        if (-not $proc.WaitForExit(4000)) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            return $false
        }
        return ($proc.ExitCode -eq 0)
    } catch {
        return $false
    }
}

function Invoke-Compose([string[]]$ComposeArgs) {
    Push-Location $Root
    try {
        & docker compose @ComposeArgs
        if ($LASTEXITCODE -ne 0) {
            & docker-compose @ComposeArgs
        }
    } finally {
        Pop-Location
    }
}

function Set-SqliteDatabaseUrl([string]$EnvPath) {
    $text = Get-Content $EnvPath -Raw -Encoding UTF8
    if ($text -notmatch 'DATABASE_URL=sqlite') {
        $text = $text -replace 'DATABASE_URL=.*', 'DATABASE_URL=sqlite+aiosqlite:///./data/akrag.db'
        Set-Content -Path $EnvPath -Value $text -Encoding UTF8
        Write-Info "未检测到 Docker，已将 DATABASE_URL 设为 SQLite"
    }
}

function Ensure-Env([bool]$PreferSqlite) {
    $envPath = Join-Path $Root ".env"
    $example = Join-Path $Root ".env.example"
    if (-not (Test-Path $envPath)) {
        if (-not (Test-Path $example)) {
            throw "缺少 .env.example，无法生成配置文件"
        }
        Copy-Item $example $envPath
        Write-Info "已从 .env.example 创建 .env"
    }
    if ($PreferSqlite) {
        Set-SqliteDatabaseUrl $envPath
    }
}

function Invoke-Deploy {
    Write-Info "开始部署 / 安装依赖"
    Ensure-Uv
    if (-not (Test-CommandExists "npm")) {
        throw "未找到 npm / Node.js。请安装 Node.js 18+"
    }

    $useInfra = $WithInfra.IsPresent -and (Test-Docker)
    if ($WithInfra.IsPresent -and -not (Test-Docker)) {
        Write-Warn "已指定 -WithInfra，但 Docker 不可用，将按本地降级模式安装"
    }

    Ensure-Env -PreferSqlite (-not $useInfra)
    New-Item -ItemType Directory -Force -Path (Join-Path $Root "data") | Out-Null

    Write-Info "安装 Python 依赖 (uv sync)"
    Push-Location $Root
    try {
        uv sync
        if ($LASTEXITCODE -ne 0) { throw "uv sync 失败" }
        Write-Info "安装前端依赖 (npm install)"
        Push-Location $FrontendDir
        try {
            npm install
            if ($LASTEXITCODE -ne 0) { throw "npm install 失败" }
        } finally {
            Pop-Location
        }
    } finally {
        Pop-Location
    }

    if ($useInfra) {
        Invoke-InfraUp
    }

    Write-Ok "部署完成。接下来执行: .\scripts\akrag.ps1 start"
}

function Invoke-InfraUp {
    if (-not (Test-Docker)) {
        throw "Docker 不可用，无法启动基础设施（Postgres/Qdrant/MinIO/ES/Neo4j/Redis）"
    }
    Write-Info "启动 docker compose 基础设施"
    Invoke-Compose @("up", "-d")
    Write-Ok "基础设施已启动"
}

function Invoke-InfraDown {
    if (-not (Test-Docker)) {
        Write-Warn "Docker 不可用，跳过 infra-down"
        return
    }
    Write-Info "停止 docker compose 基础设施"
    Invoke-Compose @("down")
    Write-Ok "基础设施已停止"
}

function Start-Backend {
    if (Test-PortListening $BackendPort) {
        Write-Warn "后端已在端口 $BackendPort 运行"
        return
    }
    Ensure-Uv
    Ensure-RunDir
    $uv = (Get-Command uv).Source
    $log = Join-Path $RunDir "backend.log"
    $err = Join-Path $RunDir "backend.err"
    $proc = Start-Process -FilePath $uv -ArgumentList @(
        "run", "uvicorn", "app.main:app",
        "--app-dir", "backend",
        "--host", "0.0.0.0",
        "--port", "$BackendPort"
    ) -WorkingDirectory $Root -RedirectStandardOutput $log -RedirectStandardError $err -WindowStyle Hidden -PassThru
    $proc.Id | Set-Content $BackendPidFile
    Write-Info "后端已启动 PID=$($proc.Id)，日志 $log"
}

function Start-Frontend {
    if (Test-PortListening $FrontendPort) {
        Write-Warn "前端已在端口 $FrontendPort 运行"
        return
    }
    if (-not (Test-CommandExists "npm")) {
        throw "未找到 npm，请先执行 deploy"
    }
    Ensure-RunDir
    $log = Join-Path $RunDir "frontend.log"
    $cmd = "npm run dev > `"$log`" 2>&1"
    $proc = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $cmd) -WorkingDirectory $FrontendDir -WindowStyle Hidden -PassThru
    $proc.Id | Set-Content $FrontendPidFile
    Write-Info "前端已启动 PID=$($proc.Id)，日志 $log"
}

function Wait-Health {
    $ok = $false
    for ($i = 0; $i -lt 40; $i++) {
        try {
            $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/health" -TimeoutSec 2
            if ($resp.status -eq "ok") { $ok = $true; break }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if ($ok) {
        Write-Ok "后端健康检查通过 http://127.0.0.1:$BackendPort/health"
    } else {
        Write-Warn "后端尚未就绪，请查看 .run/backend.log / .run/backend.err"
    }
}

function Invoke-Start {
    if ($WithInfra.IsPresent) {
        if (Test-Docker) { Invoke-InfraUp } else { Write-Warn "Docker 不可用，跳过基础设施，应用将降级运行" }
    }
    Start-Backend
    Start-Frontend
    Wait-Health
    Write-Ok "应用已启动（监听 0.0.0.0，局域网可访问）"
    Write-Host "  前端:  http://localhost:$FrontendPort/  （或 http://<本机IP>:$FrontendPort/）"
    Write-Host "  后端:  http://0.0.0.0:$BackendPort/"
    Write-Host "  API:   http://localhost:$BackendPort/docs"
}

function Invoke-Stop {
    Write-Info "停止应用进程"
    Stop-PidFile $FrontendPidFile
    Stop-PidFile $BackendPidFile
    Stop-Port $FrontendPort
    Stop-Port $BackendPort
    if ($All.IsPresent) {
        Invoke-InfraDown
    }
    Write-Ok "应用已停止"
}

function Invoke-Status {
    $backend = if (Test-PortListening $BackendPort) { "running" } else { "stopped" }
    $frontend = if (Test-PortListening $FrontendPort) { "running" } else { "stopped" }
    Write-Host "backend  : $backend   http://0.0.0.0:$BackendPort/"
    Write-Host "frontend : $frontend   http://0.0.0.0:$FrontendPort/"
    if (Test-CommandExists "docker") {
        Write-Host "docker   : installed"
    } else {
        Write-Host "docker   : not installed (SQLite / in-memory fallback)"
    }
}

function Invoke-Logs {
    Ensure-RunDir
    Write-Host "---- backend.log ----"
    if (Test-Path (Join-Path $RunDir "backend.log")) {
        Get-Content (Join-Path $RunDir "backend.log") -Tail 40
    } else {
        Write-Host "(empty)"
    }
    Write-Host "---- frontend.log ----"
    if (Test-Path (Join-Path $RunDir "frontend.log")) {
        Get-Content (Join-Path $RunDir "frontend.log") -Tail 40
    } else {
        Write-Host "(empty)"
    }
}

Set-Location $Root
switch ($Command) {
    "deploy" { Invoke-Deploy }
    "start" { Invoke-Start }
    "stop" { Invoke-Stop }
    "restart" { Invoke-Stop; Start-Sleep -Seconds 1; Invoke-Start }
    "status" { Invoke-Status }
    "infra-up" { Invoke-InfraUp }
    "infra-down" { Invoke-InfraDown }
    "logs" { Invoke-Logs }
}
