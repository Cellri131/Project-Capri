"""
Avatar de Capri.

Fenêtre Windows translucide (alpha par pixel), sans bordure, toujours au premier plan.
Seuls les pixels visibles de Capri interceptent la souris : le reste de l'écran
reste utilisable normalement.

Effets : flottement, glitchs, fragments numériques à l'apparition/disparition,
téléportation avec traînées roses et vertes, bulle de texte néon.
"""

import ctypes
import math
import os
import queue
import random
import threading
import time
from ctypes import wintypes as wt

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

import capri_config as cfg
from capri_sprites import Bibliotheque

ROSE = (255, 32, 130)
VERT = (0, 255, 120)
BLANC = (235, 255, 245)

# Palette des éclairs, tirée des sprites : rose vif, vert néon, contour violet
ECLAIR_ROSE = (254, 20, 74)
ECLAIR_VERT = (40, 255, 110)
ECLAIR_SOMBRE = (17, 13, 29)
ECLAIR_VIOLET = (141, 13, 231)

# ---------------------------------------------------------------- Win32 ----

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
CS_DBLCLKS = 0x0008
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
ULW_ALPHA = 2
PM_REMOVE = 1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
WM_DESTROY, WM_MOUSEACTIVATE = 0x0002, 0x0021
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x0200, 0x0201, 0x0202, 0x0203, 0x0205
TPM_RETURNCMD, TPM_RIGHTBUTTON = 0x0100, 0x0002
MF_STRING = 0x0000
SPI_GETWORKAREA = 0x0030
SM_CXSCREEN, SM_CYSCREEN = 0, 1
WM_SETICON = 0x0080
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x0010, 0x0040
NB_RANGEES = 10   # nombre de segments de l'arête en zigzag lors des apparitions


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
        ("hCursor", wt.HICON), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wt.HWND), ("message", wt.UINT), ("wParam", wt.WPARAM), ("lParam", wt.LPARAM),
                ("time", wt.DWORD), ("pt", wt.POINT)]


def _signatures():
    user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wt.ATOM
    user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
    user32.CreateWindowExW.restype = wt.HWND
    user32.DestroyWindow.argtypes = [wt.HWND]
    user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    user32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
    user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
    user32.GetDC.argtypes = [wt.HWND]
    user32.GetDC.restype = wt.HDC
    user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
    user32.UpdateLayeredWindow.argtypes = [
        wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT), ctypes.POINTER(wt.SIZE), wt.HDC,
        ctypes.POINTER(wt.POINT), wt.COLORREF, ctypes.POINTER(BLENDFUNCTION), wt.DWORD]
    user32.UpdateLayeredWindow.restype = wt.BOOL
    user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
    user32.SetCapture.argtypes = [wt.HWND]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
    user32.LoadCursorW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
    user32.LoadCursorW.restype = wt.HICON
    user32.SystemParametersInfoW.argtypes = [wt.UINT, wt.UINT, ctypes.c_void_p, wt.UINT]
    user32.CreatePopupMenu.restype = wt.HMENU
    user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
    user32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, ctypes.c_void_p]
    user32.DestroyMenu.argtypes = [wt.HMENU]
    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
    user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
    user32.LoadImageW.restype = wt.HANDLE
    user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.SendMessageW.restype = LRESULT
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
    gdi32.CreateCompatibleDC.restype = wt.HDC
    gdi32.CreateDIBSection.argtypes = [wt.HDC, ctypes.POINTER(BITMAPINFO), wt.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD]
    gdi32.CreateDIBSection.restype = wt.HBITMAP
    gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
    gdi32.SelectObject.restype = wt.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wt.HDC]
    kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wt.HMODULE


_signatures()


def rendre_dpi_precis():
    """Coordonnées en pixels physiques (sinon Windows étire la fenêtre)."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def zone_de_travail():
    """Zone utile de l'écran principal (hors barre des tâches)."""
    r = wt.RECT()
    if user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0):
        return r.left, r.top, r.right, r.bottom
    return 0, 0, user32.GetSystemMetrics(SM_CXSCREEN), user32.GetSystemMetrics(SM_CYSCREEN)


def _bgra_premultiplie(img):
    r, g, b, a = img.convert("RGBa").split()
    return Image.merge("RGBA", (b, g, r, a)).tobytes()


class FenetreCalque:
    """Fenêtre popup à alpha par pixel (UpdateLayeredWindow)."""

    CLASSE = "CapriAvatarCalque"

    def __init__(self, rappel_messages):
        self._rappel = rappel_messages
        self._wndproc = WNDPROC(self._proc)
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.style = CS_DBLCLKS
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.hCursor = user32.LoadCursorW(None, 32512)
        wc.lpszClassName = self.CLASSE
        user32.RegisterClassW(ctypes.byref(wc))  # déjà enregistrée en cas de relance : sans conséquence
        self.hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            self.CLASSE, "Capri", WS_POPUP, 0, 0, 1, 1, None, None, hinst, None)
        if not self.hwnd:
            raise OSError(f"CreateWindowEx a échoué ({ctypes.get_last_error()})")
        self._hdc_ecran = user32.GetDC(None)
        self._hdc_mem = gdi32.CreateCompatibleDC(self._hdc_ecran)
        self._bitmap = None
        self._ancien = None
        self._bits = ctypes.c_void_p()
        self._taille = (0, 0)
        self.visible = False

    def _proc(self, hwnd, msg, wp, lp):
        try:
            if msg == WM_MOUSEACTIVATE:
                return 3  # MA_NOACTIVATE : cliquer sur Capri ne vole pas le focus
            retour = self._rappel(msg, wp, lp)
            if retour is not None:
                return retour
        except Exception as e:
            cfg.journal(f"Erreur fenêtre avatar: {e}")
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def _creer_bitmap(self, w, h):
        if self._bitmap:
            gdi32.SelectObject(self._hdc_mem, self._ancien)
            gdi32.DeleteObject(self._bitmap)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        self._bitmap = gdi32.CreateDIBSection(self._hdc_mem, ctypes.byref(bmi), 0, ctypes.byref(self._bits), None, 0)
        old = gdi32.SelectObject(self._hdc_mem, self._bitmap)
        if self._ancien is None:
            self._ancien = old
        self._taille = (w, h)

    def afficher(self, montrer):
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE if montrer else SW_HIDE)
        self.visible = montrer

    def au_premier_plan(self):
        user32.SetWindowPos(self.hwnd, wt.HWND(-1), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def definir_icone(self, chemin):
        """Icône de la fenêtre (grande et petite) chargée depuis un fichier .ico."""
        for taille in (1, 0):  # ICON_BIG, ICON_SMALL
            icone = user32.LoadImageW(None, chemin, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if icone:
                user32.SendMessageW(self.hwnd, WM_SETICON, taille, icone)

    def rendre_cliquable(self, cliquable):
        """Sans WS_EX_TRANSPARENT les clics sur Capri sont captés ; avec, ils traversent la fenêtre."""
        style = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        style = style & ~WS_EX_TRANSPARENT if cliquable else style | WS_EX_TRANSPARENT
        user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, style)

    def mettre_a_jour(self, img, x, y, opacite=255):
        w, h = img.size
        if (w, h) != self._taille:
            self._creer_bitmap(w, h)
        ctypes.memmove(self._bits, _bgra_premultiplie(img), w * h * 4)
        pt, taille, src = wt.POINT(x, y), wt.SIZE(w, h), wt.POINT(0, 0)
        blend = BLENDFUNCTION(0, 0, max(0, min(255, int(opacite))), 1)
        user32.UpdateLayeredWindow(self.hwnd, self._hdc_ecran, ctypes.byref(pt), ctypes.byref(taille),
                                   self._hdc_mem, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA)

    def pomper_messages(self):
        msg = MSG()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def detruire(self):
        try:
            user32.DestroyWindow(self.hwnd)
            if self._bitmap:
                gdi32.SelectObject(self._hdc_mem, self._ancien)
                gdi32.DeleteObject(self._bitmap)
            gdi32.DeleteDC(self._hdc_mem)
            user32.ReleaseDC(None, self._hdc_ecran)
        except Exception:
            pass


# ------------------------------------------------------------- utilitaires --

def _coller(canvas, im, x, y):
    """alpha_composite tolérant aux positions négatives / hors cadre."""
    cw, ch = canvas.size
    w, h = im.size
    sx, sy = max(0, -x), max(0, -y)
    dx, dy = max(0, x), max(0, y)
    ex, ey = min(w, cw - x), min(h, ch - y)
    if ex <= sx or ey <= sy:
        return
    canvas.alpha_composite(im, (dx, dy), (sx, sy, ex, ey))


def _ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _union(rects):
    return (min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects))


