from pathlib import Path
import os
import shutil
import subprocess
import sys


ROOT = Path(__file__).parents[1]


def test_start_scripts_open_browser_and_use_manual_startup():
    powershell = (ROOT / "start.ps1").read_text(encoding="utf-8")

    assert "Start-Process" in powershell
    assert "8000..8010" in powershell
    assert "InstallAutostart" not in powershell
    assert "Start-Process $gameUrl" in powershell


def test_start_script_checks_health_marker_and_scans_alternate_ports():
    powershell = (ROOT / "start.ps1").read_text(encoding="utf-8")

    assert "TcpListener" in powershell
    assert "portProbe.Start()" in powershell
    assert "$health.data.status -eq \"ok\"" in powershell
    assert "$health.data.mode -in @(\"offline\", \"live\")" in powershell
    assert '$health.data.version -eq "0.2.0"' in powershell
    assert '"--port", "$gamePort"' in powershell
    assert "$server.HasExited" in powershell


def test_start_script_reuses_the_existing_wanderer_game_service():
    powershell = (ROOT / "start.ps1").read_text(encoding="utf-8")

    assert "/api/health" in powershell
    assert "游戏服务已在运行" in powershell


def test_dependency_probe_handles_missing_imports_without_terminating_powershell(tmp_path):
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        import pytest

        pytest.skip("PowerShell is required for the native-command integration test")

    helper = ROOT / "scripts" / "python_import_check.ps1"
    helper_path = str(helper).replace("'", "''")
    python_path = sys.executable.replace("'", "''")
    probe = tmp_path / "dependency_probe.ps1"
    probe.write_text(
        "\n".join(
            (
                "$ErrorActionPreference = 'Stop'",
                f". '{helper_path}'",
                f"$python = '{python_path}'",
                "if (-not (Test-PythonImports -PythonPath $python -ImportStatement 'import sys')) { throw 'valid imports were rejected' }",
                "if ($ErrorActionPreference -ne 'Stop') { throw 'error preference was not restored after success' }",
                "if (Test-PythonImports -PythonPath $python -ImportStatement 'import wanderer_missing_test_dependency') { throw 'missing import was accepted' }",
                "if ($ErrorActionPreference -ne 'Stop') { throw 'error preference was not restored after failure' }",
                "Write-Output 'dependency probe recovered from missing import'",
            )
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [powershell, "-NoProfile", "-File", str(probe)],
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert "dependency probe recovered from missing import" in result.stdout

    launcher = (ROOT / "start.ps1").read_text(encoding="utf-8")
    assert 'Test-PythonImports -PythonPath $pythonPath -ImportStatement "import fastapi, uvicorn"' in launcher


def test_dependency_installer_retries_with_fallback_index_after_primary_failure(tmp_path):
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        import pytest

        pytest.skip("PowerShell is required for the native-command integration test")

    helper_path = str(ROOT / "scripts" / "python_import_check.ps1").replace("'", "''")
    shim_path = tmp_path / "python.cmd"
    calls_path = tmp_path / "pip-calls.txt"
    first_call_path = tmp_path / "first-call.txt"
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text("test-only\n", encoding="utf-8")
    shim_path.write_text(
        "\r\n".join(
            (
                "@echo off",
                f'>>"{calls_path}" echo %*',
                f'if not exist "{first_call_path}" (',
                f'  >"{first_call_path}" echo called',
                "  echo primary index unavailable 1>&2",
                "  exit /b 1",
                ")",
                "echo fallback index succeeded 1>&2",
                "exit /b 0",
            )
        ),
        encoding="utf-8",
    )
    probe = tmp_path / "fallback_probe.ps1"
    probe.write_text(
        "\n".join(
            (
                "$ErrorActionPreference = 'Stop'",
                f". '{helper_path}'",
                f"$python = '{str(shim_path).replace(chr(39), chr(39) * 2)}'",
                f"$requirements = '{str(requirements_path).replace(chr(39), chr(39) * 2)}'",
                "$installed = Install-WandererDependencies -PythonPath $python -RequirementsPath $requirements -FallbackIndexUrl 'https://mirror.example/simple'",
                "if (-not $installed) { throw 'fallback install did not recover' }",
                "if ($ErrorActionPreference -ne 'Stop') { throw 'error preference was not restored' }",
                "Write-Output 'fallback install recovered'",
            )
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [powershell, "-NoProfile", "-File", str(probe)],
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert "fallback install recovered" in result.stdout
    calls = calls_path.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 2
    assert "--index-url https://mirror.example/simple" not in calls[0]
    assert "--index-url https://mirror.example/simple" in calls[1]


def test_start_script_warns_and_avoids_reusing_an_old_game_version():
    powershell = (ROOT / "start.ps1").read_text(encoding="utf-8")

    assert '$health.data.version -ne "0.2.0"' in powershell
    assert "检测到旧版游戏服务" in powershell
    assert "$health.data.version -eq \"0.2.0\"" in powershell


def test_batch_launcher_keeps_error_window_open_for_diagnostics():
    batch = (ROOT / "start.bat").read_text(encoding="utf-8")

    assert "if errorlevel 1" in batch
    assert "pause" in batch
    assert '"%~dp0start.ps1" %*' in batch


def test_readme_explains_automatic_alternate_port_selection():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "自动尝试 8001 至 8010" in readme
    assert "请关闭占用端口的程序再启动" not in readme


def test_voice_diagnostic_is_visible_before_web_startup_continues(tmp_path):
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        import pytest
        pytest.skip("PowerShell is required for the launcher integration test")

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "start_gpt_sovits.py").write_text(
        "from pathlib import Path\nimport sys\n"
        "Path('diagnostic-ready').touch()\n"
        "print('TTS_REFERENCE_AUDIO_MISSING: set WANDERER_TTS_REFERENCE_AUDIO', file=sys.stderr)\n"
        "raise SystemExit(1)\n", encoding="utf-8",
    )
    launcher = (ROOT / "start.ps1").read_text(encoding="utf-8")
    # Exercise the voice-to-web boundary without probing real ports, environments,
    # dependencies, or starting the actual game service.
    boundary = launcher[launcher.index("$server = $null"):launcher.index("    $ready = $false")]
    probe = tmp_path / "voice_boundary.ps1"
    probe.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        f"$projectRoot = '{str(tmp_path).replace(chr(39), chr(39) * 2)}'\n"
        f"$pythonPath = '{sys.executable.replace(chr(39), chr(39) * 2)}'\n"
        "$voiceSessionFile = Join-Path $projectRoot 'session.json'\n"
        "$gamePort = 8000\nSet-Location $projectRoot\n"
        "function Start-Process {\n"
        "param($FilePath, $ArgumentList, $WorkingDirectory, [switch]$PassThru, $WindowStyle, [switch]$NoNewWindow)\n"
        "if ($ArgumentList[0] -eq 'scripts\\start_gpt_sovits.py') {\n"
        "return Microsoft.PowerShell.Management\\Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory -PassThru -WindowStyle Hidden\n}\n"
        "if (-not (Test-Path 'diagnostic-ready')) { throw 'web started before voice result' }\n"
        "Write-Host 'web startup continued'\n}\n"
        + boundary
        + "\n} finally { }\n"
        + "if ($ErrorActionPreference -ne 'Stop') { throw 'error preference was not restored' }\n",
        encoding="utf-8-sig",
    )
    isolated_env = os.environ.copy()
    isolated_env.update({
        "LOCALAPPDATA": str(tmp_path / "localappdata"),
        "TEMP": str(tmp_path / "temp"),
        "TMP": str(tmp_path / "temp"),
        "WANDERER_TTS_SESSION_FILE": str(tmp_path / "session.json"),
    })
    result = subprocess.run([powershell, "-NoProfile", "-File", str(probe)], capture_output=True, text=True, timeout=15, env=isolated_env)
    assert result.returncode == 0, result.stderr
    assert "WANDERER_TTS_REFERENCE_AUDIO" in result.stdout
    assert "文字" in result.stdout
    assert "web startup continued" in result.stdout


def test_voice_startup_cancellation_stops_owned_server(tmp_path):
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        import pytest
        pytest.skip("PowerShell is required for the launcher integration test")

    shim = tmp_path / "voice_shim.ps1"
    shim.write_text(
        "if ($args -contains '--stop') {\n"
        "    Set-Content -LiteralPath (Join-Path $env:VOICE_TEST_ROOT 'stopped') -Value 'yes'\n"
        "    Remove-Item -LiteralPath (Join-Path $env:VOICE_TEST_ROOT 'session.json')\n"
        "    return\n"
        "}\n"
        "Set-Content -LiteralPath (Join-Path $env:VOICE_TEST_ROOT 'session.json') -Value 'owned'\n"
        "throw 'simulated startup cancellation'\n",
        encoding="utf-8-sig",
    )
    launcher = (ROOT / "start.ps1").read_text(encoding="utf-8")
    startup = launcher[launcher.index("$server = $null"):]
    quoted_root = str(tmp_path).replace("'", "''")
    quoted_shim = str(shim).replace("'", "''")
    probe = tmp_path / "cancel_probe.ps1"
    probe.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        f"$projectRoot = '{quoted_root}'\n"
        f"$pythonPath = '{quoted_shim}'\n"
        "$voiceSessionFile = Join-Path $projectRoot 'session.json'\n"
        "$gamePort = 8000\n$NoBrowser = $true\nSet-Location $projectRoot\n"
        "function Start-Process { Set-Content -LiteralPath (Join-Path $projectRoot 'web-started') -Value 'yes' }\n"
        "try {\n" + startup + "\n} catch { Write-Host 'cancelled' }\n",
        encoding="utf-8-sig",
    )
    isolated_env = os.environ.copy()
    isolated_env.update({
        "LOCALAPPDATA": str(tmp_path / "localappdata"),
        "TEMP": str(tmp_path / "temp"),
        "TMP": str(tmp_path / "temp"),
        "WANDERER_TTS_SESSION_FILE": str(tmp_path / "session.json"),
        "VOICE_TEST_ROOT": str(tmp_path),
    })
    result = subprocess.run(
        [powershell, "-NoProfile", "-File", str(probe)],
        capture_output=True, text=True, timeout=15, env=isolated_env,
    )

    assert result.returncode == 0, result.stderr
    assert "cancelled" in result.stdout
    assert (tmp_path / "stopped").exists()
    assert not (tmp_path / "session.json").exists()
    assert not (tmp_path / "web-started").exists()
