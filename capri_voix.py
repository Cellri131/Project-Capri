"""
Voix de Capri.

Moteurs de synthèse (dans l'ordre de préférence selon la configuration) :
  - capri   : voix de Capri (Pocket-TTS + capri_french.safetensors), hors ligne, préférée
  - local   : voix neuronale française (sherpa-onnx + modèle Piper), hors ligne
  - edge    : voix neuronale Microsoft Edge (en ligne, via edge-tts)
  - windows : voix SAPI installée sur le PC (Hortense), en dernier recours

Le son est lu avec miniaudio ; l'enveloppe du signal pilote la bouche de l'avatar.
"""

import array
import glob
import math
import os
import queue
import random
import re
import tempfile
import threading
import time
import wave
from xml.sax.saxutils import escape

import capri_config as cfg

RYTHME_SORTIE = 24000

# émotion -> (tempo, hauteur) relatifs : les nuances restent discrètes
PROSODIE = {
    "interested": (1.0, 1.0), "excited": (1.07, 1.03), "annoyed": (0.98, 0.97),
    "suspicious": (0.93, 0.98), "pointing": (1.0, 1.0), "pointingatherself": (1.0, 1.01),
    "layingdown": (0.92, 0.97), "happy": (1.05, 1.02), "surprised": (1.05, 1.03),
    "bored": (0.93, 0.97), "interested_fullbody": (1.0, 1.0),
}


def nettoyer_texte(texte):
    """Retire ce qu'un moteur vocal lirait de travers (markdown, liens, émojis)."""
    t = re.sub(r"https?://\S+", " le lien ", texte)
    t = re.sub(r"[*_`#>~|]+", " ", t)
    t = re.sub(r"[\U00010000-\U0010FFFF\u2600-\u27BF\uFE0F]", "", t)
    t = t.replace("…", "...").replace("\n", ". ").replace("\r", " ")
    t = re.sub(r"\bIA\b", "I.A.", t)
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"(?<!\.)\.\s*\.(?!\.)", ".", t)


def decouper_phrases(texte, taille_max=200):
    """Découpe en morceaux courts : le premier est synthétisé vite, les suivants pendant la lecture."""
    phrases = re.split(r"(?<=[.!?])\s+", texte)
    morceaux, courant = [], ""
    for p in phrases:
        if courant and len(courant) + len(p) + 1 > taille_max:
            morceaux.append(courant)
            courant = p
        else:
            courant = f"{courant} {p}".strip()
    if courant:
        morceaux.append(courant)
    return morceaux


def enveloppe_levres(samples, rythme):
    """Niveaux de bouche (0 fermée, 1 mi-ouverte, 2 ouverte) et amplitude par fenêtre de 20 ms."""
    fen = max(1, int(rythme * 0.02))
    rms = []
    for i in range(0, len(samples), fen):
        seg = samples[i:i + fen]
        rms.append(math.sqrt(sum(x * x for x in seg) / max(1, len(seg))))
    if not rms:
        return []
    ref = sorted(rms)[int(len(rms) * 0.9)] or 1.0
    sortie = []
    for r in rms:
        n = r / ref
        sortie.append((0 if n < 0.14 else 1 if n < 0.5 else 2, min(1.0, n)))
    return sortie


# ---------------------------------------------------------------- moteurs ---

