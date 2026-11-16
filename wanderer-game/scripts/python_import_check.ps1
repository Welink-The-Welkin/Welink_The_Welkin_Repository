function Test-PythonImports {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonPath,

        [Parameter(Mandatory = $true)]
        [string]$ImportStatement
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $PythonPath -c $ImportStatement 2>$null
        $pythonExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    return ($pythonExitCode -eq 0)
}

function Install-WandererDependencies {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonPath,

        [Parameter(Mandatory = $true)]
        [string]$RequirementsPath,

        [Parameter(Mandatory = $true)]
        [string]$FallbackIndexUrl
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"

        Write-Host "正在使用当前 pip 索引安装项目依赖。"
        & $PythonPath -m pip install -r $RequirementsPath 2>&1 | ForEach-Object { Write-Host $_ }
        $primaryExitCode = $LASTEXITCODE
        if ($primaryExitCode -eq 0) {
            return $true
        }

        Write-Host "当前 pip 索引未能提供完整依赖，改用备用镜像重试：$FallbackIndexUrl" -ForegroundColor Yellow
        & $PythonPath -m pip install --index-url $FallbackIndexUrl -r $RequirementsPath 2>&1 | ForEach-Object { Write-Host $_ }
        $fallbackExitCode = $LASTEXITCODE
        return ($fallbackExitCode -eq 0)
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}
