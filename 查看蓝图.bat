@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if "%~1"=="" (
    echo Drag one or more .uasset / .umap / .json files, or a folder, then press Enter:
    set /p ASSET=
    set "ARGS=!ASSET!"
) else (
    set "ARGS=%*"
)

echo.
echo Processing: !ARGS!
echo.

python "%~dp0bp_inspect.py" !ARGS! -o "D:\Blueprint_Output"

if errorlevel 1 (
    echo.
    echo [ERROR] Check: 1^) file exists  2^) python installed  3^) uasset.exe found
    echo You can also run manually:
    echo   python "%~dp0bp_inspect.py" "your_file.umap"
)

echo.
echo Done. Results are in D:\Blueprint_Output
pause