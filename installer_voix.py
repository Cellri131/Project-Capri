"""
Télécharge la voix française neuronale de Capri (environ 65 Mo, une seule fois).

Modèle : Piper « fr_FR-siwis-medium », distribué par le projet sherpa-onnx (GitHub).
Il est placé dans le dossier voix_modeles. Sans lui, Capri utilise la voix Windows (Hortense).
"""

import os
import sys
import tarfile
import tempfile
import urllib.request

import capri_config as cfg

URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-fr_FR-siwis-medium.tar.bz2"


def modele_present():
    from capri_voix import MoteurLocal
    return MoteurLocal.dossier_modele() is not None


def progression(blocs, taille_bloc, total):
    if total > 0:
        fait = min(total, blocs * taille_bloc)
        print(f"\r  {fait / 1e6:6.1f} / {total / 1e6:.1f} Mo ({100 * fait / total:3.0f} %)", end="", flush=True)


def installer():
    if modele_present():
        print("La voix de Capri est déjà installée.")
        return True
    os.makedirs(cfg.DOSSIER_VOIX, exist_ok=True)
    fd, archive = tempfile.mkstemp(suffix=".tar.bz2")
    os.close(fd)
    try:
        print("Téléchargement de la voix de Capri...")
        urllib.request.urlretrieve(URL, archive, progression)
        print("\nExtraction...")
        with tarfile.open(archive, "r:bz2") as tar:
            try:
                tar.extractall(cfg.DOSSIER_VOIX, filter="data")
            except TypeError:  # Python sans l'argument filter
                tar.extractall(cfg.DOSSIER_VOIX)
        print("Voix installée.")
        return True
    except Exception as e:
        print(f"\nTéléchargement impossible : {e}")
        print("Capri utilisera la voix Windows en attendant. Relancez ce script plus tard.")
        return False
    finally:
        try:
            os.remove(archive)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(0 if installer() else 1)
