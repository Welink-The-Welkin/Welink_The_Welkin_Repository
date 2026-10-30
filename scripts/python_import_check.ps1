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
