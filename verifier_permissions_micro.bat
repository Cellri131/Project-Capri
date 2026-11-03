@echo off
echo ============================================================
echo VERIFICATION PERMISSIONS MICROPHONE
echo ============================================================
echo.

echo 1. Ouverture des paramètres de confidentialité du microphone...
start ms-settings:privacy-microphone

echo.
echo INSTRUCTIONS :
echo.
echo 1. Dans la fenêtre qui s'ouvre, vérifiez que :
echo    - "Autoriser les applications à accéder à votre micro" = ACTIVE
echo    - "Autoriser les applications de bureau à accéder à votre micro" = ACTIVE
echo.
echo 2. Si c'était désactivé, activez-le et relancez Capri
echo.
echo 3. Testez ensuite le microphone avec test_microphone.py
echo.
pause
