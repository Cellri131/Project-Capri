@echo off
REM Retire Capri du demarrage de Windows
echo ============================================================
echo DESINSTALLATION DE CAPRI DU DEMARRAGE
echo ============================================================
echo.

set SHORTCUT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Capri.lnk

if exist "%SHORTCUT%" (
    echo Suppression du raccourci...
    del "%SHORTCUT%"

    if %ERRORLEVEL% EQU 0 (
        echo.
        echo ============================================================
        echo DESINSTALLATION REUSSIE !
        echo ============================================================
        echo.
        echo Capri ne se lancera plus au demarrage de Windows
        echo.
    ) else (
        echo.
        echo ERREUR lors de la suppression
        echo.
    )
) else (
    echo.
    echo Capri n'est pas installee au demarrage
    echo Aucune action necessaire
    echo.
)

echo.
echo Appuyez sur une touche pour quitter...
pause >nul
