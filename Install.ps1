param(
    [string]$PythonVersion = "3.12",
    [switch]$InstallPoetry,
    [switch]$InstallDeps
)

$ErrorActionPreference = "Stop"

function Log($msg) {
    Write-Host $msg
}

function Command-Exists($name) {
    return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

if (-not (Command-Exists "python")) {
    if (Command-Exists "winget") {
        $pythonId = "Python.Python.$PythonVersion"
        Log "Installing Python via winget ($pythonId)..."
        winget install --id $pythonId -e --source winget
        Log "Python installed. You may need to reopen the terminal for PATH to update."
    } else {
        Log "ERROR: python not found and winget is not available."
        Log "Install Python $PythonVersion manually from python.org and rerun this script."
        exit 1
    }
}

# Prefer Python launcher if available to avoid picking up unsupported versions.
$pythonCmd = @("python")
if (Command-Exists "py") {
    $pythonCmd = @("py", "-$PythonVersion")
}

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)]$Args)
    $baseArgs = @()
    if ($pythonCmd.Length -gt 1) {
        $baseArgs = $pythonCmd[1..($pythonCmd.Length - 1)]
    }
    & $pythonCmd[0] @baseArgs @Args
}

Log "Python version:"
$verOutput = Invoke-Python --version 2>&1
Write-Host $verOutput
$verMatch = [regex]::Match($verOutput, "Python\s+(\d+)\.(\d+)")
if ($verMatch.Success) {
    $major = [int]$verMatch.Groups[1].Value
    $minor = [int]$verMatch.Groups[2].Value
    if ($major -ne 3 -or $minor -ge 13) {
        Log "ERROR: Unsupported Python version detected ($major.$minor)."
        Log "Install Python $PythonVersion and rerun: winget install --id Python.Python.$PythonVersion -e --source winget"
        exit 1
    }
}

Log "Upgrading pip..."
Invoke-Python -m pip install --upgrade pip

if ($InstallPoetry) {
    Log "Installing poetry..."
    Invoke-Python -m pip install --upgrade poetry
}

if ($InstallDeps) {
    Log "Installing project dependencies..."
    Invoke-Python -m pip install -e .
}

Log "Done."
