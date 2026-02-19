param(
    [string]$ConfigPath = "C:\deploy\rust-sync.json",
    [switch]$Bootstrap,
    [switch]$Web = $true,
    [string]$WebHost = "0.0.0.0",
    [int]$WebPort = 8787
)

$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot
$env:PYTHONPATH = "$PSScriptRoot\src"

$pythonCmd = @("python")
if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCmd = @("py", "-3.12")
}

$baseArgs = @()
if ($pythonCmd.Length -gt 1) {
    $baseArgs = $pythonCmd[1..($pythonCmd.Length - 1)]
}

$verOutput = & $pythonCmd[0] @baseArgs --version 2>&1
$verMatch = [regex]::Match($verOutput, "Python\s+(\d+)\.(\d+)")
if ($verMatch.Success) {
    $major = [int]$verMatch.Groups[1].Value
    $minor = [int]$verMatch.Groups[2].Value
    if ($major -ne 3 -or $minor -ge 13) {
        Write-Host "ERROR: Unsupported Python version detected ($major.$minor)."
        Write-Host "Install Python 3.12 and rerun Install.ps1."
        exit 1
    }
}

$argsList = @("--config", $ConfigPath)
if ($Bootstrap) {
    $argsList += "--bootstrap"
}
if ($Web) {
    $argsList += @("--web", "--web-host", $WebHost, "--web-port", "$WebPort")
}

& $pythonCmd[0] @baseArgs -m rust_sync @argsList
