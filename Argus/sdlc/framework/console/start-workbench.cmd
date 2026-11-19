@echo off
rem Argus on Windows: double-click to start it (when it is not running) and open the page.
rem   start-workbench.cmd [jira-user]    default jira-user: your Windows user name (e.g. AB12345)
rem Argus runs in a minimised window named after the product (product.brand in .devin\rules\sdlc-profile.json);
rem close that window to stop it.
setlocal
set "HERE=%~dp0"
set "WB_TITLE=Argus"
for /f "delims=" %%t in ('py -3 "%HERE%sdlc_profile.py" workbench_short 2^>nul') do set "WB_TITLE=%%t"
set "PORT=8787"
if not "%SDLC_CONSOLE_PORT%"=="" set "PORT=%SDLC_CONSOLE_PORT%"
set "WB_USER=%~1"
if "%WB_USER%"=="" set "WB_USER=%USERNAME%"
set "URL=http://127.0.0.1:%PORT%"
if "%SDLC_DEVIN_TRANSPORT%"=="" set "SDLC_DEVIN_TRANSPORT=api"
curl.exe -s -o nul --max-time 2 "%URL%/api/config" && goto open
start "%WB_TITLE%" /min cmd /k py -3 "%HERE%server.py" --port %PORT% --user %WB_USER%
for /l %%i in (1,1,30) do (
  timeout /t 1 /nobreak >nul
  curl.exe -s -o nul --max-time 2 "%URL%/api/config" && goto open
)
echo Argus did not answer on %URL%.
echo Open the "%WB_TITLE%" window on the taskbar to see why.
pause
exit /b 1
:open
start "" "%URL%"
