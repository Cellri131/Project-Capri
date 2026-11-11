"""
Chargement des sprites pixel-art de Capri.

Les images du dossier assets sont des grilles pixel-art agrandies (suffixe @10x, @8x...).
On les ramène à leur grille d'origine (mise en cache sur disque), on aligne les trois
variantes de bouche (closed / mid / full) puis on met à l'échelle pour l'écran.
"""

import glob
import math
import os
import re
import threading

from PIL import Image, ImageFilter

import capri_config as cfg

NEAREST = Image.Resampling.NEAREST
BOX = Image.Resampling.BOX

BOUCHES = ("closed", "mid", "full")

# Taille maximale d'un sprite, en pixels de grille d'origine
HAUTEUR_MAX = 170
LARGEUR_MAX = 256

EMOTIONS = (
    "interested", "interested_fullbody", "excited", "annoyed",
    "suspicious", "pointing", "pointingatherself", "layingdown",
)

# Sprites sans animation de bouche : clé -> motif regex sur le nom de fichier
SPRITES_SIMPLES = {
    "listening_blink": r"lookingatscreen_eyesclosed",
    "listening": r"lookingatscreen-\d",
    "searching": r"searchinginfo",
    "surprised": r"lookingatsmthsuprised",
    "happy": r"interestedhappy",
    "bored": r"lookingatsmthbored",
}

# Les dessins "pointing" sont recadrés séparément : décalage (en pixels de grille)
# qui superpose les yeux de chaque variante sur ceux de la variante "closed".
DECALAGES = {
    "pointing": {"mid": (6, 16), "full": (12, 25)},
}


def _facteur(chemin):
    m = re.search(r"@(\d+)x", os.path.basename(chemin))
    return int(m.group(1)) if m else 1


def _multiplicateur(chemin):
    """Les dessins en 16x ont une grille deux fois plus fine : on les double. Vaut aussi pour les fichiers déjà réduits."""
    m = re.search(r"[@_](\d+)x", os.path.basename(chemin))
    return 2 if m and int(m.group(1)) == 16 else 1


# Sprites de repli en mode « petite » (le dossier slim n'a pas toutes les expressions)
REPLI_SLIM = {
    "interested": "suspicious", "interested_fullbody": "suspicious", "excited": "suspicious", "happy": "suspicious",
    "bored": "suspicious", "surprised": "annoyed", "layingdown": "annoyed", "pointingatherself": "pointing",
}

# Ligne de l'image capri_OnPanel (en pixels de grille) qui touche le bord haut de la fenêtre
LIGNE_PERCHOIR = 156


