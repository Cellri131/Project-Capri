"""
Capri - assistante vocale pour Windows.

Une entité numérique inspirée de Capri (Cyberpunk: Edgerunners) : un avatar pixel-art flottant
reste à l'écran, écoute, répond à voix haute et pilote le PC. Elle se gère depuis l'icône
de la zone de notification (icônes cachées).
"""

# Fix pour Python 3.13+ - Le module aifc a été supprimé
import sys
if sys.version_info >= (3, 13):
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    # Créer un module aifc factice pour PyAudio
    sys.modules['aifc'] = type(sys)('aifc')

import argparse
import ctypes
import glob
import os
import queue
import random
import subprocess
import threading
import time
import traceback
from ctypes import wintypes as wt

import speech_recognition as sr
from PIL import Image
import pystray
from pystray import MenuItem as item

import capri_config as cfg
from capri_avatar import AvatarCapri, rendre_dpi_precis
from capri_cerveau import Cerveau, est_demande_arret, extraire_mot_activation, normaliser, similarite_capri
from capri_phrases import Phrases
from capri_voix import Voix
from commandes import CommandeHandler

try:
    import audioop   # absent de Python 3.13+ sauf avec audioop-lts (déjà demandé par SpeechRecognition)
except ImportError:
    audioop = None

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.restype = ctypes.c_void_p
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
kernel32.CreateEventW.restype = ctypes.c_void_p
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
kernel32.SetEvent.argtypes = [ctypes.c_void_p]
kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wt.DWORD]

ERROR_ALREADY_EXISTS = 183


class Reconnaisseur(sr.Recognizer):
    """Recognizer dont le seuil de détection de la voix reste entre un plancher et un plafond.

    Dans une pièce silencieuse, le seuil dynamique de SpeechRecognition tombe presque à zéro : le moindre
    souffle déclenche alors un « enregistrement » qui ne se termine jamais, et ta demande se perd dedans.
    """
    plancher = 120
    plafond = 800

    @property
    def energy_threshold(self):
        return self._seuil

    @energy_threshold.setter
    def energy_threshold(self, valeur):
        self._seuil = min(max(valeur, self.plancher), self.plafond)


