"""
Configuration et journal de Capri.

Les réglages sont stockés dans capri_config.json (créé au premier lancement).
"""

import copy
import datetime
import json
import os
import sys
import threading

DOSSIER = os.path.dirname(os.path.abspath(__file__))
FICHIER_CONFIG = os.path.join(DOSSIER, "capri_config.json")
FICHIER_JOURNAL = os.path.join(DOSSIER, "capri_log.txt")
DOSSIER_ASSETS = os.path.join(DOSSIER, "assets")
DOSSIER_CACHE_SPRITES = os.path.join(DOSSIER, "cache_sprites")
DOSSIER_VOIX = os.path.join(DOSSIER, "voix_modeles")
ICONE_PNG = os.path.join(DOSSIER, "icon.png")       # icône de la zone de notification
ICONE_ICO = os.path.join(DOSSIER, "icon.ico")       # icône du raccourci
ICONE_FENETRE = os.path.join(DOSSIER, "capri.ico")  # icône de la fenêtre de Capri
FICHIER_PHRASES = os.path.join(DOSSIER, "phrases.txt")

# Numéro de version des réglages : quand les valeurs par défaut de certaines clés changent, la valeur
# enregistrée dans capri_config.json est remplacée une seule fois (voir MIGRATIONS).
VERSION_CONFIG = 3
MIGRATIONS = {
    2: [("phrases", "visible_secondes"), ("phrases", "cachee_secondes")],
    3: [("avatar", "positions")],
}

DEFAUTS = {
    "version": VERSION_CONFIG,
    "avatar": {
        "taille": "moyenne",            # petite | moyenne | grande
        "opacite": 1.0,                 # 0.3 -> 1.0
        "bulle": True,                  # sous-titres près de Capri
        "deplacements_auto": True,      # téléportations spontanées (False = jamais)
        # jamais | rare | normale | frequente | intense (menu « Téléportation automatique »)
        "frequence_teleportation": "normale",
        "apparitions_auto": True,       # elle disparaît et réapparaît d'elle-même
        "expressions_auto": True,       # elle change d'expression toute seule quand on ne lui dit rien
        "cliquable": True,              # False : les clics traversent Capri (elle ne peut plus être déplacée)
        "duree_teleportation": 0.6,     # secondes (plus petit = plus rapide)
        "duree_apparition": 0.5,
        "duree_disparition": 0.45,
        # endroits où elle peut apparaître ou se téléporter d'elle-même : "aleatoire" = n'importe où sur l'écran,
        # ou bas_droite | bas_gauche | haut_droite | haut_gauche | centre (mélangeables)
        "positions": ["aleatoire"],
        "eclairs_cachee": True,         # éclairs qui traversent l'écran pendant qu'elle est cachée
        "eclairs_secondes": [6, 25],    # délai min/max entre deux éclairs
        "position": "bas_droite",       # dernière position (ou "libre" si hors des endroits nommés)
        "x": None,
        "y": None,
    },
    "voix": {
        "moteur": "auto",               # auto (voix de Capri puis secours) | capri | local | edge | windows
        "fichier_voix": "capri_french.safetensors",  # voix de Capri (Pocket-TTS), à côté de assistant_vocal.py
        "muet": False,
        "volume": 0.9,
        "vitesse": 1.05,                # tempo global de la parole
        "hauteur": 1.04,                # >1 = voix plus claire/jeune
        "edge_voix": "fr-FR-VivienneMultilingualNeural",
        "windows_voix": "Hortense",
    },
    "ecoute": {
        "anglais_secours": True,        # retente en anglais si le français échoue
        "attente_demande_secondes": 10, # après un « Capri » seul, elle attend la demande pendant ce délai
        # mots que la reconnaissance vocale entend parfois à la place de « Capri » : ils comptent comme son nom
        # s'ils commencent la phrase (voir « hypothèses » dans capri_log.txt pour en ajouter)
        "alias_debut": ["café", "tapis", "capi", "kapi", "cap"],
        # vrais mots souvent entendus à la place de « Capri » (« prix recherche github ») : acceptés seulement
        # s'ils sont suivis d'un ordre reconnu, pour ne pas la réveiller à chaque « prix » prononcé
        "alias_si_ordre": ["prix", "pris", "pri", "prie", "pays", "paris", "capris"],
        # limites du seuil de détection de la voix : trop bas, le moindre souffle déclenche un enregistrement sans fin
        # et sa demande se perd ; trop haut, elle devient sourde. À ajuster si elle t'entend mal (ou trop de bruits).
        "seuil_min": 120,
        "seuil_max": 800,
    },
    "phrases": {
        "probabilite": 0.8,             # chance de dire une phrase de phrases.txt à chaque apparition/disparition
        "bavardage": True,              # elle dit aussi des phrases sans bouger ni disparaître
        "niveau_parole": "normale",     # silencieuse | discrete | normale | bavarde (menu « Elle parle... »)
        "visible_secondes": [30, 120],  # délai entre deux initiatives quand elle est à l'écran
        "cachee_secondes": [15, 75],    # durée cachée avant de réapparaître d'elle-même
    },
    "llm": {
        # "auto": actif dès qu'une clé API (ou un serveur local) est configuré
        "actif": "auto",
        "url": "https://api.openai.com/v1",
        "modele": "gpt-4o-mini",
        "cle_env": "OPENAI_API_KEY",
        "cle": "",
        "delai": 25,
    },
}

_verrou = threading.Lock()


def _fusion(base, extra):
    for cle, valeur in extra.items():
        if isinstance(valeur, dict) and isinstance(base.get(cle), dict):
            _fusion(base[cle], valeur)
        else:
            base[cle] = valeur
    return base


def charger():
    """Charge la configuration (valeurs par défaut + capri_config.json)."""
    config = copy.deepcopy(DEFAUTS)
    try:
        with open(FICHIER_CONFIG, "r", encoding="utf-8") as f:
            enregistree = json.load(f)
        _fusion(config, enregistree)
        version = enregistree.get("version", 1) if isinstance(enregistree, dict) else 1
        if version < VERSION_CONFIG:
            for v in range(version + 1, VERSION_CONFIG + 1):
                for section, cle in MIGRATIONS.get(v, []):
                    config[section][cle] = copy.deepcopy(DEFAUTS[section][cle])
            config["version"] = VERSION_CONFIG
            sauvegarder(config)
    except FileNotFoundError:
        sauvegarder(config)
    except (OSError, ValueError) as e:
        journal(f"Configuration illisible ({e}), valeurs par défaut utilisées")
    return config


def sauvegarder(config):
    try:
        with _verrou:
            with open(FICHIER_CONFIG, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
    except OSError as e:
        journal(f"Impossible d'enregistrer la configuration: {e}")


def journal(message):
    """Écrit dans capri_log.txt (et dans la console si elle existe)."""
    ligne = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    try:
        if sys.stdout is not None:
            enc = getattr(sys.stdout, "encoding", None) or "utf-8"
            print(ligne.encode(enc, "replace").decode(enc))
    except Exception:
        pass
    try:
        with _verrou:
            with open(FICHIER_JOURNAL, "a", encoding="utf-8") as f:
                f.write(ligne + "\n")
    except OSError:
        pass
