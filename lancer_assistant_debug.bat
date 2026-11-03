@echo off
REM Lance Capri avec affichage des messages et des erreurs
echo ============================================================
echo LANCEMENT DE CAPRI - MODE DEBUG
echo ============================================================
echo.

cd /d "%~dp0"

REM Verifier si Python est installe
echo Verification de Python...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERREUR] Python n'est pas installe ou pas dans le PATH
    echo.
    echo Solutions:
    echo 1. Installez Python depuis https://www.python.org/downloads/
    echo 2. Cochez "Add Python to PATH" pendant l'installation
    echo 3. Ou utilisez: winget install Python.Python.3.12
    echo.
    echo Appuyez sur une touche pour quitter...
    pause >nul
    exit /b 1
)

echo Python OK
python --version
echo.

REM Verifier si les dependances sont installees
echo Verification des dependances...
pip show SpeechRecognition >nul 2>&1
if %ERRORLEVEL% NEQ 0 goto installer
pip show sherpa-onnx >nul 2>&1
if %ERRORLEVEL% NEQ 0 goto installer
pip show miniaudio >nul 2>&1
if %ERRORLEVEL% NEQ 0 goto installer
goto lancer

:installer
echo.
echo Des dependances manquent, installation en cours...
echo.
pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERREUR] Impossible d'installer les dependances
    echo Appuyez sur une touche pour quitter...
    pause >nul
    exit /b 1
)

:lancer
echo Dependances OK
echo.
echo ============================================================
echo LANCEMENT DE CAPRI...
echo ============================================================
echo Options utiles : --muet (sans son)  --sans-micro (sans ecoute)
echo.

REM Lancer Capri (avec fenetre visible pour voir les erreurs)
python assistant_vocal.py %*

echo.
echo.
echo ============================================================
echo Capri s'est arretee
echo ============================================================
echo.
echo Appuyez sur une touche pour fermer cette fenetre...
pause >nul