LUTS_FONDU = [[int(v * i / 8) for v in range(256)] for i in range(9)]


def _police(taille):
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for nom in ("bahnschrift.ttf", "consola.ttf", "segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(os.path.join(windir, "Fonts", nom), taille)
        except OSError:
            continue
    return ImageFont.load_default()


def _decouper(texte, police, largeur_max):
    lignes, courante = [], ""
    for mot in texte.split():
        essai = f"{courante} {mot}".strip()
        if police.getlength(essai) <= largeur_max or not courante:
            courante = essai
        else:
            lignes.append(courante)
            courante = mot
    if courante:
        lignes.append(courante)
    return lignes or [""]


# ------------------------------------------------------------------ avatar --

class AvatarCapri:
    TAILLES = {"petite": 0.8, "moyenne": 1.2, "grande": 1.7}
    COINS = ("bas_droite", "bas_gauche", "haut_droite", "haut_gauche", "centre")
    DELAI_SOMMEIL = 300.0   # après ce temps sans interaction, elle s'allonge et s'ennuie plus souvent
    DUREES_EFFETS = {"apparition": 0.5, "disparition": 0.45, "teleportation": 0.6}
    # Expressions de repos : (sprite, poids, durée min, durée max en secondes)
    POSES = (
        ("interested", 6.0, 6, 14), ("interested_fullbody", 1.2, 4, 8), ("pointingatherself", 0.9, 3, 6),
        ("happy", 1.3, 3, 6), ("excited", 1.0, 3, 6), ("suspicious", 1.3, 3, 7), ("bored", 1.6, 4, 9),
        ("annoyed", 0.5, 2, 4), ("surprised", 0.5, 2, 3), ("searching", 1.0, 3, 6), ("layingdown", 1.2, 6, 14),
    )
    MENU = {1: "masquer", 2: "teleporter", 3: "muet", 4: "pause", 5: "quitter"}

    def __init__(self, config, etat_voix=None, rappel=None):
        self.config = config
        self.cfg = config["avatar"]
        self._etat_voix = etat_voix or (lambda: None)
        self._rappel_ext = rappel or (lambda *a, **k: None)
        self._cmds = queue.SimpleQueue()
        self._thread = None
        self._pret = threading.Event()
        self._actif = False
        self.eco = False

        self.mode_courant = "repos"
        self.emotion = "interested"
        self._pose = ("interested", time.monotonic() + 8)   # expression de repos en cours et instant de son prochain changement
        self._mode_fin = None
        self._derniere_activite = time.monotonic()
        self._bulle = None
        self._visible = False

    # ---------------------------------------------------- API publique ----

    def demarrer(self):
        self._actif = True
        self._thread = threading.Thread(target=self._boucle_protegee, name="capri-avatar", daemon=True)
        self._thread.start()
        self._pret.wait(15)

    def arreter(self):
        self._cmds.put(("stop",))
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(3)

    @property
    def visible(self):
        return self._visible

    def duree_effet(self, nom):
        """Durée (s) d'un effet d'éclair : apparition, disparition ou teleportation (réglable dans capri_config.json)."""
        try:
            return max(0.15, float(self.cfg.get(f"duree_{nom}", self.DUREES_EFFETS[nom])))
        except (TypeError, ValueError):
            return self.DUREES_EFFETS[nom]

    def definir_mode(self, mode, emotion=None, duree=None):
        now = time.monotonic()
        if emotion:
            self.emotion = emotion
        self._mode_fin = now + duree if duree else None
        self.mode_courant = mode
        if mode not in ("repos", "dort"):
            self._derniere_activite = now
            self._pose = ("interested", now + random.uniform(3, 6))   # elle reprend son air habituel

    def afficher_bulle(self, texte, duree=0.0):
        self._cmds.put(("bulle", texte, max(0.0, duree)))

    def afficher_utilisateur(self, texte):
        self._cmds.put(("bulle_user", texte))

    def effacer_bulle(self):
        self._cmds.put(("bulle_off",))

    def montrer(self, coin=None):
        """Fait apparaître Capri (à son dernier emplacement, ou dans `coin` : un coin ou "hasard")."""
        self._cmds.put(("montrer", coin))

    def cacher(self):
        self._cmds.put(("cacher",))

    def basculer(self):
        self._cmds.put(("cacher",) if self._visible else ("montrer", None))

    @property
    def en_transition(self):
        return self._fx is not None

    def teleporter(self, destination=None):
        """Téléportation visible : un nom d'endroit, un point (x, y), ou None/"hasard"."""
        self._cmds.put(("tp", destination))

    def eclair_traversant(self, origine=None, dest=None):
        """Éclair qui traverse l'écran pendant que Capri est cachée (trajet au hasard par défaut)."""
        self._cmds.put(("traversee", origine, dest, False))

    def apparaitre_par_eclair(self, dest=None):
        """Un éclair traverse l'écran puis Capri se forme là où il s'arrête (point au hasard par défaut)."""
        self._cmds.put(("traversee", None, dest, True))

    @property
    def en_traversee(self):
        return self._fx_solo is not None

    def changer_taille(self, nom):
        self._cmds.put(("taille", nom))

    def reagir(self):
        self._cmds.put(("poke",))

    def definir_cliquable(self, cliquable):
        self._cmds.put(("cliquable", cliquable))

    # ------------------------------------------------------- initialisation --

    def _boucle_protegee(self):
        try:
            self._boucle()
        except Exception as e:
            import traceback
            cfg.journal(f"Avatar arrêté suite à une erreur: {e}\n{traceback.format_exc()}")
        finally:
            self._pret.set()
            self._actif = False

    def _echelle_pour(self, nom):
        h = max(1, user32.GetSystemMetrics(SM_CYSCREEN))
        return self.TAILLES.get(nom, 1.5) * max(0.75, min(2.0, h / 1080))

    def _recalculer_echelle(self):
        self.k = self._echelle_pour(self.cfg.get("taille", "moyenne"))
        self.pad = max(10, int(14 * self.k))
        self.police_texte = _police(max(13, int(7.5 * self.k + 5)))
        self.police_titre = _police(max(10, int(5 * self.k + 4)))
        self._img_bulle = None
        if hasattr(self, "biblio"):
            self.biblio.changer_echelle(self.k)

    def _init(self):
        rendre_dpi_precis()
        self.fen = FenetreCalque(self._messages)
        self.fen.rendre_cliquable(self.cfg.get("cliquable", True))
        self.zone = zone_de_travail()
        self._recalculer_echelle()
        self.biblio = Bibliotheque(self.k)
        if not self.biblio.disponible():
            raise FileNotFoundError(f"Aucun sprite trouvé dans {cfg.DOSSIER_ASSETS}")
        self.biblio.sprite("interested")
        threading.Thread(target=self.biblio.precharger, name="capri-sprites", daemon=True).start()

        self._fx = None
        self._fx_solo = None
        self._glitch = None
        self._cle_prec = None
        self._particules = []
        self._drag = None
        self._t_zone = 0.0
        self._t_premier_plan = 0.0
        now = time.monotonic()
        self._prochain_glitch = now + random.uniform(3, 6)
        self._prochain_scan = now + random.uniform(4, 8)
        self._scan_fin = 0.0
        self._ancre = self._ancre_coin(self.cfg.get("position", "bas_droite"))
        self.fen.definir_icone(cfg.ICONE_FENETRE if os.path.exists(cfg.ICONE_FENETRE) else cfg.ICONE_ICO)

    # --------------------------------------------------------- positions ----

    def _ancre_coin(self, coin):
        """(centre_x, bas_y) de l'ancrage de Capri pour un endroit de l'écran (coin ou centre)."""
        if coin == "libre" and self.cfg.get("x") is not None and self.cfg.get("y") is not None:
            return self._borner_ancre(float(self.cfg["x"]), float(self.cfg["y"]))
        if coin not in self.COINS:
            coin = "bas_droite"
        l, t, r, b = self.zone
        if coin == "centre":
            return self._borner_ancre((l + r) / 2, (t + b) / 2 + 80 * self.k)
        marge = int(28 * self.k)
        demi = 128 * self.k
        haut = 150 * self.k
        cx = r - marge - demi if coin.endswith("droite") else l + marge + demi
        by = b - marge if coin.startswith("bas") else t + marge + haut + int(60 * self.k)
        return self._borner_ancre(cx, by)

    def _borner_ancre(self, cx, by):
        l, t, r, b = self.zone
        return (min(max(cx, l + 40), r - 40), min(max(by, t + 60), b))

    def _position_aleatoire(self):
        """Ancrage (centre_x, bas_y) tiré au hasard n'importe où sur l'écran, loin de la position actuelle."""
        sp = self.biblio.sprite("interested")
        l, t, r, b = self.zone
        marge = int(24 * self.k)
        demi, haut = sp.w / 2, sp.h
        x0, x1 = l + demi + marge, max(l + demi + marge, r - demi - marge)
        y0, y1 = t + haut + marge + 80 * self.k, max(t + haut + marge + 80 * self.k, b - marge)
        point = None
        for _ in range(12):
            point = (random.uniform(x0, x1), random.uniform(y0, y1))
            if math.hypot(point[0] - self._ancre[0], point[1] - self._ancre[1]) > 0.25 * (r - l):
                break
        return self._borner_ancre(*point)

    def _coin_hasard(self):
        """Une destination tirée parmi `positions` (capri_config.json) : nom d'endroit ou point (x, y) quelconque."""
        permis = [c for c in self.cfg.get("positions", ["aleatoire"]) if c in self.COINS or c == "aleatoire"] or ["aleatoire"]
        autres = [c for c in permis if c != self.cfg.get("position")]
        choix = random.choice(autres or permis)
        return self._position_aleatoire() if choix == "aleatoire" else choix

    def position_aleatoire(self):
        """Point (x, y) où elle peut apparaître, utilisable avec montrer() et teleporter()."""
        return self._position_aleatoire()

    # ----------------------------------------------------------- messages ----

    def _curseur(self):
        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def _messages(self, msg, wp, lp):
        if msg == WM_LBUTTONDOWN:
            user32.SetCapture(self.fen.hwnd)
            self._drag = {"c0": self._curseur(), "a0": self._ancre, "bouge": False}
            return 0
        if msg == WM_MOUSEMOVE and self._drag:
            cx, cy = self._curseur()
            dx, dy = cx - self._drag["c0"][0], cy - self._drag["c0"][1]
            if self._drag["bouge"] or abs(dx) + abs(dy) > 5:
                self._drag["bouge"] = True
                self._ancre = self._borner_ancre(self._drag["a0"][0] + dx, self._drag["a0"][1] + dy)
            return 0
        if msg == WM_LBUTTONUP and self._drag:
            user32.ReleaseCapture()
            drag, self._drag = self._drag, None
            if drag["bouge"]:
                self.cfg["position"] = "libre"
                self.cfg["x"], self.cfg["y"] = round(self._ancre[0]), round(self._ancre[1])
                cfg.sauvegarder(self.config)
            else:
                self._poke()
                self._rappel_ext("clic")
            return 0
        if msg == WM_LBUTTONDBLCLK:
            self._rappel_ext("double_clic")
            return 0
        if msg == WM_RBUTTONUP:
            self._menu_contextuel()
            return 0
        return None

    def _menu_contextuel(self):
        menu = user32.CreatePopupMenu()
        libelles = {1: "Cacher Capri", 2: "Se téléporter ailleurs", 3: "Voix : couper / réactiver",
                    4: "Écoute : pause / reprise", 5: "Quitter"}
        for ident, texte in libelles.items():
            user32.AppendMenuW(menu, MF_STRING, ident, texte)
        x, y = self._curseur()
        user32.SetForegroundWindow(self.fen.hwnd)
        choix = user32.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON, x, y, 0, self.fen.hwnd, None)
        user32.DestroyMenu(menu)
        if choix in self.MENU:
            self._rappel_ext("menu", action=self.MENU[choix])

    # ------------------------------------------------------------- commandes --

    def _traiter_commandes(self, now):
        while True:
            try:
                cmd = self._cmds.get_nowait()
            except queue.Empty:
                return True
            nom = cmd[0]
            if nom == "stop":
                return False
            elif nom == "bulle":
                self._bulle = {"texte": cmd[1], "t0": now, "duree": cmd[2], "user": (self._bulle or {}).get("user"),
                               "t_user": (self._bulle or {}).get("t_user", 0)}
                self._derniere_activite = now
            elif nom == "bulle_user":
                ancien = self._bulle if self._bulle and now < self._bulle_fin(self._bulle) else None
                self._bulle = {"texte": "", "t0": now, "duree": 0, "user": cmd[1], "t_user": now}
                if ancien and ancien["texte"] and now - ancien["t0"] < 1.5:
                    self._bulle.update(texte=ancien["texte"], t0=ancien["t0"], duree=ancien["duree"])
                self._derniere_activite = now
            elif nom == "bulle_off":
                self._bulle = None
            elif nom == "montrer":
                self._montrer(now, cmd[1])
            elif nom == "cacher":
                self._cacher(now)
            elif nom == "tp":
                self._lancer_deplacement(now, cmd[1])
            elif nom == "traversee":
                self._lancer_traversee(now, cmd[1], cmd[2], cmd[3])
            elif nom == "taille":
                if cmd[1] in self.TAILLES:
                    self.cfg["taille"] = cmd[1]
                    cfg.sauvegarder(self.config)
                    self._recalculer_echelle()
                    self._ancre = self._ancre_coin(self.cfg.get("position", "bas_droite"))
            elif nom == "poke":
                self._poke()
            elif nom == "cliquable":
                self.fen.rendre_cliquable(cmd[1])

    def _poke(self):
        now = time.monotonic()
        self._declencher_glitch(now, 0.35)
        if self.mode_courant == "repos":
            self.definir_mode("surpris", duree=0.9)

    # ------------------------------------------------------- transitions ----

    def _nouveau_fx(self, type_fx, now, duree, **extra):
        """Transition avec une forme d'éclair propre : arête en zigzag et sens du balayage."""
        fx = {"type": type_fx, "t0": now, "duree": duree, "pente": random.uniform(-0.55, 0.55),
              "sens": random.choice((-1, 1)), "zig": [random.uniform(-0.5, 0.5) for _ in range(NB_RANGEES + 1)]}
        fx.update(extra)
        return fx

    def _montrer(self, now, coin=None):
        if self._visible and not (self._fx and self._fx["type"] == "disparition"):
            return
        self._fx_solo = None
        if coin == "hasard":
            coin = self._coin_hasard()
        if isinstance(coin, tuple):
            self._ancre = self._borner_ancre(*coin)
            self.cfg["position"] = "libre"
            self.cfg["x"], self.cfg["y"] = round(self._ancre[0]), round(self._ancre[1])
            cfg.sauvegarder(self.config)
        elif coin in self.COINS:
            self.cfg["position"] = coin
            self._ancre = self._ancre_coin(coin)
            cfg.sauvegarder(self.config)
        self._visible = True
        self.fen.afficher(True)
        self._fx = self._nouveau_fx("apparition", now, self.duree_effet("apparition"))

    def _cacher(self, now):
        if not self._visible or (self._fx and self._fx["type"] == "disparition"):
            return
        self._fx = self._nouveau_fx("disparition", now, self.duree_effet("disparition"))

    def _lancer_deplacement(self, now, destination):
        if not self._visible or (self._fx and self._fx["type"] in ("disparition", "teleport")):
            return
        if destination in (None, "hasard"):
            destination = self._coin_hasard()
        if destination in self.COINS:
            dest = self._ancre_coin(destination)
            self.cfg["position"] = destination
        else:
            dest = self._borner_ancre(*destination)
            self.cfg["position"] = "libre"
            self.cfg["x"], self.cfg["y"] = round(dest[0]), round(dest[1])
        cfg.sauvegarder(self.config)
        self._fx = self._nouveau_fx("teleport", now, self.duree_effet("teleportation"), origine=self._ancre, dest=dest)

    # Éclairs qui traversent l'écran sans que Capri soit visible

    def duree_traversee(self):
        return self.duree_effet("teleportation") + 0.2

    def _lancer_traversee(self, now, origine, dest, puis_montrer=False):
        """Éclair qui traverse l'écran ; avec `puis_montrer`, Capri se forme là où il s'arrête (dest ou au hasard)."""
        if self._visible or self._fx_solo:
            return
        l, t, r, b = self.zone
        puis = None
        if puis_montrer:
            puis = dest if dest is not None else self._coin_hasard()
            ancre = self._ancre_coin(puis) if isinstance(puis, str) else self._borner_ancre(*puis)
            dest = (ancre[0], ancre[1] - self.biblio.sprite("interested").h / 2)
        if origine is None:
            # un bord de l'écran au hasard vers un point éloigné
            if random.random() < 0.5:
                origine = (random.choice((l, r)), random.uniform(t, b))
            else:
                origine = (random.uniform(l, r), random.choice((t, b)))
        if dest is None:
            dest = (random.uniform(l, r), random.uniform(t, b))
            for _ in range(8):
                if math.hypot(dest[0] - origine[0], dest[1] - origine[1]) > 0.4 * (r - l):
                    break
                dest = (random.uniform(l, r), random.uniform(t, b))
        self.fen.afficher(True)
        self._fx_solo = {"t0": now, "duree": self.duree_traversee(), "o": origine, "d": dest, "puis": puis}

    def _etat_fx(self, now):
        """Retourne (p_forme, ancre, phase_trajet) selon la transition en cours."""
        fx = self._fx
        if not fx:
            return 1.0, self._ancre, None
        t = (now - fx["t0"]) / fx["duree"]
        if t >= 1.0:
            self._terminer_fx(fx)
            return (1.0 if fx["type"] != "disparition" else 0.0), self._ancre, None
        kind = fx["type"]
        if kind == "apparition":
            return _ease(t), self._ancre, None
        if kind == "disparition":
            return 1.0 - _ease(t), self._ancre, None
        o, d = fx["origine"], fx["dest"]
        # teleport : l'éclair efface Capri, traverse l'écran, puis la reforme à l'arrivée
        if t < 0.33:
            return 1.0 - _ease(t / 0.33), o, None
        if t < 0.62:
            s = _ease((t - 0.33) / 0.29)
            return 0.0, (o[0] + (d[0] - o[0]) * s, o[1] + (d[1] - o[1]) * s), s
        return _ease((t - 0.62) / 0.38), d, None

    def _terminer_fx(self, fx):
        if fx["type"] == "teleport":
            self._ancre = fx["dest"]
        elif fx["type"] == "disparition":
            self._visible = False
            self.fen.afficher(False)
        self._fx = None

    # ----------------------------------------------------------- effets -----

    def _declencher_glitch(self, now, duree=0.22):
        self._glitch = {"fin": now + duree, "maj": 0.0, "bandes": [], "d": max(2, int(3 * self.k / 1.5))}

    def _maj_glitch(self, now, sp):
        g = self._glitch
        if not g:
            if now >= self._prochain_glitch:
                self._declencher_glitch(now, random.uniform(0.12, 0.3))
                self._prochain_glitch = now + random.uniform(5, 13)
            return None
        if now >= g["fin"]:
            self._glitch = None
            return None
        if now - g["maj"] > 0.05:
            g["maj"] = now
            g["bandes"] = []
            for _ in range(random.randint(1, 3)):
                y0 = random.randint(0, max(1, sp.h - 6))
                g["bandes"].append((y0, min(sp.h, y0 + random.randint(3, max(4, sp.h // 8))),
                                    random.randint(-int(14 * self.k), int(14 * self.k))))
        return g

    def _appliquer_bandes(self, img, bandes):
        sortie = img.copy()
        w = img.width
        for y0, y1, dx in bandes:
            region = img.crop((0, y0, w, y1))
            sortie.paste((0, 0, 0, 0), (0, y0, w, y1))
            sortie.paste(region, (dx, y0))
        return sortie

    # ------------------------------------------------------------ éclairs ----

    def _trait(self):
        """Épaisseur du contour violet des éclats."""
        return max(1, int(self.k * 0.9))

    @staticmethod
    def _couleur_eclair():
        r = random.random()
        return ECLAIR_ROSE if r < 0.5 else ECLAIR_VERT if r < 0.92 else ECLAIR_SOMBRE

    @staticmethod
    def _lame(x, y, angle, longueur, largeur):
        """Éclat effilé et dentelé : (polygone, points de paillettes)."""
        ca, sa = math.cos(angle), math.sin(angle)
        gauche, droite, pailles = [], [], []
        for t, w in ((0.0, 1.0), (0.28, 0.5), (0.5, 0.85), (0.78, 0.3), (1.0, 0.0)):
            ax, ay = x + ca * longueur * t, y + sa * longueur * t
            wl = w * largeur / 2 * random.uniform(0.6, 1.25)
            wr = w * largeur / 2 * random.uniform(0.6, 1.25)
            gauche.append((ax - sa * wl, ay + ca * wl))
            droite.append((ax + sa * wr, ay - ca * wr))
        for _ in range(3):
            t, lat = random.uniform(0.1, 0.7), random.uniform(-0.25, 0.25) * largeur
            pailles.append((x + ca * longueur * t - sa * lat, y + sa * longueur * t + ca * lat))
        return gauche + droite[::-1], pailles

    @staticmethod
    def _bande(pts, largeur):
        """Transforme une ligne brisée en éclair : polygone effilé aux deux bouts."""
        n = len(pts)
        gauche, droite = [], []
        for i, (px, py) in enumerate(pts):
            demi = largeur * (0.2 + 0.8 * math.sin(math.pi * i / (n - 1))) / 2
            ax, ay = pts[max(0, i - 1)]
            bx, by = pts[min(n - 1, i + 1)]
            tl = math.hypot(bx - ax, by - ay) or 1.0
            lx, ly = -(by - ay) / tl, (bx - ax) / tl
            gauche.append((px + lx * demi, py + ly * demi))
            droite.append((px - lx * demi, py - ly * demi))
        return gauche + droite[::-1]

    def _eclair(self, p0, p1, amplitude, largeur, segments):
        """Éclair en zigzag de p0 à p1."""
        (x0, y0), (x1, y1) = p0, p1
        dx, dy = x1 - x0, y1 - y0
        longueur = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / longueur, dx / longueur
        pts = [(x0, y0)]
        for i in range(1, segments):
            t, decal = i / segments, random.uniform(-amplitude, amplitude)
            pts.append((x0 + dx * t + nx * decal, y0 + dy * t + ny * decal))
        pts.append((x1, y1))
        return self._bande(pts, largeur)

    def _tracer(self, dessin, poly, couleur, pailles=()):
        dessin.polygon(poly, fill=couleur + (255,), outline=ECLAIR_VIOLET + (255,), width=self._trait())
        if couleur == ECLAIR_ROSE:
            for px, py in pailles:
                dessin.rectangle([px, py, px + 1, py + 1], fill=(255, 255, 255, 255))

    def _lames_autour(self, dessin, x, y, n, longueur_max, direction=None, ouverture=1.3):
        """Éclats qui jaillissent d'un point ; `direction` limite la gerbe à un cône."""
        for _ in range(n):
            if direction is not None and random.random() < 0.8:
                angle = direction + random.uniform(-ouverture, ouverture)
            else:
                angle = random.uniform(0, 2 * math.pi)
            longueur = longueur_max * random.uniform(0.25, 1.0)
            poly, pailles = self._lame(x, y, angle, longueur, longueur * random.uniform(0.12, 0.28))
            self._tracer(dessin, poly, self._couleur_eclair(), pailles)

    def _arete(self, sp, p, fx):
        """Arête en zigzag qui balaie le sprite (coordonnées du sprite)."""
        w, h = sp.w, sp.h
        saut = 0.1 * w
        derive = abs(fx["pente"]) * h / 2
        base = -(saut + derive) + p * (w + 2 * (saut + derive))
        pts = []
        for i in range(NB_RANGEES + 1):
            y = h * i / NB_RANGEES
            x = base + fx["pente"] * (y - h / 2) + fx["zig"][i] * saut
            pts.append((w - x if fx["sens"] < 0 else x, y))
        return pts

    def _dessiner_revelation(self, canvas, sp, img, xc, yc, p, fx):
        """Capri se forme (ou se défait) derrière une lame d'éclairs qui traverse son image."""
        pts = self._arete(sp, p, fx)
        masque = Image.new("L", (sp.w, sp.h), 0)
        coin = 0 if fx["sens"] > 0 else sp.w
        ImageDraw.Draw(masque).polygon([(coin, 0)] + pts + [(coin, sp.h)], fill=255)
        base = img.copy()
        base.putalpha(ImageChops.multiply(img.getchannel("A"), masque))
        _coller(canvas, base, xc, yc)

        dessin = ImageDraw.Draw(canvas)
        w = sp.w
        intensite = 0.4 + 0.6 * math.sin(math.pi * min(1.0, max(0.0, p)))
        absolus = [(xc + x, yc + y) for x, y in pts]
        saut = 0.03 * w
        for largeur, couleur in ((0.05 * w, ECLAIR_ROSE), (0.022 * w, ECLAIR_VERT)):
            ligne = [(x + random.uniform(-saut, saut), y) for x, y in absolus]
            self._tracer(dessin, self._bande(ligne, largeur), couleur)
        direction = 0.0 if fx["sens"] > 0 else math.pi
        for _ in range(int(5 + 9 * intensite)):
            i = random.randrange(len(absolus))
            x, y = absolus[i]
            self._lames_autour(dessin, x, y, 1, w * 0.4 * (0.5 + intensite), direction)
        if 0.12 < p < 0.9 and random.random() < 0.6:
            # grande lame qui coupe l'image en diagonale
            i = random.randrange(len(absolus))
            x, y = absolus[i]
            angle = direction + math.pi + random.uniform(-0.6, 0.6)
            poly, pailles = self._lame(x, y, angle, w * random.uniform(0.5, 0.9), w * 0.1)
            self._tracer(dessin, poly, ECLAIR_ROSE, pailles)

    def _dessiner_transit(self, canvas, s, fx, ox, oy, sp):
        """Éclairs qui traversent l'écran, de l'ancienne position à la nouvelle."""
        o, d = fx["origine"], fx["dest"]
        depart = (o[0] - ox, o[1] - sp.h / 2 - oy)
        arrivee = (d[0] - ox, d[1] - sp.h / 2 - oy)
        tete = (depart[0] + (arrivee[0] - depart[0]) * s, depart[1] + (arrivee[1] - depart[1]) * s)
        self._dessiner_eclair_entre(canvas, depart, tete, sp.w)
        self._lames_autour(ImageDraw.Draw(canvas), depart[0], depart[1], 5, sp.w * 0.3)

    def _dessiner_eclair_entre(self, canvas, depart, tete, w):
        """Éclairs en zigzag de `depart` à `tete` (largeur de référence `w`), avec une gerbe d'éclats à la tête."""
        distance = math.hypot(tete[0] - depart[0], tete[1] - depart[1])
        dessin = ImageDraw.Draw(canvas)
        if distance > 4:
            segments = max(6, int(distance / (0.12 * w)))
            amplitude = min(0.12 * w, max(0.03 * w, 0.04 * distance))
            for largeur, couleur in ((0.06 * w, ECLAIR_ROSE), (0.03 * w, ECLAIR_VERT), (0.018 * w, ECLAIR_ROSE)):
                self._tracer(dessin, self._eclair(depart, tete, amplitude, largeur, segments), couleur)
        self._lames_autour(dessin, tete[0], tete[1], 9, w * 0.4)

    def _rendre_solo(self, now):
        """Éclair qui traverse l'écran alors que Capri n'est pas visible."""
        fx = self._fx_solo
        t = (now - fx["t0"]) / fx["duree"]
        if t >= 1.0:
            self._fx_solo = None
            if fx["puis"] is not None:
                self._montrer(now, fx["puis"])
            else:
                self.fen.afficher(False)
            return
        s = _ease(t)
        o, d = fx["o"], fx["d"]
        w = self.biblio.sprite("interested").w
        tete = (o[0] + (d[0] - o[0]) * s, o[1] + (d[1] - o[1]) * s)
        queue = (o[0] + (d[0] - o[0]) * max(0.0, s - 0.6), o[1] + (d[1] - o[1]) * max(0.0, s - 0.6))
        marge = int(0.5 * w)
        sw_, sh_ = user32.GetSystemMetrics(SM_CXSCREEN), user32.GetSystemMetrics(SM_CYSCREEN)
        x0, y0 = max(0, int(min(o[0], d[0]) - marge)), max(0, int(min(o[1], d[1]) - marge))
        x1, y1 = min(sw_, int(max(o[0], d[0]) + marge)), min(sh_, int(max(o[1], d[1]) + marge))
        if x1 <= x0 or y1 <= y0:
            return
        canvas = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
        self._dessiner_eclair_entre(canvas, (queue[0] - x0, queue[1] - y0), (tete[0] - x0, tete[1] - y0), w)
        self.fen.mettre_a_jour(canvas, x0, y0, 255 * max(0.3, min(1.0, self.cfg.get("opacite", 1.0))))

    def _maj_particules(self, now, rect, dt):
        mode = self.mode_courant
        taux = {"ecoute": 14, "reflechit": 20, "parle": 9}.get(mode, 2.5)
        if self.eco:
            taux /= 2
        if random.random() < taux * dt and len(self._particules) < 40:
            x0, y0, x1, y1 = rect
            self._particules.append({
                "x": random.uniform(x0, x1), "y": random.choice((y0 + (y1 - y0) * random.random(), y1 - 4)),
                "vx": random.uniform(-8, 8), "vy": random.uniform(-40, -14) * self.k / 1.5,
                "t0": now, "vie": random.uniform(0.7, 1.5), "taille": random.choice((2, 3, 4)) if self.k < 1.8 else 4,
                "couleur": ROSE if random.random() < 0.55 else VERT})
        vivantes = []
        for q in self._particules:
            age = now - q["t0"]
            if age < q["vie"]:
                q["x"] += q["vx"] * dt
                q["y"] += q["vy"] * dt
                vivantes.append(q)
        self._particules = vivantes

    # -------------------------------------------------------------- bulle ----

    def _bulle_fin(self, b):
        fin_texte = b["t0"] + b["duree"] + 3.2 + 0.035 * len(b["texte"]) if b["texte"] else 0
        fin_user = b["t_user"] + 3.5 if b.get("user") else 0
        return max(fin_texte, fin_user)

    def _creer_image_bulle(self, b, revele, opacite):
        k = self.k
        largeur_max = int(250 * k)
        marge = int(10 * k)
        pt, ptitre = self.police_texte, self.police_titre
        h_ligne = int(pt.size * 1.3)
        lignes_user = _decouper("> " + b["user"], ptitre, largeur_max)[:2] if b.get("user") else []
        lignes = _decouper(b["texte"], pt, largeur_max) if b["texte"] else []
        largeur = max([int(pt.getlength(l)) for l in lignes] + [int(ptitre.getlength(l)) for l in lignes_user] + [int(60 * k)])
        h_user = int(ptitre.size * 1.35) * len(lignes_user)
        h_titre = int(ptitre.size * 1.5) if lignes else 0
        w = largeur + 2 * marge
        h = h_user + h_titre + h_ligne * len(lignes) + 2 * marge
        queue_h = int(9 * k)
        img = Image.new("RGBA", (w, h + queue_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        c = int(7 * k)  # coins coupés façon HUD
        poly = [(c, 0), (w - c, 0), (w - 1, c), (w - 1, h - c), (w - c, h - 1), (c, h - 1), (0, h - c), (0, c)]
        d.polygon(poly, fill=(8, 6, 20, 218))
        d.line(poly + [poly[0]], fill=VERT + (255,), width=2)
        d.rectangle([0, c, 3, h - c], fill=ROSE + (255,))
        milieu = w // 2
        d.polygon([(milieu - queue_h, h - 1), (milieu + queue_h, h - 1), (milieu, h + queue_h - 1)], fill=(8, 6, 20, 218))
        d.line([(milieu - queue_h, h - 1), (milieu, h + queue_h - 1), (milieu + queue_h, h - 1)], fill=VERT + (255,), width=2)
        y = marge
        for l in lignes_user:
            d.text((marge, y), l, font=ptitre, fill=(120, 200, 160, 255))
            y += int(ptitre.size * 1.35)
        if lignes:
            d.text((marge, y), "CAPRI //", font=ptitre, fill=ROSE + (255,))
            y += h_titre
            restant = revele
            for l in lignes:
                if restant <= 0:
                    break
                d.text((marge, y), l[:restant], font=pt, fill=BLANC + (255,))
                restant -= len(l) + 1
                y += h_ligne
        if opacite < 1.0:
            img.putalpha(img.getchannel("A").point(LUTS_FONDU[int(opacite * 8)]))
        return img

    def _bulle_image(self, now):
        b = self._bulle
        if not b or not self.cfg.get("bulle", True):
            return None
        if now >= self._bulle_fin(b):
            self._bulle = None
            return None
        total = len(b["texte"])
        if b["duree"] > 0 and total:
            revele = min(total, int(total * (now - b["t0"]) / b["duree"]) + 1)
        else:
            revele = total
        restant = self._bulle_fin(b) - now
        opacite = min(1.0, restant / 0.4)
        cle = (b["texte"], revele, b.get("user"), int(opacite * 8))
        if not self._img_bulle or self._img_bulle[0] != cle:
            self._img_bulle = (cle, self._creer_image_bulle(b, revele, opacite))
        return self._img_bulle[1]

    # ------------------------------------------------------------ sprites ----

    def _cle_sprite(self, now):
        mode = self.mode_courant
        if mode == "ecoute":
            return ("listening_blink" if (now % 4.6) < 0.14 else "listening"), 0
        if mode == "reflechit":
            return "searching", 0
        if mode == "surpris":
            return "surprised", 0
        if mode == "content":
            return "happy", 0
        if mode == "ennui":
            return "bored", 0
        if mode == "dort":
            return "layingdown", 0
        if mode == "parle":
            etat = self._etat_voix()
            # les sprites de réaction n'ont pas de bouche animée : on prend l'équivalent qui parle
            cle = {"happy": "excited", "surprised": "excited", "bored": "layingdown"}.get(self.emotion, self.emotion)
            return cle, (etat[0] if etat else 0)
        return self._pose[0], 0

    def _maj_pose(self, now):
        """Au repos, Capri change d'expression de temps en temps, comme si elle vivait sa vie."""
        if self.mode_courant != "repos" or not self._visible or self._fx:
            return
        cle, fin = self._pose
        if not self.cfg.get("expressions_auto", True):
            self._pose = ("interested", now + 5)
            return
        if now < fin:
            return
        inactive = now - self._derniere_activite > self.DELAI_SOMMEIL   # seule depuis longtemps : plus nonchalante
        candidats = [(c, p * (3 if inactive and c in ("layingdown", "bored") else 1), lo, hi)
                     for c, p, lo, hi in self.POSES if c != cle]
        choix = random.choices(candidats, weights=[c[1] for c in candidats])[0]
        self._pose = (choix[0], now + random.uniform(choix[2], choix[3]))

    # ------------------------------------------------------------ rendu -----

    def _rendre(self, now, dt):
        cle, bouche = self._cle_sprite(now)
        sp = self.biblio.sprite(cle, ("closed", "mid", "full")[bouche])
        if sp is None:
            return
        if cle != self._cle_prec:
            if self._cle_prec is not None:
                self._declencher_glitch(now, 0.2)
            self._cle_prec = cle

        p, ancre, trajet = self._etat_fx(now)
        if not self._visible:
            return
        t = now
        k = self.k
        cx = ancre[0] + math.sin(t * 1.55) * 2.2 * k
        by = ancre[1] + math.sin(t * 1.1) * 5.0 * k
        if self._drag and self._drag["bouge"]:
            cx, by = ancre
        l, tp, r, b = self.zone
        sx = int(min(max(cx - sp.w / 2, l), max(l, r - sp.w)))
        sy = int(min(max(by - sp.h, tp), max(tp, b - sp.h)))
        rect_sprite = (sx, sy, sx + sp.w, sy + sp.h)
        pad = self.pad
        rects = [(sx - pad, sy - pad, sx + sp.w + pad, sy + sp.h + pad)]

        fx = self._fx
        en_transit = bool(fx and fx["type"] == "teleport" and trajet is not None)
        if fx:
            # les éclats dépassent largement de l'image : on agrandit la zone de dessin
            marge_fx = int(0.5 * sp.w)
            rects.append((sx - marge_fx, sy - marge_fx // 2, sx + sp.w + marge_fx, sy + sp.h + marge_fx // 2))
        if en_transit:
            o, d = fx["origine"], fx["dest"]
            marge_fx = int(0.5 * sp.w)
            rects.append((int(min(o[0], d[0]) - sp.w / 2 - marge_fx), int(min(o[1], d[1]) - sp.h - marge_fx),
                          int(max(o[0], d[0]) + sp.w / 2 + marge_fx), int(max(o[1], d[1]) + marge_fx)))

        bulle = self._bulle_image(now) if p > 0.6 else None
        pos_bulle = None
        if bulle is not None:
            bw, bh = bulle.size
            bx = int(min(max(sx + sp.w / 2 - bw / 2, l), max(l, r - bw)))
            if sy - bh - 6 >= tp:
                by_b = sy - bh - 6 - pad // 2
            else:
                by_b = sy + sp.h + 6 + pad // 2
            pos_bulle = (bx, by_b)
            rects.append((bx, by_b, bx + bw, by_b + bh))

        self._maj_particules(now, rect_sprite, dt)
        sw_, sh_ = user32.GetSystemMetrics(SM_CXSCREEN), user32.GetSystemMetrics(SM_CYSCREEN)
        x0, y0, x1, y1 = _union(rects)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(sw_, x1), min(sh_, y1)
        if x1 <= x0 or y1 <= y0:
            return
        ox, oy = x0, y0
        canvas = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
        xc, yc = sx - ox, sy - oy

        glitch = self._maj_glitch(now, sp)
        img = sp.img
        if glitch and glitch["bandes"]:
            img = self._appliquer_bandes(img, glitch["bandes"])

        if p > 0.02:
            # lueur néon : verte à l'écoute, rose sinon, pulsée par la voix
            pulse = 0.5 + 0.5 * math.sin(now * 2.4)
            niveau = 0.0
            if self.mode_courant == "parle":
                etat = self._etat_voix()
                niveau = etat[1] if etat else 0.0
            intensite = (0.28 + 0.18 * pulse + 0.35 * niveau) * p
            couleur = VERT if self.mode_courant == "ecoute" else ROSE
            masque = sp.halo(pad).point(lambda v, f=intensite: int(v * f))
            lueur = Image.new("RGBA", masque.size, couleur + (0,))
            lueur.putalpha(masque)
            _coller(canvas, lueur, xc - pad, yc - pad)

        if glitch and p > 0.5:
            dd = glitch["d"]
            _coller(canvas, sp.silhouette(ROSE, 0.6), xc - dd, yc)
            _coller(canvas, sp.silhouette(VERT, 0.6), xc + dd, yc + (1 if dd > 2 else 0))

        if p >= 0.999:
            _coller(canvas, img, xc, yc)
            self._dessiner_balayage(canvas, sp, img, xc, yc, now)
        elif p > 0.0 and fx:
            self._dessiner_revelation(canvas, sp, img, xc, yc, p, fx)

        if en_transit:
            self._dessiner_transit(canvas, trajet, fx, ox, oy, sp)

        if self._particules:
            dp = ImageDraw.Draw(canvas)
            for q in self._particules:
                age = (now - q["t0"]) / q["vie"]
                a = int(255 * (1 - age) * 0.85)
                s = q["taille"]
                px, py = int(q["x"] - ox), int(q["y"] - oy)
                if 0 <= px < canvas.width - s and 0 <= py < canvas.height - s:
                    dp.rectangle([px, py, px + s - 1, py + s - 1], fill=q["couleur"] + (a,))

        if bulle is not None:
            _coller(canvas, bulle, pos_bulle[0] - ox, pos_bulle[1] - oy)

        opacite = self.cfg.get("opacite", 1.0)
        self.fen.mettre_a_jour(canvas, ox, oy, 255 * max(0.3, min(1.0, opacite)))

    def _dessiner_balayage(self, canvas, sp, img, xc, yc, now):
        """Fine ligne holographique qui parcourt Capri de temps en temps."""
        if now >= self._prochain_scan and now > self._scan_fin:
            self._scan_fin = now + 0.9
            self._prochain_scan = now + random.uniform(6, 11)
        if now > self._scan_fin:
            return
        s = 1 - (self._scan_fin - now) / 0.9
        bh = max(3, int(4 * self.k / 1.5))
        y = int(s * (sp.h - bh))
        bande = img.getchannel("A").crop((0, y, sp.w, y + bh)).point(lambda v: int(v * 0.3))
        couche = Image.new("RGBA", (sp.w, bh), (190, 255, 225, 0))
        couche.putalpha(bande)
        _coller(canvas, couche, xc, yc + y)

    # --------------------------------------------------------- boucle -------

    def _boucle(self):
        self._init()
        self._pret.set()
        self._montrer(time.monotonic())
        precedent = time.monotonic()
        while self._actif:
            debut = time.monotonic()
            dt = min(0.2, debut - precedent)
            precedent = debut
            self.fen.pomper_messages()
            if not self._traiter_commandes(debut):
                break
            self._maj(debut)
            if self._visible:
                try:
                    self._rendre(debut, dt)
                except Exception as e:
                    import traceback
                    cfg.journal(f"Erreur de rendu avatar: {e}\n{traceback.format_exc()}")
                    time.sleep(0.5)
            elif self._fx_solo:
                try:
                    self._rendre_solo(debut)
                except Exception as e:
                    import traceback
                    cfg.journal(f"Erreur de rendu des éclairs: {e}\n{traceback.format_exc()}")
                    self._fx_solo = None
                    self.fen.afficher(False)
            visuel_actif = bool(self._fx or self._fx_solo or self._glitch or self._bulle or self._drag
                                or self.mode_courant not in ("repos", "dort"))
            cible = (1 / 12 if self.eco else 1 / 30 if visuel_actif else 1 / 20) if (self._visible or self._fx_solo) else 0.08
            reste = cible - (time.monotonic() - debut)
            if reste > 0:
                time.sleep(reste)
        self.fen.detruire()

    def _maj(self, now):
        if self._mode_fin and now >= self._mode_fin:
            self._mode_fin = None
            self.mode_courant = "repos"
        self._maj_pose(now)
        if now - self._t_zone > 5:
            self._t_zone = now
            self.zone = zone_de_travail()
        if self._visible and now - self._t_premier_plan > 2:
            self._t_premier_plan = now
            self.fen.au_premier_plan()