class AssistantVocal:
    def __init__(self, nom="Capri", mode_economie=False, muet=False, sans_micro=False, signal_relance=None):
        self.nom = nom
        self.config = cfg.charger()
        if muet:
            self.config["voix"]["muet"] = True   # le temps de la session seulement
        self.sans_micro = sans_micro
        self.recognizer = Reconnaisseur()
        self.recognizer.plancher = self.config["ecoute"].get("seuil_min", 120)
        self.recognizer.plafond = self.config["ecoute"].get("seuil_max", 800)
        self.voix = Voix(self.config)
        self.cerveau = Cerveau(self.config)
        self.phrases = Phrases()
        self.handler = CommandeHandler()
        self.handler.assistant_parler = self.parler  # Donner accès à la fonction parler
        self.avatar = AvatarCapri(self.config, etat_voix=self.voix.etat_bouche, rappel=self._evenement_avatar)
        self.signal_relance = signal_relance
        self.actif = False
        self.en_pause = False
        self.en_train_de_parler = False
        self.fin_attente = 0.0          # après un « Capri » seul : jusqu'à quand la demande peut suivre
        self._occupee = False           # une demande est en cours de traitement
        self._autonome_actif = False    # une initiative spontanée est en cours
        self._cachee_auto = False       # vrai si elle a disparu d'elle-même (et peut donc revenir seule)
        self._prochaine_initiative = 0.0
        self._prochain_eclair = 0.0
        self.tray_icon = None
        self.thread_ecoute = None
        self.file_audio = queue.Queue(maxsize=4)
        self.micro_pret = threading.Event()     # le micro est ouvert et calibré
        self.dernier_son = 0.0                  # dernière fois qu'une voix a été captée

        # Détecter automatiquement si le PC est sur batterie
        self.mode_economie = self.detecter_mode_batterie() if not mode_economie else mode_economie
        self.appliquer_mode(self.mode_economie)

    # ------------------------------------------------------------ système ----

    def trouver_et_lancer_application(self, nom_app):
        """
        Recherche un raccourci (.lnk) dans le menu démarré et lance l'application si trouvée.
        nom_app : nom de l'application (ex: 'Word', 'Chrome', 'Spotify')
        """
        try:
            from win32com.client import Dispatch
        except ImportError:
            cfg.journal("Module win32com non disponible")
            return False

        # Dossiers du menu démarré utilisateur et global
        start_menu_dirs = [
            os.path.join(os.environ['APPDATA'], r"Microsoft\Windows\Start Menu\Programs"),
            os.path.join(os.environ['PROGRAMDATA'], r"Microsoft\Windows\Start Menu\Programs")
        ]
        # Recherche tous les .lnk
        raccourcis = []
        for d in start_menu_dirs:
            if os.path.exists(d):
                raccourcis += glob.glob(os.path.join(d, '**', '*.lnk'), recursive=True)

        # Recherche par nom (insensible à la casse)
        nom_app = nom_app.lower()
        for lnk in raccourcis:
            nom_fichier = os.path.splitext(os.path.basename(lnk))[0].lower()
            if nom_app in nom_fichier:
                try:
                    shell = Dispatch('WScript.Shell')
                    shortcut = shell.CreateShortCut(lnk)
                    target = shortcut.Targetpath
                    cfg.journal(f"Lancement de {nom_fichier}...")
                    subprocess.Popen(target)
                    return True
                except Exception as e:
                    cfg.journal(f"Erreur lors du lancement : {e}")
                    return False

        cfg.journal(f"Application '{nom_app}' non trouvée dans le menu démarré")
        return False

    def detecter_mode_batterie(self):
        """Détecte si le PC est sur batterie (mode économie d'énergie)"""
        try:
            import psutil
            battery = psutil.sensors_battery()
            if battery is None:
                # PC de bureau sans batterie
                return False
            # Si branché sur secteur, mode normal, sinon mode économie
            return not battery.power_plugged
        except Exception:
            return False

    def appliquer_mode(self, mode_economie):
        """Applique les paramètres selon le mode"""
        self.mode_economie = mode_economie
        self.avatar.eco = mode_economie
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.energy_threshold = 500 if mode_economie else 300
        self.duree_phrase_max = 8 if mode_economie else 12

    # --------------------------------------------------------------- voix ----

    def parler(self, texte, emotion="interested"):
        """Fait parler Capri : voix, bouche animée et bulle de texte."""
        cfg.journal(f"Capri : {texte}")
        self.en_train_de_parler = True
        self.avatar.definir_mode("parle", emotion=emotion)
        try:
            self.voix.parler(texte, emotion, au_debut=lambda duree: self.avatar.afficher_bulle(texte, duree))
        finally:
            self.avatar.definir_mode("repos")
            self.en_train_de_parler = False

    def _parler_en_tache_de_fond(self, texte, emotion="interested"):
        if not self.voix.en_cours:
            threading.Thread(target=self.parler, args=(texte, emotion), daemon=True).start()

    # ------------------------------------------------------------- écoute ----

    def boucle_ecoute(self):
        """Capture continue du micro ; la reconnaissance se fait dans un second thread."""
        threading.Thread(target=self._boucle_traitement, name="capri-traitement", daemon=True).start()
        while self.actif:
            if self.en_pause:
                time.sleep(0.5)
                continue
            try:
                with sr.Microphone() as source:
                    cfg.journal("Micro ouvert, calibrage du bruit ambiant...")
                    self.recognizer.adjust_for_ambient_noise(source, duration=1)
                    cfg.journal(f"Seuil d'énergie : {int(self.recognizer.energy_threshold)} "
                                f"(limites {self.recognizer.plancher}-{self.recognizer.plafond})")
                    self.micro_pret.set()
                    while self.actif and not self.en_pause:
                        if self.voix.en_cours or time.monotonic() < self.voix.derniere_fin + 0.4:
                            # elle parle : on lit et on jette ce que capte le micro (sinon il déborde, et on
                            # entendrait ensuite sa propre voix avec du retard, mêlée à ta demande)
                            source.stream.read(source.CHUNK)
                            continue
                        try:
                            audio = self.recognizer.listen(source, timeout=2, phrase_time_limit=self.duree_phrase_max)
                        except sr.WaitTimeoutError:
                            continue
                        self.dernier_son = time.monotonic()
                        try:
                            self.file_audio.put_nowait((audio, time.monotonic()))
                        except queue.Full:
                            pass
            except Exception as e:
                cfg.journal(f"Micro indisponible ({e}), nouvel essai dans 3 s")
                time.sleep(3)

    def _boucle_traitement(self):
        while self.actif:
            self._maj_affichage()
            try:
                audio, instant = self.file_audio.get(timeout=0.5)
            except queue.Empty:
                continue
            if self.en_pause:
                continue
            # On ignore ce que Capri vient de dire elle-même (écho du haut-parleur)
            duree = len(audio.frame_data) / (audio.sample_rate * audio.sample_width)
            if duree < 0.35:
                continue  # claquement ou bruit bref : inutile d'interroger le service de reconnaissance
            if self.voix.en_cours or self.voix.derniere_fin > instant - duree - 0.35:
                continue
            texte = self.reconnaitre(audio, duree)
            if texte:
                self._occupee = True
                try:
                    self.traiter_phrase(texte)
                except Exception as e:
                    cfg.journal(f"Erreur pendant le traitement de '{texte}': {e}\n{traceback.format_exc()}")
                finally:
                    self._occupee = False
                    if self.avatar.mode_courant == "reflechit":
                        self.avatar.definir_mode("repos")

    def _hypotheses(self, audio):
        """Les hypothèses de Google pour ce son (la meilleure en premier), ou None si le service est injoignable."""
        try:
            resultat = self.recognizer.recognize_google(audio, language='fr-FR', show_all=True)
        except sr.RequestError:
            cfg.journal("Erreur de connexion au service de reconnaissance")
            return None
        if isinstance(resultat, dict):
            return [h["transcript"].lower().strip() for h in resultat.get("alternative", []) if h.get("transcript")]
        return []

    def _debut_audio(self, audio, duree=1.3):
        """Le début de la phrase, à partir de la première voix : « Capri » isolé est bien mieux reconnu que dans une phrase."""
        largeur, rythme = audio.sample_width, audio.sample_rate
        brut = audio.get_raw_data()
        pas = int(rythme * 0.02) * largeur
        debut = 0
        if audioop is not None:
            for i in range(0, len(brut) - pas, pas):
                if audioop.rms(brut[i:i + pas], largeur) > self.recognizer.energy_threshold:
                    debut = i
                    break
        debut = max(0, debut - int(rythme * 0.12) * largeur)
        return sr.AudioData(brut[debut:debut + int(rythme * duree) * largeur], rythme, largeur)

    def _detecter_appel(self, texte):
        """(True, reste) si la phrase commence par « Capri » ou par un mot que la reconnaissance entend à sa place."""
        conf = self.config["ecoute"]
        appelee, reste = extraire_mot_activation(texte, conf.get("alias_debut", []))
        if appelee:
            return True, reste
        mots = texte.split()
        if mots and normaliser(mots[0]) in {normaliser(a) for a in conf.get("alias_si_ordre", [])}:
            reste = " ".join(mots[1:]).strip(" ,.!?;:")
            if reste and (self.handler.reconnaitre(reste) or self.cerveau.conversation_locale(reste)):
                return True, reste
        return False, texte

    def _sans_mot_mal_entendu(self, texte):
        """Retire le premier mot de la phrase s'il est probablement « Capri » mal entendu (« prix recherche github »)."""
        mots = texte.split()
        if not mots:
            return texte
        conf = self.config["ecoute"]
        suspects = {normaliser(a) for a in conf.get("alias_debut", []) + conf.get("alias_si_ordre", [])}
        reste = " ".join(mots[1:])
        if (normaliser(mots[0]) in suspects or similarite_capri(mots[0]) >= 0.5
                or (not self.handler.reconnaitre(texte) and (self.handler.reconnaitre(reste)
                                                              or self.cerveau.conversation_locale(reste)))):
            return reste
        return texte

    def reconnaitre(self, audio, duree=0.0):
        """Reconnaissance vocale (français, puis anglais en secours), avec plusieurs chances de reconnaître « Capri » :
        les autres hypothèses de Google, puis le début de la phrase écouté seul.
        """
        hypotheses = self._hypotheses(audio)
        if hypotheses is None:
            return ""
        if not hypotheses:
            if not self.config["ecoute"].get("anglais_secours", True):
                return ""
            try:
                return self.recognizer.recognize_google(audio, language='en-US').lower().strip()
            except sr.UnknownValueError:
                return ""
            except sr.RequestError:
                cfg.journal("Erreur de connexion au service de reconnaissance")
                return ""
        texte = hypotheses[0]
        if len(hypotheses) > 1:
            cfg.journal(f"   (hypothèses : {' | '.join(hypotheses)})")
        if not self._detecter_appel(texte)[0]:
            autre = next((h for h in hypotheses[1:] if self._detecter_appel(h)[0]), None)
            if autre:
                texte = autre
            elif duree > 1.2 and time.monotonic() >= self.fin_attente and not self.handler.choix_actif():
                debut = self._hypotheses(self._debut_audio(audio)) or []
                if any(self._detecter_appel(h)[0] for h in debut):
                    cfg.journal(f"   (début de phrase entendu : {' | '.join(debut)})")
                    texte = f"capri {self._sans_mot_mal_entendu(texte)}".strip()
        return texte

    def _maj_affichage(self):
        """Fait suivre l'état de l'avatar : endormie en pause, attentive quand on l'a appelée."""
        mode = self.avatar.mode_courant
        if self.en_pause:
            if mode != "dort":
                self.avatar.definir_mode("dort")
            return
        if self.voix.en_cours or self._occupee or self._autonome_actif or mode not in ("repos", "ecoute", "dort"):
            return
        cible = "ecoute" if time.monotonic() < self.fin_attente else "repos"
        if mode != cible:
            self.avatar.definir_mode(cible)

    def traiter_phrase(self, texte):
        """Une demande n'est prise en compte que si elle commence par « Capri » (ou suit un « Capri » seul)."""
        cfg.journal(f"Vous : {texte}")
        appelee, reste = self._detecter_appel(texte)
        if appelee:
            self.apparaitre()
            if reste:
                self.fin_attente = 0.0
                self.traiter_demande(reste)
            else:
                self.appel_seul()
        elif time.monotonic() < self.fin_attente or self.handler.est_reponse_choix(texte):
            # la demande attendue après un « Capri » seul, ou le numéro choisi dans une liste proposée
            self.fin_attente = 0.0
            self.traiter_demande(texte)
        # sinon : conversation ambiante, on ignore

    def apparaitre(self):
        """Capri est appelée : elle se montre si elle était cachée (environ une seconde)."""
        self._cachee_auto = False
        self.avatar.montrer(None)
        self._planifier(visible=True)

    def appel_seul(self):
        """« Capri » sans demande : réaction visuelle uniquement, pour ne pas couvrir la demande qui suit."""
        self.avatar.definir_mode("surpris", duree=0.5)
        self.fin_attente = time.monotonic() + self.config["ecoute"].get("attente_demande_secondes", 10)

    def traiter_demande(self, demande):
        """Exécute un ordre ou engage la conversation."""
        demande = demande.strip()
        if not demande:
            return
        self.avatar.afficher_utilisateur(demande)
        if est_demande_arret(demande):
            self.parler("D'accord, je coupe la connexion. À la prochaine, voyageur du réseau.", "layingdown")
            self.arreter()
            return

        # Exemple : "ouvre word", "lance chrome", "ouvre spotify" : raccourci du menu Démarrer d'abord
        c = self.handler._sans_politesse(demande)
        if c.startswith(("ouvre ", "lance ")):
            nom_app = c.replace("ouvre ", "").replace("lance ", "").strip()
            if self.trouver_et_lancer_application(nom_app):
                self.parler(random.choice((f"{nom_app}, c'est parti.", f"J'ouvre {nom_app}.", f"Je te lance {nom_app}.")),
                            "excited")
                return

        reponse = self.handler.executer(demande)
        if reponse is not None:
            self.parler(reponse, self.cerveau.emotion_pour_commande(reponse))
        else:
            if self.cerveau.llm.actif():
                self.avatar.definir_mode("reflechit")
            rep = self.cerveau.repondre(demande)
            if rep.action and rep.action[0] == "recherche":
                self.handler.rechercher_web(f"recherche {rep.action[1]}")
            self.parler(rep.texte, rep.emotion)

    # ------------------------------------------------- initiatives spontanées ---

    # niveau de bavardage -> (probabilité de parler, bavardage libre, multiplicateur des délais entre initiatives)
    NIVEAUX_PAROLE = {
        "silencieuse": (0.0, False, 1.0),
        "discrete": (0.35, True, 2.0),
        "normale": (None, None, 1.0),
        "bavarde": (1.0, True, 0.5),
    }

    def _niveau_parole(self):
        niveau = self.config["phrases"].get("niveau_parole", "normale")
        return self.NIVEAUX_PAROLE.get(niveau, self.NIVEAUX_PAROLE["normale"])

    def _planifier(self, visible):
        """Tire au hasard le moment de sa prochaine initiative (disparaître, réapparaître, se téléporter, parler)."""
        conf = self.config["phrases"]
        cle, defaut = ("visible_secondes", (30, 120)) if visible else ("cachee_secondes", (15, 75))
        try:
            bas, haut = conf.get(cle, defaut)
        except (TypeError, ValueError):
            bas, haut = defaut
        mult = self._niveau_parole()[2]
        self._prochaine_initiative = time.monotonic() + random.uniform(min(bas, haut), max(bas, haut)) * mult

    def _disponible(self):
        """Capri ne prend l'initiative que lorsqu'elle n'est ni en train d'écouter ni de parler, ni quand on parle."""
        return (not self.en_pause and not self.voix.en_cours and not self._occupee
                and time.monotonic() >= self.fin_attente and not self.handler.choix_actif()
                and time.monotonic() - self.dernier_son > 4 and self.file_audio.empty()
                and not self.avatar.en_transition and not self.avatar.en_traversee
                and self.avatar.mode_courant in ("repos", "dort"))

    def _dire_spontane(self, section, probabilite=None):
        if probabilite is None:
            probabilite = self._niveau_parole()[0]
            if probabilite is None:
                probabilite = self.config["phrases"].get("probabilite", 0.8)
        elif self._niveau_parole()[0] == 0.0:
            return
        if random.random() > probabilite:
            return
        choix = self.phrases.choisir(section)
        if choix:
            self.parler(*choix)

    def _attendre_effet(self, nom):
        """Laisse l'éclair se terminer avant de parler."""
        time.sleep(self.avatar.duree_effet(nom) + 0.15)

    def _planifier_eclair(self):
        try:
            bas, haut = self.config["avatar"].get("eclairs_secondes", (6, 25))
        except (TypeError, ValueError):
            bas, haut = 6, 25
        self._prochain_eclair = time.monotonic() + random.uniform(min(bas, haut), max(bas, haut))

    def _boucle_autonome(self):
        self._planifier(visible=True)
        self._prochaine_initiative = max(self._prochaine_initiative, time.monotonic() + 20)
        self._planifier_eclair()
        while self.actif:
            time.sleep(1.0)
            if not self._disponible():
                if time.monotonic() >= self._prochaine_initiative:
                    self._prochaine_initiative = time.monotonic() + 5
                continue
            # cachée d'elle-même : des éclairs continuent de traverser l'écran, comme si elle voyageait dans le réseau
            if (self._cachee_auto and not self.avatar.visible and time.monotonic() >= self._prochain_eclair
                    and self.config["avatar"].get("eclairs_cachee", True)):
                self.avatar.eclair_traversant()
                self._planifier_eclair()
                continue
            if time.monotonic() < self._prochaine_initiative:
                continue
            conf_avatar = self.config["avatar"]
            options = []   # (action, poids)
            if conf_avatar.get("apparitions_auto", True):
                options.append((self._initiative_disparition, 2))
            if conf_avatar.get("deplacements_auto", True):
                options.append((self._initiative_deplacement, 1))
            bavarde = self._niveau_parole()[1]
            if self.config["phrases"].get("bavardage", True) if bavarde is None else bavarde:
                options.append((self._initiative_bavardage, 2))
            self._autonome_actif = True
            try:
                if self.avatar.visible:
                    if options:
                        actions, poids = zip(*options)
                        random.choices(actions, weights=poids)[0]()
                    else:
                        self._planifier(visible=True)
                elif self._cachee_auto:
                    self._initiative_apparition()
                else:
                    self._planifier(visible=False)   # cachée à la demande de l'utilisateur : elle reste cachée
            except Exception as e:
                cfg.journal(f"Erreur pendant une initiative: {e}\n{traceback.format_exc()}")
                self._planifier(visible=True)
            finally:
                self._autonome_actif = False

    def _initiative_disparition(self):
        self._dire_spontane("disparition")
        self._cachee_auto = True
        self.avatar.cacher()
        self._attendre_effet("disparition")
        self._planifier(visible=False)
        self._planifier_eclair()

    def _initiative_apparition(self):
        """Elle revient à un endroit quelconque de l'écran, le plus souvent amenée par un éclair qui la traverse."""
        self._cachee_auto = False
        if random.random() < 0.7:
            self.avatar.apparaitre_par_eclair()
            time.sleep(self.avatar.duree_traversee() + 0.1)
        else:
            self.avatar.montrer("hasard")
        self._attendre_effet("apparition")
        self._dire_spontane("apparition")
        self._planifier(visible=True)

    def _initiative_deplacement(self):
        self.avatar.teleporter("hasard")
        self._attendre_effet("teleportation")
        self._dire_spontane("deplacement")
        self._planifier(visible=True)

    def _initiative_bavardage(self):
        """Une phrase de phrases.txt, sans bouger : elle se manifeste simplement."""
        self._dire_spontane("bavardage", probabilite=1.0)
        self._planifier(visible=True)

    # ---------------------------------------------------- événements avatar ---

    def _evenement_avatar(self, evenement, **infos):
        if evenement == "clic":
            self._parler_en_tache_de_fond(self.cerveau.clic(), "surprised")
        elif evenement == "double_clic":
            self.appel_seul()
        elif evenement == "menu":
            action = infos.get("action")
            if action == "masquer":
                self.basculer_avatar(None, None)
            elif action == "teleporter":
                self.avatar.teleporter("hasard")
            elif action == "muet":
                self.basculer_voix(None, None)
            elif action == "pause":
                self.toggle_pause(None, None)
            elif action == "quitter":
                threading.Thread(target=self.arreter, daemon=True).start()

    # ------------------------------------------------------ menu de la zone de notification ---

    def basculer_avatar(self, icon, item_):
        """Afficher / cacher à la main : cachée ainsi, elle ne revient que si on l'appelle ou la réaffiche."""
        self._cachee_auto = False
        if self.avatar.visible:
            self.avatar.cacher()
        else:
            self.apparaitre()

    def toggle_pause(self, icon, item_):
        """Active/désactive l'écoute"""
        self.en_pause = not self.en_pause
        if self.en_pause:
            cfg.journal("Capri en pause")
            self.avatar.definir_mode("dort")
        else:
            cfg.journal("Capri écoute de nouveau")
            self.avatar.definir_mode("repos")

    def basculer_voix(self, icon, item_):
        self.config["voix"]["muet"] = not self.config["voix"].get("muet", False)
        cfg.sauvegarder(self.config)
        cfg.journal("Voix coupée" if self.config["voix"]["muet"] else "Voix réactivée")

    def changer_moteur_voix(self, moteur):
        self.config["voix"]["moteur"] = moteur
        cfg.sauvegarder(self.config)
        cfg.journal(f"Moteur de voix : {moteur}")
        self.voix._indispo.clear()
        threading.Thread(target=self.parler, args=("Voilà, tu entends ma nouvelle voix ?", "happy"), daemon=True).start()

    def changer_niveau_parole(self, niveau):
        self.config["phrases"]["niveau_parole"] = niveau
        cfg.sauvegarder(self.config)
        cfg.journal(f"Niveau de bavardage : {niveau}")
        self._planifier(visible=self.avatar.visible)

    def basculer_option(self, section, cle):
        self.config[section][cle] = not self.config[section].get(cle, True)
        cfg.sauvegarder(self.config)

    def basculer_cliquable(self, icon, item_):
        self.basculer_option("avatar", "cliquable")
        self.avatar.definir_cliquable(self.config["avatar"]["cliquable"])

    def changer_taille(self, nom):
        self.avatar.changer_taille(nom)

    def quitter(self, icon, item_):
        """Quitte l'application"""
        cfg.journal("Arrêt de Capri...")
        self.arreter()

    def afficher_status(self, icon, item_):
        """Affiche le statut dans le journal et dans une bulle"""
        etat = "en pause" if self.en_pause else "à l'écoute"
        mode = "économie" if self.mode_economie else "normal"
        moteurs = ", ".join(self.voix.moteurs_disponibles()) or "aucun"
        cerveau = "LLM connecté" if self.cerveau.llm.actif() else "répliques intégrées"
        message = f"Statut : {etat}. Mode {mode}. Voix : {moteurs}. Cerveau : {cerveau}."
        cfg.journal(message)
        self.avatar.afficher_bulle(message, 0.0)

    def toggle_mode_economie(self, icon, item_):
        """Bascule entre mode normal et mode économie"""
        # Détecter d'abord le mode batterie
        if self.detecter_mode_batterie():
            # Forcer le mode économie si sur batterie
            self.appliquer_mode(True)
            cfg.journal("Sur batterie - Mode économie forcé")
        else:
            self.appliquer_mode(not self.mode_economie)
            cfg.journal("Mode économie" if self.mode_economie else "Mode normal")

    def creer_menu(self):
        """Crée le menu de l'icône (zone de notification)"""
        a = self.config["avatar"]

        def coin(nom, libelle):
            return item(libelle, lambda icon, i: self.avatar.teleporter(nom))

        def taille(nom, libelle):
            return item(libelle, lambda icon, i: self.changer_taille(nom),
                        checked=lambda i: a.get("taille") == nom, radio=True)

        def moteur(nom, libelle):
            return item(libelle, lambda icon, i: self.changer_moteur_voix(nom),
                        checked=lambda i: self.config["voix"].get("moteur", "auto") == nom, radio=True)

        def parole(nom, libelle):
            return item(libelle, lambda icon, i: self.changer_niveau_parole(nom),
                        checked=lambda i: self.config["phrases"].get("niveau_parole", "normale") == nom, radio=True)

        return pystray.Menu(
            item(lambda i: 'Cacher Capri' if self.avatar.visible else 'Afficher Capri', self.basculer_avatar, default=True),
            item('Se téléporter', pystray.Menu(
                coin("bas_droite", "Bas à droite"), coin("bas_gauche", "Bas à gauche"),
                coin("haut_droite", "Haut à droite"), coin("haut_gauche", "Haut à gauche"),
                coin("centre", "Au centre de l'écran"),
                pystray.Menu.SEPARATOR, coin("hasard", "Au hasard"))),
            item('Taille', pystray.Menu(taille("petite", "Petite"), taille("moyenne", "Moyenne"), taille("grande", "Grande"))),
            item('Apparitions automatiques', lambda icon, i: self.basculer_option("avatar", "apparitions_auto"),
                 checked=lambda i: a.get("apparitions_auto", True)),
            item('Déplacements automatiques', lambda icon, i: self.basculer_option("avatar", "deplacements_auto"),
                 checked=lambda i: a.get("deplacements_auto", True)),
            item('Bulles de texte', lambda icon, i: self.basculer_option("avatar", "bulle"),
                 checked=lambda i: a.get("bulle", True)),
            item('Cliquable (déplaçable à la souris)', self.basculer_cliquable,
                 checked=lambda i: a.get("cliquable", True)),
            pystray.Menu.SEPARATOR,
            item('Voix', self.basculer_voix, checked=lambda i: not self.config["voix"].get("muet", False)),
            item('Choix de la voix', pystray.Menu(
                moteur("auto", "Automatique (voix de Capri)"), moteur("capri", "Voix de Capri"),
                moteur("local", "Voix Piper (secours)"), moteur("windows", "Voix Windows (Hortense)"),
                moteur("edge", "Voix Microsoft Edge (en ligne)"))),
            item('Elle parle...', pystray.Menu(
                parole("silencieuse", "Jamais d'elle-même"), parole("discrete", "Rarement"),
                parole("normale", "Normalement"), parole("bavarde", "Beaucoup"))),
            item(lambda i: 'Reprendre l\'écoute' if self.en_pause else 'Mettre en pause', self.toggle_pause),
            item(lambda i: 'Mode normal' if self.mode_economie else 'Mode économie', self.toggle_mode_economie),
            item('Afficher le statut', self.afficher_status),
            pystray.Menu.SEPARATOR,
            item('Quitter', self.quitter)
        )

    # ---------------------------------------------------------- démarrage ----

    def arreter(self):
        """Ferme Capri proprement (avatar, voix, icône)."""
        if not self.actif:
            return
        self.actif = False
        self.voix.arreter()
        self.avatar.cacher()
        time.sleep(0.9)
        self.avatar.arreter()
        if self.tray_icon:
            self.tray_icon.stop()

    def _icone(self):
        """Icône de la zone de notification : icon.png (ou icon.ico), ramenée à 64 px pour rester nette."""
        for chemin in (cfg.ICONE_PNG, cfg.ICONE_ICO):
            try:
                image = Image.open(chemin).convert("RGBA")
                return image.resize((64, 64), Image.Resampling.LANCZOS)
            except Exception:
                continue
        return Image.new('RGB', (64, 64), color=(255, 32, 130))   # icône de secours

    def demarrer(self):
        """Démarre Capri : avatar, voix, écoute et icône de la zone de notification"""
        cfg.journal(f"Démarrage de {self.nom}...")
        self.actif = True
        self.avatar.demarrer()
        self.voix.prechauffer()

        if not self.sans_micro:
            self.thread_ecoute = threading.Thread(target=self.boucle_ecoute, name="capri-ecoute", daemon=True)
            self.thread_ecoute.start()
        else:
            threading.Thread(target=self._boucle_traitement, name="capri-traitement", daemon=True).start()
        threading.Thread(target=self._message_bienvenue, daemon=True).start()
        threading.Thread(target=self._boucle_autonome, name="capri-initiatives", daemon=True).start()
        if self.signal_relance:
            threading.Thread(target=self._surveiller_relance, daemon=True).start()

        # Créer et démarrer l'icône de la zone de notification
        self.tray_icon = pystray.Icon(
            "capri_assistant",
            self._icone(),
            f"{self.nom} - Assistante vocale",
            menu=self.creer_menu()
        )

        cfg.journal(f"{self.nom} est en ligne. Voix : {', '.join(self.voix.moteurs_disponibles()) or 'aucune'}. "
                    f"Cerveau : {'LLM' if self.cerveau.llm.actif() else 'répliques intégrées'}. "
                    f"Mode {'économie' if self.mode_economie else 'normal'}.")

        # Lancer l'icône (bloquant)
        self.tray_icon.run()

    def _message_bienvenue(self):
        """Message de bienvenue (dans un thread séparé), une fois le micro calibré : sa voix ne doit pas fausser le seuil."""
        time.sleep(1.2)
        if not self.sans_micro:
            self.micro_pret.wait(8)
        self.parler(self.cerveau.demarrage(), "excited")

    def _surveiller_relance(self):
        """Si le raccourci est relancé alors que Capri tourne déjà, elle se montre."""
        while self.actif:
            if kernel32.WaitForSingleObject(self.signal_relance, 1000) == 0 and self.actif:
                self.apparaitre()
                self._parler_en_tache_de_fond("Je suis déjà là ! Pas besoin de me relancer, je ne bouge pas du réseau.", "excited")


