@echo off
REM S2 Report Sniffer — Portable Mode Launcher (Windows)
REM Usage: Run-S2ReportSniffer.bat

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "BACKEND_BIN=%SCRIPT_DIR%backend\s2rs-backend.exe"
set "UI_DIR=%SCRIPT_DIR%ui"
set "PORT=8000"

echo S2 Report Sniffer - Portable Mode
echo   Backend: %BACKEND_BIN%
echo   UI:      %UI_DIR%
echo   Port:    %PORT%
echo.

if not exist "%BACKEND_BIN%" (
  echo ERROR: Backend binary not found at %BACKEND_BIN%
  echo        Expected in portable folder structure: .\backend\s2rs-backend.exe + .\ui\
  pause
  exit /b 1
)

REM Find a free port
:findport
netstat -ano | findstr ":%PORT% " >nul 2>&1
if %errorlevel% equ 0 (
  set /a PORT+=1
  goto findport
)

set "S2RS_HOST=127.0.0.1"
set "S2RS_PORT=%PORT%"
set "S2RS_UI_DIR=%UI_DIR%"
set "S2RS_ENVIRONMENT=production"

echo Starting backend on 127.0.0.1:%PORT%...
echo Open http://127.0.0.1:%PORT%/ui/ in your browser.
echo Press Ctrl+C to stop.
echo.

"%BACKEND_BIN%"