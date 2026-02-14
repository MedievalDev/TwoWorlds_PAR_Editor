@echo off
title TW1 PAR Editor v1.1
echo TW1 PAR Editor v1.1
echo.
echo Dateien neben den Editor legen:
echo   tw1_sdk_labels.json        = SDK-Feldnamen (1808 Labels)
echo   tw1_sdk_descriptions.json  = Deutsche Tooltip-Beschreibungen
echo.
python tw1_par_editor.py %*
if errorlevel 1 (
    echo.
    echo FEHLER: Python 3 wird benoetigt. Download: python.org
    pause
)
