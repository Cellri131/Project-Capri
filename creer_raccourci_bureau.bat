@echo off
REM Cree le raccourci "Capri" sur le bureau (icone generee depuis icon.png)
echo ============================================================
echo CREATION DU RACCOURCI SUR LE BUREAU
echo ============================================================
echo.

cd /d "%~dp0"
python creer_raccourci.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ============================================================
    echo RACCOURCI CREE AVEC SUCCES !
    echo ============================================================
    echo.
    echo Double-cliquez sur "Capri" sur votre bureau pour la lancer.
    echo Pour changer l'icone : remplacez icon.ico (raccourci) et icon.png (icones cachees)
    echo puis relancez ce script.
    echo.
) else (
    echo.
    echo ERREUR lors de la creation du raccourci
    echo.
)

echo.
echo Appuyez sur une touche pour quitter...
pause >nul
