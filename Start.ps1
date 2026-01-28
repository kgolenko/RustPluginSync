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

$argsList = @("--config", $ConfigPath)
if ($Bootstrap) {
    $argsList += "--bootstrap"
}
if ($Web) {
    $argsList += @("--web", "--web-host", $WebHost, "--web-port", "$WebPort")
}

python -m rust_sync @argsList