def charger_grille(chemin):
    """Retourne l'image à sa résolution pixel-art native (avec cache disque)."""
    if _facteur(chemin) == 1:
        return Image.open(chemin).convert("RGBA")   # déjà à la taille de la grille
    nom = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(chemin))
    cache = os.path.join(cfg.DOSSIER_CACHE_SPRITES, nom)
    try:
        if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(chemin):
            return Image.open(cache).convert("RGBA")
    except OSError:
        pass
    im = Image.open(chemin).convert("RGBA")
    f = _facteur(chemin)
    grille = im.resize((max(1, im.width // f), max(1, im.height // f)), NEAREST)
    try:
        os.makedirs(cfg.DOSSIER_CACHE_SPRITES, exist_ok=True)
        grille.save(cache)
    except OSError:
        pass
    return grille


def mise_a_echelle(im, k):
    """Agrandit en gardant un rendu net (agrandissement entier puis réduction BOX)."""
    w, h = im.size
    cible = (max(1, round(w * k)), max(1, round(h * k)))
    if cible == im.size:
        return im
    m = max(1, math.ceil(k))
    if m > 1 and k != m:
        im = im.resize((w * m, h * m), NEAREST)
        return im.resize(cible, BOX)
    if k >= 1:
        return im.resize(cible, NEAREST)
    return im.resize(cible, BOX)


class Sprite:
    """Image prête à afficher + calques d'effets calculés à la demande."""

    def __init__(self, img):
        self.img = img
        self.w, self.h = img.size
        self._glows = {}
        self._silhouettes = {}

    def halo(self, marge):
        """Masque 'L' flou (agrandi de `marge` px de chaque côté) pour la lueur néon."""
        if marge not in self._glows:
            alpha = self.img.getchannel("A")
            grand = Image.new("L", (self.w + 2 * marge, self.h + 2 * marge), 0)
            grand.paste(alpha, (marge, marge))
            flou = grand.filter(ImageFilter.GaussianBlur(max(1, marge * 0.55)))
            self._glows[marge] = flou.point(lambda v: min(255, int(v * 1.7)))
        return self._glows[marge]

    def silhouette(self, couleur, opacite=0.6):
        """Copie monochrome du sprite (séparation de canaux / traînées)."""
        cle = (couleur, opacite)
        if cle not in self._silhouettes:
            sil = Image.new("RGBA", (self.w, self.h), couleur + (0,))
            sil.putalpha(self.img.getchannel("A").point(lambda v: int(v * opacite)))
            self._silhouettes[cle] = sil
        return self._silhouettes[cle]


class Bibliotheque:
    """Index des fichiers d'assets et cache des sprites mis à l'échelle."""

    def __init__(self, k, slim=False):
        self.k = k
        self.slim = slim
        self._verrou = threading.RLock()
        self._cache = {}
        self._mouth = {}
        self._simples = {}
        self._slim_mouth = {}
        self._slim_simples = {}
        self._perchoir = None
        self._indexer()

    def _classer(self, chemin, mouth, simples):
        nom = os.path.basename(chemin).lower()
        m = re.match(r"done_capri_(.+)_(closed|mid|full)-\d", nom)
        if m and m.group(1) in EMOTIONS:
            mouth.setdefault(m.group(1), {})[m.group(2)] = chemin
            return
        for cle, motif in SPRITES_SIMPLES.items():
            if re.search(motif, nom):
                simples[cle] = chemin
                return

    def _indexer(self):
        racines = (cfg.DOSSIER_ASSETS, cfg.DOSSIER_CACHE_SPRITES)
        for racine in racines:
            for chemin in glob.glob(os.path.join(racine, "**", "*.png"), recursive=True):
                nom = os.path.basename(chemin).lower()
                if "slim" in os.path.relpath(chemin, racine).lower().split(os.sep)[:-1]:
                    self._classer(chemin, self._slim_mouth, self._slim_simples)
                elif nom.startswith("capri_onpanel"):
                    self._perchoir = self._perchoir or chemin
                elif racine == cfg.DOSSIER_ASSETS:
                    self._classer(chemin, self._mouth, self._simples)

    def disponible(self):
        return bool(self._mouth or self._simples)

    def changer_echelle(self, k):
        with self._verrou:
            if abs(k - self.k) > 1e-3:
                self.k = k
                self._cache.clear()

    def utiliser_slim(self, actif):
        """Mode « petite » : seuls les sprites du dossier slim sont utilisés (s'il existe)."""
        with self._verrou:
            actif = bool(actif and (self._slim_mouth or self._slim_simples))
            if actif != self.slim:
                self.slim = actif
                self._cache.clear()

    def perchoir_disponible(self):
        return self._perchoir is not None

    def cles(self):
        return list(self._mouth) + list(self._simples)

    def _sources(self, cle):
        """(fichiers_bouche, fichier_simple) du sprite demandé selon le mode, ou (None, None)."""
        if self.slim:
            cle = cle if (cle in self._slim_mouth or cle in self._slim_simples) else REPLI_SLIM.get(cle, cle)
            if cle in self._slim_mouth:
                return self._slim_mouth[cle], None
            if cle in self._slim_simples:
                return None, self._slim_simples[cle]
        if cle in self._mouth:
            return self._mouth[cle], None
        return None, self._simples.get(cle)

    def _construire_perchoir(self):
        grille = charger_grille(self._perchoir)
        mult = _multiplicateur(self._perchoir)
        k = self._echelle_effective(*grille.size, mult)
        sp = Sprite(mise_a_echelle(grille, k))
        sp.h_grille = grille.height
        return {"closed": sp}

    def ligne_perchoir(self):
        """Position (en pixels écran) de la ligne de contact dans le sprite perché."""
        sp = self.sprite("perchoir")
        return sp.h * LIGNE_PERCHOIR / max(1, sp.h_grille) if sp else 0

    def _construire_emotion(self, cle, fichiers=None):
        fichiers = fichiers or self._mouth[cle]
        decalages = DECALAGES.get(cle, {})
        grilles = {}
        for etat in BOUCHES:
            chemin = fichiers.get(etat) or fichiers.get("closed")
            grilles[etat] = (charger_grille(chemin), decalages.get(etat, (0, 0)))
        largeur = max(g.width + d[0] for g, d in grilles.values())
        hauteur = max(g.height + d[1] for g, d in grilles.values())
        toiles = {}
        for etat, (g, d) in grilles.items():
            toile = Image.new("RGBA", (largeur, hauteur), (0, 0, 0, 0))
            toile.paste(g, d)
            toiles[etat] = toile
        # Recadrage commun pour que les trois bouches restent superposées
        boite = None
        for toile in toiles.values():
            b = toile.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
            if b:
                boite = b if boite is None else (
                    min(boite[0], b[0]), min(boite[1], b[1]), max(boite[2], b[2]), max(boite[3], b[3]))
        mult = _multiplicateur(fichiers["closed"])
        recadrees = {etat: toile.crop(boite) if boite else toile for etat, toile in toiles.items()}
        k = self._echelle_effective(*recadrees["closed"].size, mult)
        return {etat: Sprite(mise_a_echelle(im, k)) for etat, im in recadrees.items()}

    def _echelle_effective(self, w, h, mult):
        """Les dessins très hauts (pointing, surprised...) sont réduits pour rester discrets."""
        reduction = min(1.0, HAUTEUR_MAX / (h * mult), LARGEUR_MAX / (w * mult))
        return self.k * mult * reduction

    def _construire_simple(self, chemin):
        mult = _multiplicateur(chemin)
        grille = charger_grille(chemin)
        return {"closed": Sprite(mise_a_echelle(grille, self._echelle_effective(*grille.size, mult)))}

    def sprite(self, cle, bouche="closed"):
        """Retourne le Sprite demandé (repli sur 'interested' si absent)."""
        with self._verrou:
            if cle == "perchoir":
                if not self._perchoir:
                    return None
                if "perchoir" not in self._cache:
                    self._cache["perchoir"] = self._construire_perchoir()
                return self._cache["perchoir"]["closed"]
            fichiers, simple = self._sources(cle)
            if not fichiers and not simple:
                cle = "interested" if "interested" in self._mouth else next(iter(self.cles()), None)
                if cle is None:
                    return None
                fichiers, simple = self._sources(cle)
            cache_cle = (cle, self.slim)
            if cache_cle not in self._cache:
                self._cache[cache_cle] = (
                    self._construire_emotion(cle, fichiers) if fichiers else self._construire_simple(simple))
            variantes = self._cache[cache_cle]
            return variantes.get(bouche) or variantes["closed"]

    def precharger(self):
        for cle in self.cles():
            try:
                self.sprite(cle)
            except Exception as e:  # une image corrompue ne doit pas bloquer Capri
                cfg.journal(f"Sprite '{cle}' ignoré: {e}")
