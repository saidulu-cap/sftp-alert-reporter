@echo off
REM Run this script ONCE (no admin needed) to register the daily 1pm IST task.
REM After registration, Windows Task Scheduler runs it automatically every day.

SET SCRIPT_DIR=%~dp0
SET PYTHON_EXE=C:\Users\gadari.saidulu\AppData\Local\Programs\PythonEmbed312\python.exe

REM Delete old task if it exists (ignore error if not found)
schtasks /delete /tn "SFTP Alert Reporter" /f 2>nul

REM Create the daily task at 14:00 (2pm) local time (set your PC timezone to IST)
schtasks /create ^
  /tn "SFTP Alert Reporter" ^
  /tr "\"%PYTHON_EXE%\" \"%SCRIPT_DIR%sftp_report.py\"" ^
  /sc DAILY ^
  /st 13:00 ^
  /f

echo.
echo Task "SFTP Alert Reporter" scheduled successfully.
echo It will run every day at 1:00 PM local time.
echo Make sure your Windows timezone is set to IST (UTC+5:30).
pause
