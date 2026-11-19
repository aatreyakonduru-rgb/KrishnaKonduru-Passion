@echo off
rem Run once: puts an Argus icon (named after product.brand in sdlc-profile.json) on your desktop that runs start-workbench.cmd.
rem   make-shortcut.cmd [jira-user]    default jira-user: your Windows user name
rem To pin it: right-click the icon, then Pin to taskbar (Windows 11: Show more options first).
setlocal
set "TARGET=%~dp0start-workbench.cmd"
set "WB_ARG=%~1"
for %%r in ("%~dp0..\..\..") do set "REPO=%%~fr"
set "WB_TITLE=Argus"
set "WB_LONG=Argus"
for /f "delims=" %%t in ('py -3 "%~dp0sdlc_profile.py" workbench_short 2^>nul') do set "WB_TITLE=%%t"
for /f "delims=" %%t in ('py -3 "%~dp0sdlc_profile.py" workbench_title 2^>nul') do set "WB_LONG=%%t"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$q=[char]34; $lnk=[Environment]::GetFolderPath('Desktop')+'\'+$env:WB_TITLE+'.lnk';" ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($lnk);" ^
  "$s.TargetPath=$env:ComSpec; $s.Arguments='/c '+$q+$q+$env:TARGET+$q+' '+$env:WB_ARG+$q;" ^
  "$s.WorkingDirectory=$env:REPO; $s.WindowStyle=7; $s.Description=$env:WB_LONG;" ^
  "$s.IconLocation=$env:SystemRoot+'\System32\shell32.dll,13'; $s.Save(); Write-Output ('Made '+$lnk)"
if errorlevel 1 (echo Could not make the shortcut. & pause & exit /b 1)
echo Double-click "%WB_TITLE%" on your desktop to start it.
pause
