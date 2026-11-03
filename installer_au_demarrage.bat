@echo off
REM Installe Capri au demarrage de Windows
echo ============================================================
echo INSTALLATION DE CAPRI AU DEMARRAGE DE WINDOWS
echo ============================================================
echo.

cd /d "%~dp0"
python creer_raccourci.py --demarrage

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ============================================================
    echo INSTALLATION REUSSIE !
    echo ============================================================
    echo.
    echo Capri se lancera automatiquement au prochain demarrage de Windows.
    echo Pour desinstaller : desinstaller_demarrage.bat
    echo.
) else (
    echo.
    echo ERREUR lors de l'installation
    echo Verifiez que Python et les dependances sont installes
    echo.
)

echo.
echo Appuyez sur une touche pour quitter...
pause >nul
