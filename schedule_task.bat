@echo off
REM Run this script ONCE to register the daily 1pm IST task.
REM  - StartWhenAvailable: if laptop was off at 1pm, runs as soon as laptop is on
REM  - Deduplication: the script itself skips if report was already sent today (by GitHub Actions)

SET PYTHON_EXE=C:\Users\gadari.saidulu\AppData\Local\Programs\PythonEmbed312\python.exe
SET SCRIPT=C:\Users\gadari.saidulu\Projects\sftp-alert-reporter\sftp_report.py
SET WORKDIR=C:\Users\gadari.saidulu\Projects\sftp-alert-reporter

powershell -NoProfile -Command ^
  "$action   = New-ScheduledTaskAction -Execute '%PYTHON_EXE%' -Argument '%SCRIPT%' -WorkingDirectory '%WORKDIR%';" ^
  "$trigger  = New-ScheduledTaskTrigger -Daily -At '13:00';" ^
  "$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew;" ^
  "Unregister-ScheduledTask -TaskName 'SFTP Alert Reporter' -Confirm:$false -ErrorAction SilentlyContinue;" ^
  "Register-ScheduledTask   -TaskName 'SFTP Alert Reporter' -Action $action -Trigger $trigger -Settings $settings -Force;" ^
  "Write-Host 'Task registered successfully with StartWhenAvailable.'"

echo.
echo Task "SFTP Alert Reporter" scheduled at 1:00 PM daily.
echo If laptop is off at 1pm it will run as soon as you switch on.
echo Duplicate runs are prevented by the script's own sent-mail check.
pause
