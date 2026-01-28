param(
    [string]$ConfigPath = "C:\deploy\rust-sync.json",
    [string]$PluginsRepoDir = "C:\deploy\rust-plugins-config",
    [string]$KeyDir = "C:\deploy\keys",
    [string]$KeyName = "rust-sync",
    [string]$InstallDir = "C:\deploy"
)

$ErrorActionPreference = "Stop"

function Log($msg) {
    Write-Host $msg
}

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

    $entry = @"
Host $hostName
  HostName $hostName
  User $user
  IdentityFile $keyPath
  IdentitiesOnly yes
"@
    $entry | Set-Content -LiteralPath $configPath -Encoding ASCII
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
        LogPath = "C:\deploy\logs\deploy.log"
        IntervalSeconds = 120
        Branch = "main"
        GitRetryCount = 3
        GitRetryDelaySeconds = 10
        GitTimeoutSeconds = 30
        StartupDelaySeconds = 1
        Servers = @(
            @{
                Name = "main"
                RepoPath = $pluginsRepoDir
                ServerRoot = $serverRoot
                PluginsTarget = "$serverRoot\oxide\plugins"
                ConfigTarget = "$serverRoot\oxide\config"
            }
        )
    }
    $config | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $configPath -Encoding UTF8
}

function Is-Ready() {
    $configOk = Test-Path -LiteralPath $ConfigPath
    $keyOk = Test-Path -LiteralPath (Join-Path $KeyDir $KeyName)
    if (-not ($configOk -and $keyOk)) {
        return $false
    }
    try {
        $cfg = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json -Depth 5
        if (-not $cfg.Servers) {
            return $false
        }
        foreach ($srv in $cfg.Servers) {
            if (-not (Test-Path -LiteralPath $srv.RepoPath)) {
                return $false
            }
            if (-not (Test-Path -LiteralPath (Join-Path $srv.RepoPath ".git"))) {
                return $false
            }
        }
    } catch {
        return $false
    }
    return $true
}

function Check-SshAccess($privateKeyPath) {
    $prevEA = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & ssh -i $privateKeyPath -o IdentitiesOnly=yes -T git@github.com 2>&1 | Out-String
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $prevEA

    Log "SSH output:"
    if ([string]::IsNullOrWhiteSpace($output)) {
        Log "(empty output)"
    } else {
        Log $output
    }
    Log "SSH exit code: $exitCode"

    return ($output -match "successfully authenticated" -or $output -match "Hi " -or $output -match "You.ve successfully authenticated")
}

function Bootstrap() {
    Log "== Rust Plugin Sync bootstrap =="
    Ensure-Dir $InstallDir

    Log "User profile: $env:USERPROFILE"
    Log "Git path: $(Get-Command git -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)"
    Log "SSH path: $(Get-Command ssh -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)"
    try { Log "SSH version: $(ssh -V 2>&1)" } catch {}

    $keys = Ensure-SshKey -keyDir $KeyDir -keyName $KeyName
    $privateKeyPath = $keys[0]
    $publicKeyPath = $keys[1]

    Ensure-SshConfigEntry -configPath "$env:USERPROFILE\.ssh\config" -hostName "github.com" -keyPath $privateKeyPath -user "git"
    Log "SSH config path: $env:USERPROFILE\.ssh\config"
    Log "SSH config contents:"
    Log (Get-Content -LiteralPath "$env:USERPROFILE\.ssh\config" -Raw)
    Log "Private key exists: $(Test-Path -LiteralPath $privateKeyPath)"
    Log "Public key exists:  $(Test-Path -LiteralPath $publicKeyPath)"

    Log "Public key (add to GitHub Deploy Keys, read-only):"
    Log (Get-Content -LiteralPath $publicKeyPath -Raw)

    $null = Read-Host "Press Enter after you added the key to GitHub"

    while ($true) {
        Log "Checking SSH access to GitHub..."
        if (Check-SshAccess -privateKeyPath $privateKeyPath) {
            break
        }
        Log "SSH check failed. Verify Deploy Key and access."
        $retry = Read-Host "Retry SSH check? (y/n)"
        if ($retry -ne "y") {
            $continue = Read-Host "Continue anyway (skip SSH check)? (y/n)"
            if ($continue -ne "y") {
                exit 1
            }
            break
        }
    }

    $serverRoot = Read-Host "Enter Rust server path (e.g. C:\Users\Administrator\Desktop\266Server)"
    if ([string]::IsNullOrWhiteSpace($serverRoot)) {
        Log "ERROR: ServerRoot is required"
        exit 1
    }

    $repoUrl = Read-Host "Enter plugins repo SSH URL (e.g. git@github.com:USER/REPO.git)"
    if ([string]::IsNullOrWhiteSpace($repoUrl)) {
        Log "ERROR: Repo URL is required"
        exit 1
    }

    if (-not (Test-Path -LiteralPath $PluginsRepoDir)) {
        git clone $repoUrl $PluginsRepoDir
    }

    Write-SampleConfig -configPath $ConfigPath -serverRoot $serverRoot -pluginsRepoDir $PluginsRepoDir

    Log "Config created: $ConfigPath"
}

Log "== Rust Plugin Sync start =="

if (-not (Is-Ready)) {
    Log "Bootstrap required."
    Bootstrap
}

Log "Starting service..."
Set-Location $PSScriptRoot
& poetry run rust-sync --config $ConfigPath
