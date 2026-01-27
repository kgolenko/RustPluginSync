param(
    [string]$KeyDir = "C:\deploy\keys",
    [string]$KeyName = "rust-sync",
    [string]$SshConfigPath = "$env:USERPROFILE\.ssh\config",
    [string]$GitHost = "github.com",
    [string]$GitUser = "git"
)

$ErrorActionPreference = "Stop"

function Ensure-Dir($path) {
    if (-not (Test-Path -LiteralPath $path)) {
        New-Item -ItemType Directory -Path $path | Out-Null
    }
}

function Ensure-ParentDir($path) {
    $parent = Split-Path -Parent $path
    Ensure-Dir $parent
}

function Ensure-SshConfigEntry($configPath, $hostName, $keyPath, $user) {
    Ensure-ParentDir $configPath
    if (-not (Test-Path -LiteralPath $configPath)) {
        New-Item -ItemType File -Path $configPath | Out-Null
    }

    $configText = Get-Content -LiteralPath $configPath -Raw
    $hostEntry = "Host $hostName"
    if ($configText -notmatch [regex]::Escape($hostEntry)) {
        Add-Content -LiteralPath $configPath -Value "`nHost $hostName"
        Add-Content -LiteralPath $configPath -Value "  HostName $hostName"
        Add-Content -LiteralPath $configPath -Value "  User $user"
        Add-Content -LiteralPath $configPath -Value "  IdentityFile $keyPath"
        Add-Content -LiteralPath $configPath -Value "  IdentitiesOnly yes"
    }
}

$privateKeyPath = Join-Path $KeyDir $KeyName
$publicKeyPath = "$privateKeyPath.pub"

Ensure-Dir $KeyDir

if (-not (Test-Path -LiteralPath $privateKeyPath)) {
    ssh-keygen -t ed25519 -C "rust-sync" -f $privateKeyPath | Out-Null
}

Ensure-SshConfigEntry -configPath $SshConfigPath -host $GitHost -keyPath $privateKeyPath -user $GitUser

Write-Host "Private key: $privateKeyPath"
Write-Host "Public key:  $publicKeyPath"
Write-Host "Add public key to GitHub Deploy Keys (read-only)"
Write-Host "Key contents:"
Get-Content -LiteralPath $publicKeyPath
