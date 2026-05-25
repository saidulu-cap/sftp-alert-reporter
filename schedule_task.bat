@echo off
REM Run this script ONCE to register the SFTP Alert Reporter task.
REM Trigger: daily at 1pm, repeats every 10 min until 11pm, StartWhenAvailable.
REM The script skips instantly if before 1pm IST or already sent today.

SET XMLFILE=%TEMP%\sftp_task.xml

powershell -NoProfile -Command " ^
  $xml = @'<?xml version=""1.0"" encoding=""UTF-16""?><Task version=""1.2"" xmlns=""http://schemas.microsoft.com/windows/2004/02/mit/task""><RegistrationInfo><Description>SFTP Alert Reporter</Description></RegistrationInfo><Triggers><CalendarTrigger><Repetition><Interval>PT10M</Interval><Duration>PT10H</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><StartBoundary>2026-05-25T13:00:00</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger></Triggers><Principals><Principal id=""Author""><UserId>CLPT1731\gadari.saidulu</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals><Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable><Enabled>true</Enabled><Hidden>false</Hidden><RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT5M</ExecutionTimeLimit><Priority>7</Priority></Settings><Actions Context=""Author""><Exec><Command>C:\Users\gadari.saidulu\AppData\Local\Programs\PythonEmbed312\python.exe</Command><Arguments>C:\Users\gadari.saidulu\Projects\sftp-alert-reporter\sftp_report.py</Arguments><WorkingDirectory>C:\Users\gadari.saidulu\Projects\sftp-alert-reporter</WorkingDirectory></Exec></Actions></Task>'@; ^
  $xml | Out-File -FilePath '%XMLFILE%' -Encoding Unicode; ^
  Unregister-ScheduledTask -TaskName 'SFTP Alert Reporter' -Confirm:$false -ErrorAction SilentlyContinue; ^
  Register-ScheduledTask -TaskName 'SFTP Alert Reporter' -Xml (Get-Content '%XMLFILE%' -Raw) -Force; ^
  Write-Host 'Task registered: 1pm daily, repeats every 10min until 11pm, runs on battery, StartWhenAvailable.' ^
"

echo.
echo Task "SFTP Alert Reporter" registered successfully.
echo Fires at 1:00 PM IST, then every 10 minutes until 11:00 PM.
echo If laptop is off at 1pm, runs within 10 min of switching on.
echo Script auto-skips if before 1pm or report already sent today.
pause
