param(
    [string]$ConfigPath = "C:\deploy\rust-sync.json",
    [switch]$Bootstrap,
    [switch]$Web,
    [string]$WebHost = "0.0.0.0",
    [int]$WebPort = 8787
)

$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot
$env:PYTHONPATH = "$PSScriptRoot\src"

$pythonCmd = "python"
if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCmd = "py -3.12"
}

$argsList = @("--config", $ConfigPath)
if ($Bootstrap) {
    $argsList += "--bootstrap"
}
if ($Web) {
    $argsList += @("--web", "--web-host", $WebHost, "--web-port", "$WebPort")
}

& $pythonCmd -m rust_sync @argsList