class MoteurLocal:
    nom = "local"

    def __init__(self):
        self.tts = None
        self.rythme = 22050
        self._verrou = threading.Lock()

    @staticmethod
    def dossier_modele():
        for onnx in glob.glob(os.path.join(cfg.DOSSIER_VOIX, "**", "*.onnx"), recursive=True):
            d = os.path.dirname(onnx)
            if os.path.exists(os.path.join(d, "tokens.txt")) and os.path.isdir(os.path.join(d, "espeak-ng-data")):
                return d, onnx
        return None

    def disponible(self):
        try:
            import sherpa_onnx  # noqa: F401
        except ImportError:
            return False
        return self.dossier_modele() is not None

    def _charger(self):
        import sherpa_onnx
        dossier, onnx = self.dossier_modele()
        conf = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=onnx, tokens=os.path.join(dossier, "tokens.txt"),
                    data_dir=os.path.join(dossier, "espeak-ng-data"),
                    noise_scale=0.72, noise_scale_w=0.85, length_scale=1.0),
                num_threads=2, provider="cpu"),
            max_num_sentences=1)
        self.tts = sherpa_onnx.OfflineTts(conf)
        self.rythme = self.tts.sample_rate

    def synthese(self, texte, tempo, hauteur):
        with self._verrou:
            if self.tts is None:
                self._charger()
            audio = self.tts.generate(texte, sid=0, speed=max(0.5, min(2.0, tempo / hauteur)))
        if not audio.samples:
            raise RuntimeError("synthèse locale vide")
        pcm = array.array("h", (int(max(-1.0, min(1.0, s)) * 32000) for s in audio.samples))
        return pcm, int(self.rythme * hauteur)


class MoteurCapri:
    """Voix de Capri : Pocket-TTS (Kyutai) conditionné par le fichier capri_french.safetensors, hors ligne."""
    nom = "capri"

    def __init__(self, fichier, langue="french"):
        self.fichier = fichier if os.path.isabs(fichier) else os.path.join(cfg.DOSSIER, fichier)
        self.langue = langue
        self.modele = None
        self.etat = None
        self._verrou = threading.Lock()

    def disponible(self):
        if not os.path.exists(self.fichier):
            return False
        try:
            import pocket_tts  # noqa: F401
        except ImportError:
            return False
        return True

    def _charger(self):
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        from pocket_tts import TTSModel
        # modèle déjà en cache : on évite toute requête réseau (lente ou bloquée) ; sinon premier téléchargement
        for hors_ligne in ("1", "0"):
            os.environ["HF_HUB_OFFLINE"] = hors_ligne
            try:
                self.modele = TTSModel.load_model(language=self.langue)
                break
            except Exception:
                if hors_ligne == "0":
                    raise
        os.environ.pop("HF_HUB_OFFLINE", None)
        self.etat = self.modele.get_state_for_audio_prompt(self.fichier)

    def synthese(self, texte, tempo, hauteur):
        with self._verrou:
            if self.modele is None:
                self._charger()
            audio = self.modele.generate_audio(self.etat, texte, max_tokens=300).numpy()
        if audio.size == 0:
            raise RuntimeError("synthèse de la voix de Capri vide")
        crete = float(abs(audio).max()) or 1.0
        audio = audio * min(6.0, 0.85 / crete)
        pcm = array.array("h", (int(max(-1.0, min(1.0, float(s))) * 32000) for s in audio))
        return pcm, int(self.modele.sample_rate)


class MoteurWindows:
    nom = "windows"

    def __init__(self, preference="Hortense"):
        self.preference = preference.lower()

    def disponible(self):
        try:
            import win32com.client  # noqa: F401
            return True
        except ImportError:
            return False

    def synthese(self, texte, tempo, hauteur):
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        chemin = None
        try:
            voix = win32com.client.Dispatch("SAPI.SpVoice")
            for v in voix.GetVoices():
                desc = v.GetDescription().lower()
                if self.preference in desc or "french" in desc or "français" in desc:
                    voix.Voice = v
                    break
            flux = win32com.client.Dispatch("SAPI.SpFileStream")
            fmt = win32com.client.Dispatch("SAPI.SpAudioFormat")
            fmt.Type = 22  # 22 kHz, 16 bits, mono
            flux.Format = fmt
            fd, chemin = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            flux.Open(chemin, 3)
            voix.AudioOutputStream = flux
            voix.Rate = max(-10, min(10, round((tempo - 1) * 20)))
            hauteur_sapi = max(-10, min(10, round((hauteur - 1) * 60)))
            voix.Speak(f'<pitch absmiddle="{hauteur_sapi}">{escape(texte)}</pitch>', 8)
            flux.Close()
            with wave.open(chemin, "rb") as w:
                pcm = array.array("h")
                pcm.frombytes(w.readframes(w.getnframes()))
                return pcm, w.getframerate()
        finally:
            if chemin and os.path.exists(chemin):
                try:
                    os.remove(chemin)
                except OSError:
                    pass
            pythoncom.CoUninitialize()


