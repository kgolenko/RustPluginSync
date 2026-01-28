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
        Log "Install Python manually from python.org and rerun this script."
        exit 1
    }
}

Log "Python version:"
python --version

Log "Upgrading pip..."
python -m pip install --upgrade pip

if ($InstallPoetry) {
    Log "Installing poetry..."
    python -m pip install --upgrade poetry
}

if ($InstallDeps) {
    Log "Installing project dependencies..."
    python -m pip install -e .
}

Log "Done."
