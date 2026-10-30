param(
    [switch]$NoBrowser
)

# 本文件由 codex 辅助生成（外围模块）
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot
. (Join-Path $projectRoot "scripts\python_import_check.ps1")

$voiceLauncher = $null
$voiceSessionFile = Join-Path $env:TEMP ("wanderer-game-voice-" + [guid]::NewGuid().ToString("N") + ".json")

$gamePort = $null
foreach ($candidatePort in (8000..8010)) {
    $candidateUrl = "http://127.0.0.1:$candidatePort"
    $existingGame = $false
    try {
        # Use the health contract only: older game builds may not expose the newer OpenAPI URL.
        $health = Invoke-RestMethod -Uri "$candidateUrl/api/health" -TimeoutSec 2
        if ($health.data.status -eq "ok" -and $health.data.version -ne "0.2.0") {
            Write-Host "检测到旧版游戏服务：$candidateUrl（版本 $($health.data.version)）；新版将使用其他可用端口启动。" -ForegroundColor Yellow
        }
        $existingGame = (
            $health.data.status -eq "ok" -and
            $health.data.mode -in @("offline", "live") -and
            $health.data.version -eq "0.2.0"
        )
    } catch {
        $existingGame = $false
    }

    if ($existingGame) {
        $gamePort = $candidatePort
        $gameUrl = $candidateUrl
        Write-Host "游戏服务已在运行：$gameUrl"
        Write-Host "如刚修改了 .env 配置，请关闭原服务窗口后重新启动，配置才会生效。"
        if (-not $NoBrowser) {
            Start-Process $gameUrl
        }
        return
    }

    $portProbe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $candidatePort)
    try {
        $portProbe.Start()
        $portProbe.Stop()
        $gamePort = $candidatePort
        break
    } catch {
        try { $portProbe.Stop() } catch { }
    }
}

if ($null -eq $gamePort) {
    throw "端口 8000 至 8010 均不可用。请关闭占用端口的程序后再启动。"
}
$gameUrl = "http://127.0.0.1:$gamePort"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3 -m venv .venv
}

$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-PythonImports -PythonPath $pythonPath -ImportStatement "import fastapi, uvicorn")) {
    Write-Host "未检测到项目依赖，首次启动需要联网安装。"
    & $pythonPath -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "依赖安装失败；请检查 Python 和网络后重试。" }
}

# Voice is optional. The launcher reads WANDERER_TTS_* from the project .env,
# starts the user's local GPT-SoVITS API on 127.0.0.1:9880, and exits quietly
# when voice is disabled. The launcher auto-selects a usable CUDA runtime and
# falls back to CPU when CUDA is unavailable. Model loading may take a few minutes.
$voiceLauncher = Start-Process -FilePath $pythonPath -ArgumentList @(
    "scripts\start_gpt_sovits.py", "--state-file", $voiceSessionFile
) -WorkingDirectory $projectRoot -PassThru -WindowStyle Hidden
Write-Host "GPT-SoVITS 语音服务正在后台准备（若已关闭语音则会自动跳过）。"

$server = Start-Process -FilePath $pythonPath -ArgumentList @(
    "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "$gamePort"
) -WorkingDirectory $projectRoot -PassThru -NoNewWindow

try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 250
        try {
            $health = Invoke-WebRequest -Uri "$gameUrl/api/health" -UseBasicParsing -TimeoutSec 1
            $server.Refresh()
            if ($server.HasExited) { throw "新启动的服务进程已退出。端口 8000 可能被其他程序占用。" }
            if ($health.StatusCode -eq 200) { $ready = $true; break }
        } catch {
            $server.Refresh()
            if ($server.HasExited) { throw "服务启动失败，请检查 Python 环境或端口 8000 是否已被占用。" }
        }
    }
    if (-not $ready) { throw "服务启动超时，请检查端口 8000 是否被占用。" }
    Write-Host "已启动： $gameUrl"
    if (-not $NoBrowser) {
        Start-Process $gameUrl
    }
    Wait-Process -Id $server.Id
} finally {
    if ($null -ne $server) {
        $server.Refresh()
    }
    if ($null -ne $server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force
    }
    if (Test-Path $pythonPath) {
        & $pythonPath "scripts\start_gpt_sovits.py" --stop --state-file $voiceSessionFile 2>$null
    }
    if ($null -ne $voiceLauncher) {
        $voiceLauncher.Refresh()
        if (-not $voiceLauncher.HasExited) {
            Stop-Process -Id $voiceLauncher.Id -Force
        }
    }
}
