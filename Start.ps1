param(
    [string]$ConfigPath = "C:\deploy\rust-sync.json",
    [switch]$Bootstrap
)

$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot
$env:PYTHONPATH = "$PSScriptRoot\src"

$argsList = @("--config", $ConfigPath)
if ($Bootstrap) {
    $argsList += "--bootstrap"
}

python -m rust_sync @argsList
