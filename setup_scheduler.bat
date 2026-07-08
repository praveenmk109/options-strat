@echo off
:: Batch script to register Windows Task Scheduler tasks for the automated trading system.
:: Run this script as an Administrator.

echo === Option Selling Earnings Bot - Task Scheduler Setup ===
echo.

:: Get the directory of this batch file
set "SCRIPT_DIR=%~dp0"
:: Strip trailing backslash
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

:: Define absolute path to the orchestrator script
set "SYSTEM_PATH=%SCRIPT_DIR%\automated_system.py"

echo Script directory identified: %SCRIPT_DIR%
echo Target system file: %SYSTEM_PATH%
echo.

:: 1. Register Afternoon Advisory (1:00 PM CT)
echo Registering Afternoon Advisory (1:00 PM CT)...
schtasks /create /tn "EarningsBot_AfternoonExecution" /tr "python \"%SYSTEM_PATH%\" --mode afternoon" /sc daily /st 13:00 /f

echo.
echo === Setup Complete! ===
echo.
echo Task successfully scheduled in Windows Task Scheduler:
echo  1. EarningsBot_AfternoonExecution (Runs daily at 1:00 PM CT)
echo.
echo IMPORTANT: Make sure you have set your Environment Variables:
echo  - APCA_API_KEY_ID
echo  - APCA_API_SECRET_KEY
echo  - DISCORD_WEBHOOK_URL
echo.
pause
