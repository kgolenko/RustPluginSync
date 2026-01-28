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
$pythonCmd = "python"
if (Command-Exists "py") {
    $pythonCmd = "py -$PythonVersion"
}

Log "Python version:"
& $pythonCmd --version

Log "Upgrading pip..."
& $pythonCmd -m pip install --upgrade pip

if ($InstallPoetry) {
    Log "Installing poetry..."
    & $pythonCmd -m pip install --upgrade poetry
}

if ($InstallDeps) {
    Log "Installing project dependencies..."
    & $pythonCmd -m pip install -e .
}

Log "Done."