class MoteurEdge:
    nom = "edge"

    def __init__(self, voix):
        self.voix = voix

    def disponible(self):
        try:
            import edge_tts  # noqa: F401
            import miniaudio  # noqa: F401
            return True
        except ImportError:
            return False

    def synthese(self, texte, tempo, hauteur):
        import asyncio
        import edge_tts
        import miniaudio

        async def recuperer():
            comm = edge_tts.Communicate(texte, self.voix, rate=f"{round((tempo - 1) * 100):+d}%",
                                        pitch=f"{round((hauteur - 1) * 100):+d}Hz")
            donnees = bytearray()
            async for morceau in comm.stream():
                if morceau["type"] == "audio":
                    donnees += morceau["data"]
            return bytes(donnees)

        mp3 = asyncio.run(asyncio.wait_for(recuperer(), 12))
        if not mp3:
            raise RuntimeError("edge-tts n'a renvoyé aucun son")
        dec = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=24000)
        return array.array("h", dec.samples), 24000


# ------------------------------------------------------------------ lecture --

class _Flux:
    """File de morceaux audio lue en continu par le périphérique de sortie."""

    def __init__(self, rythme):
        self.rythme = rythme
        self.file = queue.Queue()
        self.segments = []   # (frame_debut, enveloppe)
        self.total = 0
        self.lus = 0
        self.termine = threading.Event()
        self.arret = threading.Event()

    def ajouter(self, pcm, enveloppe):
        self.segments.append((self.total, enveloppe))
        self.total += len(pcm)
        self.file.put(pcm)

    def fermer(self):
        self.file.put(None)

    def generateur(self):
        requis = yield b""
        courant, pos = None, 0
        while not self.arret.is_set():
            if courant is None:
                try:
                    courant = self.file.get_nowait()
                except queue.Empty:
                    requis = yield array.array("h", [0]) * 1  # attente du prochain morceau : silence
                    continue
                if courant is None:
                    break
                pos = 0
            morceau = courant[pos:pos + requis]
            pos += len(morceau)
            if pos >= len(courant):
                courant = None
            self.lus += len(morceau)
            requis = yield morceau
        self.termine.set()

    def niveau(self, latence=0.09):
        frame = max(0, self.lus - int(latence * self.rythme))
        for debut, env in reversed(self.segments):
            if frame >= debut:
                i = int((frame - debut) / (self.rythme * 0.02))
                return env[i] if i < len(env) else (0, 0.0)
        return (0, 0.0)


