@echo off
setlocal

set SERVICE_DIR=%~dp0..
set CONFIG_PATH=C:\deploy\rust-sync.json

cd /d %SERVICE_DIR%
poetry run rust-sync --config %CONFIG_PATH%

endlocal
