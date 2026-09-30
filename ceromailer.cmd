@echo off
setlocal

where py >nul 2>nul
if %ERRORLEVEL% equ 0 (
    py "%~dp0cli.py" %*
    exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python "%~dp0cli.py" %*
    exit /b %ERRORLEVEL%
)

echo Python was not found on this system.
echo You can use the web version of CeroMailer directly at:
echo   https://cero-mailer.vercel.app
echo.
exit /b 1