class Voix:
    def __init__(self, config):
        self.config = config
        self.cfg = config["voix"]
        self._verrou_parole = threading.Lock()
        self._arret = threading.Event()
        self._niveau = None
        self._flux = None
        self._simulation = None
        self._moteurs = {}
        self._indispo = {}   # moteur -> instant jusqu'auquel on l'évite
        self._appareil = None
        self._verrou_appareil = threading.Lock()
        self.en_cours = False
        self.derniere_fin = 0.0
        self.compteur = 0

    # ------------------------------------------------------------ moteurs ---

    def _moteur(self, nom):
        if nom not in self._moteurs:
            if nom == "capri":
                m = MoteurCapri(self.cfg.get("fichier_voix", "capri_french.safetensors"))
            elif nom == "local":
                m = MoteurLocal()
            elif nom == "edge":
                m = MoteurEdge(self.cfg.get("edge_voix", "fr-FR-VivienneMultilingualNeural"))
            else:
                m = MoteurWindows(self.cfg.get("windows_voix", "Hortense"))
            self._moteurs[nom] = m if m.disponible() else None
        return self._moteurs[nom]

    def _ordre(self):
        choix = self.cfg.get("moteur", "auto")
        if choix == "edge":
            return ["edge", "capri", "local", "windows"]
        if choix == "windows":
            return ["windows"]
        if choix == "local":
            return ["local", "windows"]
        return ["capri", "local", "windows"]

    def moteurs_disponibles(self):
        return [n for n in ("capri", "local", "edge", "windows") if self._moteur(n)]

    def _synthetiser(self, texte, emotion):
        tempo_e, hauteur_e = PROSODIE.get(emotion, (1.0, 1.0))
        tempo = self.cfg.get("vitesse", 1.05) * tempo_e
        hauteur = self.cfg.get("hauteur", 1.04) * hauteur_e
        derniere = None
        for nom in self._ordre():
            if self._indispo.get(nom, 0) > time.monotonic():
                continue
            moteur = self._moteur(nom)
            if not moteur:
                continue
            try:
                return moteur.synthese(texte, tempo, hauteur)
            except Exception as e:
                derniere = e
                cfg.journal(f"Moteur vocal '{nom}' en échec: {e}")
                self._indispo[nom] = time.monotonic() + 300
        raise RuntimeError(f"aucun moteur vocal utilisable ({derniere})")

    # ------------------------------------------------------------ état -----

    def etat_bouche(self):
        """(niveau 0-2, amplitude 0-1) pendant la parole, sinon None."""
        if self._simulation is not None:
            return self._simulation()
        flux = self._flux
        if flux is not None and self.en_cours:
            return flux.niveau()
        return None

    @property
    def muet(self):
        return bool(self.cfg.get("muet", False))

    def arreter(self):
        self._arret.set()
        if self._flux:
            self._flux.arret.set()

    # ----------------------------------------------------------- parole -----

    def parler(self, texte, emotion="interested", au_debut=None):
        """Dit le texte (bloquant). `au_debut(durée_estimée)` est appelé quand le son démarre."""
        texte = nettoyer_texte(texte)
        if not texte:
            return
        with self._verrou_parole:
            self._arret.clear()
            self.en_cours = True
            self.compteur += 1
            try:
                if self.muet:
                    self._parler_muet(texte, au_debut)
                else:
                    self._parler_audio(texte, emotion, au_debut)
            except Exception as e:
                cfg.journal(f"Erreur de synthèse vocale: {e}")
                self._parler_muet(texte, au_debut)
            finally:
                self._flux = None
                self._simulation = None
                self.en_cours = False
                self.derniere_fin = time.monotonic()

    def _parler_muet(self, texte, au_debut):
        """Sans son : la bouche bouge quand même pour accompagner le sous-titre."""
        duree = max(1.2, len(texte) * 0.058)
        debut = time.monotonic()
        etat = {"t": 0.0, "niv": 0}

        def simulation():
            now = time.monotonic()
            if now - etat["t"] > 0.09:
                etat["t"] = now
                etat["niv"] = random.choice((0, 1, 1, 2, 2))
            return etat["niv"], 0.3 + 0.2 * etat["niv"]

        self._simulation = simulation
        if au_debut:
            au_debut(duree)
        while time.monotonic() - debut < duree and not self._arret.is_set():
            time.sleep(0.03)

    def _parler_audio(self, texte, emotion, au_debut):
        miniaudio = self._miniaudio()
        morceaux = decouper_phrases(texte)
        premier, rythme = self._synthetiser(morceaux[0], emotion)
        if miniaudio:
            premier, rythme = self._vers_sortie(miniaudio, premier, rythme), RYTHME_SORTIE
        duree_premier = len(premier) / rythme
        total_estime = duree_premier * len(texte) / max(1, len(morceaux[0]))
        flux = _Flux(rythme)
        self._ajouter(flux, premier)

        def producteur():
            try:
                for m in morceaux[1:]:
                    if self._arret.is_set():
                        break
                    pcm, r = self._synthetiser(m, emotion)
                    if miniaudio:
                        pcm = self._vers_sortie(miniaudio, pcm, r)
                    elif r != rythme:
                        break
                    self._ajouter(flux, pcm)
            except Exception as e:
                cfg.journal(f"Synthèse des phrases suivantes interrompue: {e}")
            finally:
                flux.fermer()

        if len(morceaux) > 1:
            threading.Thread(target=producteur, name="capri-synthese", daemon=True).start()
        else:
            flux.fermer()
        self._flux = flux
        if miniaudio:
            self._lire(miniaudio, flux, au_debut, total_estime)
        else:
            self._lire_winsound(flux, premier, rythme, au_debut, duree_premier)

    @staticmethod
    def _miniaudio():
        try:
            import miniaudio
            return miniaudio
        except ImportError:
            return None

    @staticmethod
    def _vers_sortie(miniaudio, pcm, rythme):
        """Rééchantillonne vers la fréquence du périphérique (garde la hauteur de voix voulue)."""
        if rythme == RYTHME_SORTIE:
            return pcm
        fmt = miniaudio.SampleFormat.SIGNED16
        brut = miniaudio.convert_frames(fmt, 1, rythme, pcm.tobytes(), fmt, 1, RYTHME_SORTIE)
        sortie = array.array("h")
        sortie.frombytes(brut)
        return sortie

    def _ajouter(self, flux, pcm):
        volume = max(0.0, min(1.0, self.cfg.get("volume", 0.9)))
        silence = array.array("h", [0] * int(flux.rythme * 0.06))
        pcm = silence + pcm if not flux.segments else pcm
        enveloppe = enveloppe_levres(pcm, flux.rythme)  # calculée avant le volume : la bouche reste expressive
        if volume < 0.99:
            pcm = array.array("h", (int(s * volume) for s in pcm))
        flux.ajouter(pcm, enveloppe)

    def _obtenir_appareil(self, miniaudio):
        """Périphérique de sortie unique, créé une fois (son ouverture prend ~1 s)."""
        with self._verrou_appareil:
            if self._appareil is None:
                self._appareil = miniaudio.PlaybackDevice(
                    output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1,
                    sample_rate=RYTHME_SORTIE, buffersize_msec=50)
            return self._appareil

    def prechauffer(self):
        """Charge le moteur vocal et ouvre la sortie audio en tâche de fond."""
        def travail():
            try:
                miniaudio = self._miniaudio()
                if miniaudio:
                    self._obtenir_appareil(miniaudio)
                premier = next((n for n in self._ordre() if self._moteur(n) and n in ("capri", "local")), None)
                if premier:
                    self._moteur(premier).synthese("Bonjour.", 1.0, 1.0)
            except Exception as e:
                cfg.journal(f"Préchauffage de la voix impossible: {e}")
        threading.Thread(target=travail, name="capri-prechauffe", daemon=True).start()

    def _lire(self, miniaudio, flux, au_debut, total_estime):
        appareil = self._obtenir_appareil(miniaudio)
        try:
            gen = flux.generateur()
            next(gen)
            appareil.start(gen)
            if au_debut:
                au_debut(total_estime)
            while not flux.termine.is_set() and not self._arret.is_set():
                time.sleep(0.02)
            if not self._arret.is_set():
                time.sleep(0.25)  # laisse le tampon se vider
        finally:
            flux.arret.set()
            try:
                appareil.stop()
            except Exception:
                self._appareil = None

    def _lire_winsound(self, flux, pcm, rythme, au_debut, duree):
        """Repli sans miniaudio : lecture WAV simple du premier morceau."""
        import winsound
        fd, chemin = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            with wave.open(chemin, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rythme)
                w.writeframes(pcm.tobytes())
            debut = time.monotonic()
            env = flux.segments[0][1] if flux.segments else []

            def simulation():
                i = int((time.monotonic() - debut) / 0.02)
                return env[i] if i < len(env) else (0, 0.0)

            self._simulation = simulation
            if au_debut:
                au_debut(duree)
            winsound.PlaySound(chemin, winsound.SND_FILENAME | winsound.SND_ASYNC)
            while time.monotonic() - debut < duree + 0.2 and not self._arret.is_set():
                time.sleep(0.03)
            winsound.PlaySound(None, winsound.SND_PURGE)
        finally:
            try:
                os.remove(chemin)
            except OSError:
                pass
