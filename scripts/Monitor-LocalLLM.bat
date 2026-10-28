@echo off
setlocal
where pwsh.exe >nul 2>nul
if %errorlevel%==0 (
    pwsh.exe -NoLogo -NoProfile -File "%~dp0Watch-LocalLLM.ps1" %*
) else (
    powershell.exe -NoLogo -NoProfile -File "%~dp0Watch-LocalLLM.ps1" %*
)
endlocal
