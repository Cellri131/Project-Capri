@echo off
REM Installation des dependances de Capri (bibliotheques + voix neuronale francaise)
echo ============================================================
echo INSTALLATION DES DEPENDANCES POUR CAPRI
echo ============================================================
echo.

cd /d "%~dp0"

REM Verifier Python
echo [1/4] Verification de Python...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERREUR] Python n'est pas installe !
    echo.
    echo Installez Python avec : winget install Python.Python.3.12
    echo Ou depuis : https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

python --version
echo Python OK !
echo.

REM Mettre a jour pip
echo [2/4] Mise a jour de pip...
python -m pip install --upgrade pip
echo.

REM Installer les dependances
echo [3/4] Installation des dependances...
echo Cela peut prendre quelques minutes...
echo.

pip install -r requirements.txt

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ============================================================
    echo ERREUR LORS DE L'INSTALLATION
    echo ============================================================
    echo.
    echo Si PyAudio pose probleme :
    echo 1. Allez sur https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio
    echo 2. Telechargez le fichier .whl pour votre version de Python 64-bit
    echo 3. Installez avec : pip install nom_fichier.whl
    echo 4. Relancez ce script
    echo.
    pause
    exit /b 1
)

REM Voix neuronale francaise (environ 65 Mo, une seule fois)
echo.
echo [4/4] Voix de Capri...
python installer_voix.py

REM Raccourci sur le bureau (icone issue de icon.png)
echo.
echo Creation du raccourci sur le bureau...
python creer_raccourci.py

echo.
echo ============================================================
echo INSTALLATION TERMINEE
echo ============================================================
echo.
echo Lancez Capri avec le raccourci "Capri" du bureau.
echo.

echo Appuyez sur une touche pour quitter...
pause >nul
