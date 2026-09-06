@echo off
setlocal EnableDelayedExpansion
REM Wrapper BAT pour lancer le health-check social via PowerShell
set SCRIPT_DIR=%~dp0
set REPO_ROOT=%SCRIPT_DIR%..
set LOG_DIR=%REPO_ROOT%\logs
set LOG_FILE=%LOG_DIR%\social_health_check.log
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1

for /f "tokens=1-3 delims=/ " %%a in ("%date%") do set D=%%c-%%b-%%a
for /f "tokens=1-3 delims=:., " %%a in ("%time%") do set T=%%a:%%b:%%c
echo ==== RUN %D% %T% ====>>"%LOG_FILE%"

set PS1=%SCRIPT_DIR%run_social_health_check.ps1
powershell -NoProfile -Command "if (Test-Path '%LOG_FILE%') { $s=(Get-Item '%LOG_FILE%').Length; if ($s -gt 1048576) { Move-Item -Force '%LOG_FILE%' '%LOG_FILE%.1' } }" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" >>"%LOG_FILE%" 2>&1
set EXITCODE=%ERRORLEVEL%
echo.>>"%LOG_FILE%"
endlocal & exit /b %EXITCODE%
