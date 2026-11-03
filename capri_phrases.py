"""
Phrases spontanées de Capri, lues dans phrases.txt.

Format du fichier (texte brut UTF-8, modifiable avec le Bloc-notes, relu automatiquement) :
  - une ligne = une réplique ; une ligne peut contenir plusieurs phrases, elles sont dites d'une traite ;
  - les lignes vides et celles qui commencent par # sont ignorées ;
  - un titre entre crochets seul sur sa ligne ([apparition], [disparition], [deplacement], [bavardage]) ouvre
    une section ; [bavardage] = phrases dites sans bouger ni disparaître ;
  - les lignes placées avant le premier titre servent de secours pour toutes les sections ;
  - une humeur facultative peut précéder la réplique : [enthousiaste] Coucou !
    (neutre, enthousiaste, taquine, agacee, suspicieuse, moi, montre, detendue, content, surprise).
"""

import os
import random
import re

import capri_config as cfg
from capri_cerveau import ETIQUETTES, normaliser

SECTIONS = ("apparition", "disparition", "deplacement", "bavardage")
EMOTION_PAR_DEFAUT = {"apparition": "excited", "disparition": "layingdown", "deplacement": "interested",
                      "bavardage": "interested"}

_ENTETE = re.compile(r"^\[([^\]]+)\]\s*$")
_HUMEUR = re.compile(r"^\[([^\]]+)\]\s*(.+)$")


class Phrases:
    def __init__(self, chemin=None):
        self.chemin = chemin or cfg.FICHIER_PHRASES
        self._signature = None
        self._lignes = {}
        self._derniere = {}

    def _charger(self):
        try:
            stat = os.stat(self.chemin)
        except OSError:
            self._lignes, self._signature = {}, None
            return
        signature = (stat.st_mtime_ns, stat.st_size)
        if signature == self._signature:
            return
        lignes, section = {}, "general"
        try:
            with open(self.chemin, "r", encoding="utf-8-sig") as f:
                contenu = f.read().splitlines()
        except (OSError, UnicodeDecodeError) as e:
            cfg.journal(f"phrases.txt illisible: {e}")
            return
        for brut in contenu:
            ligne = brut.strip()
            if not ligne or ligne.startswith("#"):
                continue
            entete = _ENTETE.match(ligne)
            if entete:
                nom = normaliser(entete.group(1))
                section = nom if nom in SECTIONS or nom == "general" else section
                continue
            emotion = None
            humeur = _HUMEUR.match(ligne)
            if humeur and normaliser(humeur.group(1)) in ETIQUETTES:
                emotion = ETIQUETTES[normaliser(humeur.group(1))]
                ligne = humeur.group(2).strip()
            lignes.setdefault(section, []).append((ligne, emotion))
        self._lignes, self._signature = lignes, signature

    def choisir(self, section):
        """Retourne (texte, émotion) d'une ligne au hasard pour la section, ou None s'il n'y en a pas."""
        self._charger()
        options = self._lignes.get(section) or self._lignes.get("general")
        if not options:
            return None
        possibles = [o for o in options if o[0] != self._derniere.get(section)] or options
        texte, emotion = random.choice(possibles)
        self._derniere[section] = texte
        return texte, emotion or EMOTION_PAR_DEFAUT.get(section, "interested")
