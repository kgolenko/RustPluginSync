param(
    [string]$InstallDir = "C:\deploy",
    [string]$ServiceRepoDir = "C:\deploy\RustPluginSync",
    [string]$PluginsRepoDir = "C:\deploy\rust-plugins-config",
    [string]$ConfigPath = "C:\deploy\rust-sync.json",
    [string]$KeyDir = "C:\deploy\keys",
    [string]$KeyName = "rust-sync"
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
        Add-Content -LiteralPath $configPath -Value "  User git"
        Add-Content -LiteralPath $configPath -Value "  IdentityFile $keyPath"
        Add-Content -LiteralPath $configPath -Value "  IdentitiesOnly yes"
    }
}

function Ensure-SshKey($keyDir, $keyName) {
    Ensure-Dir $keyDir
    $privateKeyPath = Join-Path $keyDir $keyName
    $publicKeyPath = "$privateKeyPath.pub"

    if (-not (Test-Path -LiteralPath $privateKeyPath)) {
        ssh-keygen -t ed25519 -C "rust-sync" -f $privateKeyPath | Out-Null
    }

    return @($privateKeyPath, $publicKeyPath)
}

function Write-SampleConfig($configPath, $serverRoot, $pluginsRepoDir) {
    Ensure-ParentDir $configPath
    $config = @{
        RepoPath = $pluginsRepoDir
        ServerRoot = $serverRoot
        PluginsTarget = "$serverRoot\oxide\plugins"
        ConfigTarget = "$serverRoot\oxide\config"
        LogPath = "C:\deploy\logs\deploy.log"
        IntervalSeconds = 120
        Branch = "main"
        GitRetryCount = 3
        GitRetryDelaySeconds = 10
    }
    $config | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $configPath -Encoding UTF8
}

Write-Host "== Rust Plugin Sync bootstrap =="
Ensure-Dir $InstallDir

# SSH key + config
$keys = Ensure-SshKey -keyDir $KeyDir -keyName $KeyName
$privateKeyPath = $keys[0]
$publicKeyPath = $keys[1]
Ensure-SshConfigEntry -configPath "$env:USERPROFILE\.ssh\config" -hostName "github.com" -keyPath $privateKeyPath -user "git"

Write-Host "Public key (add to GitHub Deploy Keys, read-only):"
Get-Content -LiteralPath $publicKeyPath

# Wait for user to add key
$null = Read-Host "Press Enter after you добавили ключ в GitHub"

# Verify SSH access
Write-Host "Проверка SSH доступа к GitHub..."
$sshOk = $false
try {
    $output = ssh -T git@github.com 2>&1
    if ($output -match "successfully authenticated" -or $output -match "Hi ") {
        $sshOk = $true
    }
} catch {
    $sshOk = $false
}

if (-not $sshOk) {
    Write-Host "SSH проверка не прошла. Проверь Deploy Key и доступ, затем повтори запуск."
    exit 1
}

# Ask inputs
$serverRoot = Read-Host "Введите путь к Rust серверу (например C:\Users\Administrator\Desktop\266Server)"
if ([string]::IsNullOrWhiteSpace($serverRoot)) {
    Write-Host "ERROR: ServerRoot is required"
    exit 1
}

$repoUrl = Read-Host "Введите SSH URL репозитория плагинов (например git@github.com:USER/REPO.git)"
if ([string]::IsNullOrWhiteSpace($repoUrl)) {
    Write-Host "ERROR: Repo URL is required"
    exit 1
}

# Clone plugins repo
if (-not (Test-Path -LiteralPath $PluginsRepoDir)) {
    git clone $repoUrl $PluginsRepoDir
}

# Write config
Write-SampleConfig -configPath $ConfigPath -serverRoot $serverRoot -pluginsRepoDir $PluginsRepoDir

Write-Host "Config created: $ConfigPath"
Write-Host "You can now run the service:"
Write-Host "  poetry run rust-sync --config $ConfigPath"
