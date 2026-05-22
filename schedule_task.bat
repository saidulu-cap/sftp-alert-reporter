@echo off
REM Run this script ONCE to register the SFTP Alert Reporter task.
REM Two triggers:
REM   1. Daily at 1:00 PM IST  (runs on time when laptop is already on)
REM   2. At every Logon        (catches up if laptop was off at 1pm)
REM The script itself skips if:
REM   - It's before 1:00 PM IST (emails not yet received)
REM   - Report was already sent today (prevents duplicates vs GitHub Actions)

SET PYTHON_EXE=C:\Users\gadari.saidulu\AppData\Local\Programs\PythonEmbed312\python.exe
SET SCRIPT=C:\Users\gadari.saidulu\Projects\sftp-alert-reporter\sftp_report.py
SET WORKDIR=C:\Users\gadari.saidulu\Projects\sftp-alert-reporter

powershell -NoProfile -Command " ^
  $action   = New-ScheduledTaskAction -Execute '%PYTHON_EXE%' -Argument '%SCRIPT%' -WorkingDirectory '%WORKDIR%'; ^
  $t1       = New-ScheduledTaskTrigger -Daily -At '13:00'; ^
  $t2       = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; ^
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew; ^
  Unregister-ScheduledTask -TaskName 'SFTP Alert Reporter' -Confirm:$false -ErrorAction SilentlyContinue; ^
  Register-ScheduledTask -TaskName 'SFTP Alert Reporter' -Action $action -Trigger @($t1,$t2) -Settings $settings -Force; ^
  Write-Host 'Task registered: daily 1pm + at every logon.' ^
"

echo.
echo Triggers registered:
echo   1. Daily at 1:00 PM IST
echo   2. At every Windows logon (catches up missed 1pm runs)
echo.
echo The script automatically skips if before 1pm or already sent today.
pause
