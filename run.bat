@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
where python >nul 2>nul
if errorlevel 1 goto trylauncher
python -c "import sys; raise SystemExit(not ((3,10) <= sys.version_info[:2] <= (3,13)))" >nul 2>nul
if errorlevel 1 goto trylauncher
python bootstrap.py --launch %*
if errorlevel 1 goto failed
exit /b 0
:trylauncher
where py >nul 2>nul
if errorlevel 1 goto missing
for %%V in (3.13 3.12 3.11 3.10) do (
    py -%%V -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        py -%%V bootstrap.py --launch %*
        if errorlevel 1 goto failed
        exit /b 0
    )
)
:missing
echo Install Python 3.11, 3.12 or 3.13 64-bit from python.org, then run this file again.
:failed
echo.
echo PlateWatch could not start. Check the error above and README.md.
pause
exit /b 1
