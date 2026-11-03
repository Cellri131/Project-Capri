"""
Crée le raccourci de Capri (bureau par défaut, ou démarrage de Windows avec --demarrage).

L'icône du raccourci est icon.ico (celle de la zone de notification est icon.png) :
pour en changer, remplacer ces fichiers puis relancer ce script.
"""

import argparse
import os
import sys

from win32com.client import Dispatch

import capri_config as cfg

NOM = "Capri.lnk"
ANCIENS_NOMS = ("Carl Assistant Vocal.lnk",)


def interpreteur_sans_console():
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return pythonw if os.path.exists(pythonw) else exe


def creer(destination):
    shell = Dispatch("WScript.Shell")
    dossier = shell.SpecialFolders(destination)
    for ancien in ANCIENS_NOMS:
        chemin_ancien = os.path.join(dossier, ancien)
        if os.path.exists(chemin_ancien):
            lien = shell.CreateShortCut(chemin_ancien)
            if os.path.normcase(os.path.abspath(lien.WorkingDirectory)).rstrip("\\") == os.path.normcase(cfg.DOSSIER).rstrip("\\"):
                os.remove(chemin_ancien)
                print(f"Ancien raccourci supprimé : {ancien}")
    raccourci = shell.CreateShortCut(os.path.join(dossier, NOM))
    raccourci.TargetPath = interpreteur_sans_console()
    raccourci.Arguments = f'"{os.path.join(cfg.DOSSIER, "assistant_vocal.py")}"'
    raccourci.WorkingDirectory = cfg.DOSSIER
    raccourci.IconLocation = cfg.ICONE_ICO
    raccourci.Description = "Capri - Assistante vocale"
    raccourci.WindowStyle = 7
    raccourci.Save()
    return os.path.join(dossier, NOM)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--demarrage", action="store_true", help="raccourci dans le démarrage de Windows")
    args = parser.parse_args()
    print("Raccourci créé :", creer("Startup" if args.demarrage else "Desktop"))