def instance_unique():
    """Retourne (mutex, événement) si c'est la première instance, sinon signale l'autre et retourne None."""
    mutex = kernel32.CreateMutexW(None, False, "Local\\CapriAssistanteVocale")
    deja = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    signal = kernel32.CreateEventW(None, False, False, "Local\\CapriAssistanteVocaleSignal")
    if deja:
        kernel32.SetEvent(signal)
        return None
    return mutex, signal


def main():
    """Point d'entrée principal"""
    parser = argparse.ArgumentParser(description="Capri - assistante vocale")
    parser.add_argument("--muet", action="store_true", help="pas de son : sous-titres et bouche animée seulement")
    parser.add_argument("--sans-micro", action="store_true", help="n'écoute pas le micro (tests visuels)")
    args = parser.parse_args()

    rendre_dpi_precis()
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Capri.AssistanteVocale")
    except Exception:
        pass

    verrou = instance_unique()
    if verrou is None:
        return

    try:
        cfg.journal("=" * 60)
        cfg.journal("CAPRI - ASSISTANTE VOCALE")
        cfg.journal("=" * 60)
        assistant = AssistantVocal(nom="Capri", muet=args.muet, sans_micro=args.sans_micro, signal_relance=verrou[1])

        try:
            assistant.demarrer()
        except KeyboardInterrupt:
            cfg.journal("Arrêt de Capri (Ctrl+C)")
            assistant.arreter()
        except Exception as e:
            cfg.journal(f"Erreur: {e}\n{traceback.format_exc()}")
            raise

    except Exception as e:
        # Erreur critique avant même la création de l'assistant
        cfg.journal(f"Erreur critique lors de l'initialisation:\n{e}\n{traceback.format_exc()}")

        # Afficher un message Windows
        try:
            ctypes.windll.user32.MessageBoxW(
                0, f"Erreur lors du démarrage de Capri :\n\n{str(e)}\n\nConsultez capri_log.txt pour plus de détails.",
                "Capri - Erreur", 0x10)
        except Exception:
            pass

        sys.exit(1)

    # Les bibliothèques audio natives peuvent retenir le processus : on termine explicitement
    cfg.journal("Capri s'est arrêtée.")
    os._exit(0)


if __name__ == "__main__":
    main()
