@echo off
title TW1 PAR Editor v1.1

REM Try 'py' launcher first (standard Windows Python installer)
where py >nul 2>nul
if not errorlevel 1 (
    py tw1_par_editor.py %*
    goto :end
)

REM Try 'python' in PATH
where python >nul 2>nul
if not errorlevel 1 (
    python tw1_par_editor.py %*
    goto :end
)

REM Try 'python3' (some setups)
where python3 >nul 2>nul
if not errorlevel 1 (
    python3 tw1_par_editor.py %*
    goto :end
)

REM Try common install paths
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" (
    "%LocalAppData%\Programs\Python\Python313\python.exe" tw1_par_editor.py %*
    goto :end
)
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
    "%LocalAppData%\Programs\Python\Python312\python.exe" tw1_par_editor.py %*
    goto :end
)
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
    "%LocalAppData%\Programs\Python\Python311\python.exe" tw1_par_editor.py %*
    goto :end
)
if exist "%LocalAppData%\Programs\Python\Python310\python.exe" (
    "%LocalAppData%\Programs\Python\Python310\python.exe" tw1_par_editor.py %*
    goto :end
)
if exist "C:\Python313\python.exe" (
    "C:\Python313\python.exe" tw1_par_editor.py %*
    goto :end
)
if exist "C:\Python312\python.exe" (
    "C:\Python312\python.exe" tw1_par_editor.py %*
    goto :end
)
if exist "C:\Python311\python.exe" (
    "C:\Python311\python.exe" tw1_par_editor.py %*
    goto :end
)

echo.
echo ERROR: Python not found!
echo.
echo Install Python 3 from https://python.org
echo IMPORTANT: Check "Add Python to PATH" during installation!
echo.
pause
goto :eof

:end
if errorlevel 1 (
    echo.
    echo Editor exited with an error.
    pause
)
