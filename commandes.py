"""
Gestionnaire de commandes de Capri (applications, web, volume, système...)
"""

import datetime
import webbrowser
import os
import random
import re
import subprocess
import psutil
import pyautogui
import time
import winreg
from pathlib import Path
import glob


def _v(*variantes):
    """Choisit une formulation au hasard pour que Capri ne se répète pas."""
    return random.choice(variantes)


POLITESSE = re.compile(
    r"^(?:(?:s'il (?:te|vous) pla[iî]t|stp|please|alors|bon|et|donc|ok|merci)[, ]+)*"
    r"(?:(?:peux|pourrais|veux|voudrais)[- ]tu |tu (?:peux|pourrais|veux|voudrais) |je (?:voudrais|veux) |j'aimerais )?"
    r"(?:me |nous )?(?:s'il (?:te|vous) pla[iî]t )?")

NOMBRES = {"un": 1, "une": 1, "premier": 1, "première": 1, "deux": 2, "deuxième": 2, "second": 2, "seconde": 2,
           "trois": 3, "troisième": 3, "quatre": 4, "quatrième": 4, "cinq": 5, "cinquième": 5}

# Jamais fermés par la commande "ferme ..." (système, explorateur, et Capri elle-même)
PROCESSUS_PROTEGES = {
    "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "services.exe", "lsass.exe",
    "winlogon.exe", "svchost.exe", "explorer.exe", "dwm.exe", "fontdrvhost.exe", "python.exe", "pythonw.exe",
}


class CommandeHandler:
    def __init__(self):
        # Cache pour les applications trouvées et les choix utilisateur
        self.apps_cache = {}
        self.choix_en_attente = None
        self.choix_depuis = 0.0
        self.dernieres_options = []
        self.assistant_parler = None  # Sera défini par l'assistant
        self.extinction_depuis = 0.0
        
        # Corrections automatiques des erreurs de reconnaissance vocale
        self.corrections_vocales = {
            'discorde': 'discord',
            'discord': 'discord',
            'world': 'word',
            'word': 'word',
            'chrome': 'chrome',
            'crome': 'chrome',
            'fire fox': 'firefox',
            'firefox': 'firefox',
            'steam': 'steam',
            'stim': 'steam',
            'spotify': 'spotify',
            'spotifaille': 'spotify',
            'visual': 'visual',
            'vizual': 'visual',
            'code': 'code',
            'excel': 'excel',
            'exel': 'excel',
            'powerpoint': 'powerpoint',
            'power point': 'powerpoint',
            'outlook': 'outlook',
            'autlook': 'outlook',
        }
        # (motif, fonction) : le premier motif qui correspond l'emporte
        self.table = [
            (r"\bquelle heure\b|\bl'heure\b|\bheure est[- ]il\b|\bheure qu'il est\b", self.dire_heure),
            (r"\bquel jour\b|\bquelle date\b|\bla date\b|\bquel est le jour\b", self.dire_date),
            (r"^(ouvre|ouvrir|ouvrez|lance|lancer|lancez|démarre|démarrer)\b", self.ouvrir_application),
            (r"^(mets|joue|passe)( moi)?( de la| la| une?)? ?musique", self.ouvrir_musique),
            (r"^(ferme|fermer|fermez)\b", self.fermer_application),
            (r"\byou ?tube\b", self.ouvrir_youtube),
            (r"^(recherche|cherche|google|trouve|fais une recherche)\b|\b(recherche|cherche)[- ]moi\b", self.rechercher_web),
            (r"\bvolume\b|^(monte|augmente|baisse|diminue|coupe|rétablis|remets|mets|active|désactive)\b.*\b(son|volume)\b"
             r"|^(mute|unmute)\b|\b(plus|moins) fort\b", self.controler_volume),
            (r"\bcapture d'écran\b|\bscreenshot\b|^(fais|prends|prend)( une)? capture", self.capture_ecran),
            (r"\b(éteins|éteindre|shutdown|arrête)\b.*\b(pc|ordinateur|machine|windows)\b|\bshutdown\b", self.eteindre_pc),
            (r"\bflashbang\b|\bluminosité\b", self.flashbang),
            (r"\bverrouill\w*|\block\b", self.verrouiller_session),
            (r"^(le |la |l')?(notepad|bloc[- ]notes?)$", self.ouvrir_notepad),
            (r"^(la |le )?calculatrice$", self.ouvrir_calculatrice),
            (r"^(l')?explorateur( de fichiers)?$|^mes fichiers$", self.ouvrir_explorateur),
            (r"^(le )?navigateur$", self.ouvrir_navigateur),
            (r"^(google )?chrome$", self.ouvrir_chrome),
            (r"^(microsoft )?edge$", self.ouvrir_edge),
            (r"^firefox$", self.ouvrir_firefox),
        ]
    
    @staticmethod
    def _sans_politesse(commande):
        return POLITESSE.sub("", commande, count=1).strip()
    
    def choix_actif(self):
        """Vrai tant qu'une liste d'applications attend le numéro choisi (expire au bout de 45 s)."""
        if self.choix_en_attente and time.time() - self.choix_depuis > 45:
            self.choix_en_attente = None
            self.dernieres_options = []
        return bool(self.choix_en_attente)

    def est_reponse_choix(self, commande):
        """Vrai si la phrase donne un numéro en réponse à la liste proposée (sans avoir à dire « Capri »)."""
        c = self._sans_politesse(commande.lower().strip())
        return self.choix_actif() and bool(re.search(r"\d", c) or any(m in c.split() for m in NOMBRES))

    def reconnaitre(self, commande):
        """Retourne la fonction qui traite la commande, ou None si ce n'est pas un ordre."""
        c = self._sans_politesse(commande.lower().strip())
        if self.est_reponse_choix(commande):
            return self.traiter_choix_application
        if self.extinction_depuis and time.time() - self.extinction_depuis < 90 and re.search(r"\bannul", c):
            return self.annuler_extinction
        for motif, fonction in self.table:
            if re.search(motif, c):
                return fonction
        return None
    
    def executer(self, commande):
        """Exécute la commande appropriée (None si ce n'est pas un ordre)"""
        c = self._sans_politesse(commande.lower().strip())
        fonction = self.reconnaitre(commande)
        if fonction is None:
            return None
        try:
            return fonction(c)
        except Exception as e:
            return f"Erreur lors de l'exécution: {str(e)}"
    
    def annuler_extinction(self, commande):
        self.extinction_depuis = 0.0
        try:
            subprocess.run(['shutdown', '/a'])
        except Exception:
            pass
        return _v("Extinction annulée. On reste connectés.", "C'est annulé. Le PC reste allumé.")
    
    def dire_heure(self, commande):
        """Donne l'heure actuelle"""
        maintenant = datetime.datetime.now()
        heure = maintenant.strftime("%H heures %M")
        return _v(f"Il est {heure}.", f"{heure}. Le temps file vite dans le réseau.", f"Il est exactement {heure}.")
    
    def dire_date(self, commande):
        """Donne la date actuelle"""
        maintenant = datetime.datetime.now()
        jours = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']
        mois = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin',
                'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
        
        jour_semaine = jours[maintenant.weekday()]
        jour = maintenant.day
        mois_nom = mois[maintenant.month - 1]
        annee = maintenant.year
        
        return _v(f"Nous sommes le {jour_semaine} {jour} {mois_nom} {annee}.",
                  f"On est {jour_semaine}, le {jour} {mois_nom} {annee}.")
    
    def ouvrir_application(self, commande):
        """Ouvre une application spécifique"""
        # Extraire le nom de l'application
        if 'notepad' in commande or 'bloc-notes' in commande or 'bloc note' in commande:
            return self.ouvrir_notepad(commande)
        elif 'calculatrice' in commande or 'calcul' in commande:
            return self.ouvrir_calculatrice(commande)
        elif 'chrome' in commande:
            return self.ouvrir_chrome(commande)
        elif 'edge' in commande:
            return self.ouvrir_edge(commande)
        elif 'firefox' in commande:
            return self.ouvrir_firefox(commande)
        elif 'explorateur' in commande or 'fichier' in commande:
            return self.ouvrir_explorateur(commande)
        elif 'youtube' in commande:
            return self.ouvrir_youtube(commande)
        else:
            # Essayer d'ouvrir n'importe quelle application par son nom
            return self.ouvrir_app_generique(commande)
    
    def ouvrir_notepad(self, commande):
        """Ouvre le bloc-notes"""
        subprocess.Popen(['notepad.exe'])
        return _v("Bloc-notes, c'est parti.", "J'ouvre le bloc-notes. Une page blanche, tout un monde à écrire.")
    
    def ouvrir_calculatrice(self, commande):
        """Ouvre la calculatrice"""
        subprocess.Popen(['calc.exe'])
        return _v("La calculatrice arrive. Les chiffres, ça me connaît.", "J'ouvre la calculatrice.")
    
    def ouvrir_explorateur(self, commande):
        """Ouvre l'explorateur de fichiers"""
        subprocess.Popen(['explorer.exe'])
        return _v("J'ouvre l'explorateur de fichiers. Bonne exploration.", "Voilà tes fichiers, prêts à être fouillés.")
    
    def ouvrir_navigateur(self, commande):
        """Ouvre le navigateur par défaut"""
        webbrowser.open('https://www.google.com')
        return _v("Je t'ouvre une fenêtre sur le réseau.", "J'ouvre le navigateur.")
    
    def ouvrir_chrome(self, commande):
        """Ouvre Google Chrome"""
        try:
            chrome_path = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
            if os.path.exists(chrome_path):
                subprocess.Popen([chrome_path])
                return _v("Chrome, c'est parti.", "J'ouvre Google Chrome. Direction le web.")
            else:
                webbrowser.open('https://www.google.com')
                return "Chrome est introuvable, alors j'ouvre le navigateur par défaut."
        except:
            return "Impossible d'ouvrir Chrome."
    
    def ouvrir_edge(self, commande):
        """Ouvre Microsoft Edge"""
        try:
            subprocess.Popen(['msedge.exe'])
            return _v("Edge, c'est parti.", "J'ouvre Microsoft Edge.")
        except:
            return "Impossible d'ouvrir Edge."
    
    def ouvrir_firefox(self, commande):
        """Ouvre Firefox"""
        try:
            firefox_path = r'C:\Program Files\Mozilla Firefox\firefox.exe'
            if os.path.exists(firefox_path):
                subprocess.Popen([firefox_path])
                return _v("Firefox, c'est parti.", "J'ouvre Firefox.")
            else:
                return "Firefox n'est pas installé sur ce PC."
        except:
            return "Impossible d'ouvrir Firefox."
    
    def rechercher_web(self, commande):
        """Effectue une recherche sur Google"""
        # Extraire la requête
        mots_cles = ['recherche', 'google', 'cherche', 'trouve']
        requete = commande
        
        for mot in mots_cles:
            if mot in commande:
                requete = commande.split(mot, 1)[1].strip()
                break
        requete = re.sub(r"^(moi |sur (google|internet|le web|le net) |des informations sur |ça |ca )+", "", requete).strip()
        
        if requete:
            url = f"https://www.google.com/search?q={requete.replace(' ', '+')}"
            webbrowser.open(url)
            return _v(f"Je plonge dans le réseau pour {requete}.", f"Recherche lancée : {requete}.",
                      f"Je fouille le web pour {requete}.")
        else:
            return "Qu'est-ce que tu veux que j'aille chercher dans le réseau ?"
    
    def ouvrir_youtube(self, commande):
        """Ouvre YouTube, ou y lance une recherche (« recherche chats mignons sur youtube »)"""
        m = re.search(r"\b(?:recherche|cherche|trouve)\b(.*)", commande)
        if m:
            recherche = re.sub(r"\b(?:sur |dans )?(?:youtube|you tube)\b|^\s*(?:moi|des?|du|la|le|les)\s+", "", m.group(1)).strip()
            if recherche:
                url = f"https://www.youtube.com/results?search_query={recherche.replace(' ', '+')}"
                webbrowser.open(url)
                return _v(f"Je cherche {recherche} sur YouTube.", f"{recherche} sur YouTube, c'est parti.")
        
        # Ouvrir YouTube directement
        webbrowser.open('https://www.youtube.com')
        return _v("J'ouvre YouTube.", "YouTube, le grand flux vidéo. J'ouvre ça.")
    
    def ouvrir_musique(self, commande):
        """Ouvre un lecteur de musique"""
        # Essayer d'ouvrir Spotify, sinon YouTube Music
        try:
            subprocess.Popen(['spotify.exe'])
            return _v("J'ouvre Spotify. Mets-toi à l'aise.", "Spotify arrive. Une bande-son pour ton flux de pensées.")
        except:
            webbrowser.open('https://music.youtube.com')
            return "Spotify est introuvable, j'ouvre YouTube Music."
    
    def controler_volume(self, commande):
        """Contrôle le volume du système"""
        try:
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            
            pourcentage = re.search(r"(\d{1,3})\s*(%|pour ?cent)?", commande)
            if 'maximum' in commande or 'à fond' in commande:
                volume.SetMasterVolumeLevelScalar(1.0, None)
                return _v("Volume au maximum. Accroche-toi.", "Je pousse le volume à fond.")
            elif 'minimum' in commande:
                volume.SetMasterVolumeLevelScalar(0.0, None)
                return "Volume au minimum."
            elif pourcentage and 'volume' in commande and not any(m in commande for m in ('monte', 'baisse', 'augmente', 'diminue')):
                valeur = max(0, min(100, int(pourcentage.group(1))))
                volume.SetMasterVolumeLevelScalar(valeur / 100, None)
                return f"Volume réglé à {valeur} pour cent."
            elif 'augmente' in commande or 'monte' in commande or 'plus fort' in commande:
                volume_actuel = volume.GetMasterVolumeLevelScalar()
                nouveau_volume = min(1.0, volume_actuel + 0.1)
                volume.SetMasterVolumeLevelScalar(nouveau_volume, None)
                return _v("Je monte le volume.", "Un peu plus de décibels, comme demandé.")
            elif 'baisse' in commande or 'diminue' in commande or 'moins fort' in commande:
                volume_actuel = volume.GetMasterVolumeLevelScalar()
                nouveau_volume = max(0.0, volume_actuel - 0.1)
                volume.SetMasterVolumeLevelScalar(nouveau_volume, None)
                return _v("Je baisse le volume.", "Un peu plus de calme dans le signal.")
            elif 'unmute' in commande or 'rétablis' in commande or 'remets' in commande or 'réactive' in commande:
                volume.SetMute(0, None)
                return _v("Le son est de retour.", "Je rétablis le son.")
            elif 'mute' in commande or 'coupe' in commande or 'silence' in commande:
                volume.SetMute(1, None)
                return _v("Son coupé. Silence radio.", "Je coupe le son.")
            return "Tu veux que je monte, que je baisse ou que je coupe le volume ?"
        except:
            return "Impossible de contrôler le volume. Installez pycaw avec: pip install pycaw"
    
    def rechercher_applications(self, recherche):
        """Recherche toutes les applications correspondantes dans le menu démarrer"""
        applications_trouvees = []
        recherche_lower = recherche.lower()
        
        # Chemins du menu démarrer
        chemins_menu = [
            os.path.join(os.environ['APPDATA'], 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
            os.path.join(os.environ['PROGRAMDATA'], 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
        ]
        
        for chemin in chemins_menu:
            if not os.path.exists(chemin):
                continue
            
            # Rechercher tous les .lnk récursivement (y compris sous-dossiers)
            for fichier_lnk in glob.glob(os.path.join(chemin, '**', '*.lnk'), recursive=True):
                nom_fichier = os.path.basename(fichier_lnk).replace('.lnk', '')
                
                # Calculer le score de similarité pour TOUTES les applications
                score = self._calculer_score_similarite(recherche_lower, nom_fichier.lower())
                
                # Garder seulement les applications avec un score significatif (>= 15)
                if score >= 15:
                    applications_trouvees.append({
                        'nom': nom_fichier,
                        'chemin': fichier_lnk,
                        'score': score
                    })
        
        # Trier par score de similarité (meilleur en premier)
        applications_trouvees.sort(key=lambda x: x['score'], reverse=True)
        
        return applications_trouvees
    
    def corriger_texte_reconnu(self, texte):
        """Corrige automatiquement les erreurs courantes de reconnaissance vocale"""
        texte_lower = texte.lower().strip()
        
        # Vérifier les corrections exactes
        if texte_lower in self.corrections_vocales:
            return self.corrections_vocales[texte_lower]
        
        # Vérifier les corrections partielles (mots contenus)
        for erreur, correction in self.corrections_vocales.items():
            if erreur in texte_lower:
                texte_lower = texte_lower.replace(erreur, correction)
        
        return texte_lower
    
    def _calculer_score_similarite(self, recherche, nom):
        """Calcule un score de similarité entre la recherche et le nom"""
        score = 0
        recherche_lower = recherche.lower()
        nom_lower = nom.lower()
        
        # Correspondance exacte = score maximal
        if recherche_lower == nom_lower:
            score += 100
        
        # Commence par le terme de recherche
        if nom_lower.startswith(recherche_lower):
            score += 50
        
        # Contient le terme de recherche
        if recherche_lower in nom_lower:
            score += 30
        
        # Similarité de Levenshtein simplifiée (distance d'édition)
        # Plus les mots sont proches, plus le score est élevé
        if len(recherche_lower) >= 3:
            # Compter les caractères en commun dans le même ordre
            communs = 0
            j = 0
            for i, char in enumerate(recherche_lower):
                while j < len(nom_lower):
                    if nom_lower[j] == char:
                        communs += 1
                        j += 1
                        break
                    j += 1
            
            if communs > 0:
                score += (communs / len(recherche_lower)) * 40
        
        # Mots en commun
        mots_recherche = set(recherche_lower.split())
        mots_nom = set(nom_lower.split())
        mots_communs = mots_recherche & mots_nom
        score += len(mots_communs) * 20
        
        # Bonus si peu de caractères en plus
        diff_longueur = abs(len(nom_lower) - len(recherche_lower))
        score -= diff_longueur * 0.5
        
        return score
    
    def ouvrir_app_generique(self, commande):
        """Ouvre n'importe quelle application par son nom"""
        # Une nouvelle demande d'ouverture annule la liste de choix en attente
        self.choix_en_attente = None
        self.dernieres_options = []
        
        # Extraire le nom de l'application après "ouvre", "ouvrir", "lance"...
        nom_app = re.sub(r"^(ouvrir|ouvrez|ouvre|lancer|lancez|lance|démarrer|démarre)\s*", "", commande).strip()
        
        if not nom_app:
            return "Quelle application tu veux que j'ouvre ?"
        
        # Corriger les erreurs de reconnaissance vocale
        nom_app = self.corriger_texte_reconnu(nom_app)
        
        # Rechercher dans le cache d'abord
        if nom_app.lower() in self.apps_cache:
            chemin = self.apps_cache[nom_app.lower()]
            try:
                os.startfile(chemin)
                return _v(f"{nom_app}, c'est parti.", f"J'ouvre {nom_app}.")
            except Exception as e:
                # Si échec, supprimer du cache
                del self.apps_cache[nom_app.lower()]
        
        # Rechercher l'application
        apps_trouvees = self.rechercher_applications(nom_app)
        
        if not apps_trouvees:
            # Pas d'application trouvée
            return f"Je ne trouve pas l'application {nom_app} dans le réseau de ce PC. Elle est bien installée ?"
        
        elif len(apps_trouvees) == 1:
            # Une seule application trouvée, l'ouvrir directement
            app = apps_trouvees[0]
            try:
                # Ouvrir directement le .lnk avec os.startfile (pas de terminal)
                os.startfile(app['chemin'])
                # Mémoriser dans le cache
                self.apps_cache[nom_app.lower()] = app['chemin']
                nom = app['nom'].replace('.lnk', '')
                return _v(f"{nom}, c'est parti.", f"J'ouvre {nom}.", f"Je te lance {nom}.")
            except Exception as e:
                return f"Impossible d'ouvrir {app['nom'].replace('.lnk', '')}: {str(e)}"
        
        else:
            # Plusieurs applications trouvées, demander à l'utilisateur
            self.choix_en_attente = nom_app
            self.choix_depuis = time.time()
            self.dernieres_options = apps_trouvees[:5]  # Limiter à 5 options
            
            # Construire un message vocal naturel SANS retours à la ligne
            reponse = f"J'ai trouvé {len(self.dernieres_options)} applications. "
            for i, app in enumerate(self.dernieres_options, 1):
                reponse += f"Option {i} : {app['nom'].replace('.lnk', '')}. "
            reponse += "Dis-moi le numéro de ton choix."
            
            return reponse
    
    def traiter_choix_application(self, commande):
        """Traite le choix de l'utilisateur parmi les applications proposées"""
        if not self.choix_en_attente or not self.dernieres_options:
            self.choix_en_attente = None
            self.dernieres_options = []
            return "Mon signal a sauté : je ne me souviens plus des options. Redemande-moi ça."
        
        # Extraire le numéro du choix (chiffre ou mot : "deux", "troisième"...)
        numero = None
        nombres = re.findall(r'\d+', commande)
        if nombres:
            numero = int(nombres[0])
        else:
            for mot in commande.split():
                if mot in NOMBRES:
                    numero = NOMBRES[mot]
                    break
        
        # Vérifier si le numéro est valide
        if numero and 1 <= numero <= len(self.dernieres_options):
            app_choisie = self.dernieres_options[numero - 1]
            
            try:
                # Ouvrir directement le .lnk avec os.startfile (pas de terminal)
                os.startfile(app_choisie['chemin'])
                # Mémoriser le choix dans le cache
                self.apps_cache[self.choix_en_attente.lower()] = app_choisie['chemin']
                
                # Réinitialiser
                self.choix_en_attente = None
                self.dernieres_options = []
                
                return _v(f"{app_choisie['nom'].replace('.lnk', '')}, excellent choix.", f"J'ouvre {app_choisie['nom'].replace('.lnk', '')}.")
            except Exception as e:
                self.choix_en_attente = None
                self.dernieres_options = []
                return f"Impossible d'ouvrir {app_choisie['nom']}"
        else:
            return f"Dis-moi un numéro entre 1 et {len(self.dernieres_options)}."
    
    def fermer_application(self, commande):
        """Ferme une application"""
        # Extraire le nom de l'application
        mots_cles = ['ferme', 'fermer', 'fermez']
        nom_app = commande
        
        for mot in mots_cles:
            if mot in commande:
                nom_app = commande.split(mot, 1)[1].strip()
                break
        
        if not nom_app:
            return "Quelle application voulez-vous fermer ?"
        
        # Corriger les erreurs de reconnaissance vocale
        nom_app_corrige = self.corriger_texte_reconnu(nom_app)
        
        # Mapping des noms courants vers les processus
        apps_processus = {
            'notepad': 'notepad.exe',
            'bloc-notes': 'notepad.exe',
            'calculatrice': 'CalculatorApp.exe',
            'calculator': 'CalculatorApp.exe',
            'chrome': 'chrome.exe',
            'edge': 'msedge.exe',
            'firefox': 'firefox.exe',
            'word': 'WINWORD.EXE',
            'excel': 'EXCEL.EXE',
            'powerpoint': 'POWERPNT.EXE',
            'outlook': 'OUTLOOK.EXE',
            'discord': 'Discord.exe',
            'spotify': 'Spotify.exe',
            'steam': 'steam.exe',
            'steamwebhelper': 'steamwebhelper.exe',
            'obs': 'obs64.exe',
            'vscode': 'Code.exe',
            'code': 'Code.exe',
            'visual studio code': 'Code.exe',
        }
        
        # Essayer avec le nom corrigé d'abord
        for nom_connu, processus in apps_processus.items():
            if nom_connu in nom_app_corrige.lower():
                try:
                    ferme = False
                    nom_processus_trouve = None
                    for proc in psutil.process_iter(['name']):
                        if proc.info['name'].lower() == processus.lower():
                            proc.kill()
                            ferme = True
                            nom_processus_trouve = proc.info['name']
                    
                    if ferme:
                        return _v(f"{nom_connu} fermé.", f"Je ferme {nom_connu}.")
                    else:
                        return f"{nom_connu} n'est pas ouvert."
                except Exception as e:
                    return f"Impossible de fermer {nom_connu}."
        
        # Recherche floue dans les processus actifs
        try:
            processus_actifs = []
            for proc in psutil.process_iter(['name']):
                nom_proc = proc.info['name'].replace('.exe', '').lower()
                if proc.pid == os.getpid() or proc.info['name'].lower() in PROCESSUS_PROTEGES:
                    continue
                score = self._calculer_score_similarite(nom_app_corrige.lower(), nom_proc)
                
                # Garder seulement les scores significatifs
                if score > 20:
                    processus_actifs.append({
                        'nom': proc.info['name'],
                        'proc': proc,
                        'score': score
                    })
            
            if not processus_actifs:
                return f"Je ne trouve pas l'application {nom_app} parmi celles qui sont ouvertes."
            
            # Trier par score
            processus_actifs.sort(key=lambda x: x['score'], reverse=True)
            
            # Prendre le meilleur match
            meilleur = processus_actifs[0]
            meilleur['proc'].kill()
            nom_affiche = meilleur['nom'].replace('.exe', '')
            return _v(f"{nom_affiche} fermé.", f"Je ferme {nom_affiche}.")
            
        except Exception as e:
            return f"Impossible de fermer {nom_app}: {str(e)}"

    
    def capture_ecran(self, commande):
        """Prend une capture d'écran"""
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            nom_fichier = f"capture_{timestamp}.png"
            chemin = Path.home() / "Pictures" / nom_fichier
            
            screenshot = pyautogui.screenshot()
            screenshot.save(str(chemin))
            
            return _v("Capture faite. Je l'ai rangée dans ton dossier Images.", "Clic, clac : ton écran est dans le dossier Images.")
        except Exception as e:
            return f"Erreur lors de la capture d'écran: {str(e)}"
    
    def eteindre_pc(self, commande):
        """Éteint le PC"""
        try:
            # Donner un avertissement de 10 secondes
            if 'maintenant' in commande or 'immédiat' in commande:
                subprocess.run(['shutdown', '/s', '/t', '0'])
                return "J'éteins le PC immédiatement. À bientôt dans le réseau."
            else:
                subprocess.run(['shutdown', '/s', '/t', '10'])
                self.extinction_depuis = time.time()
                return "J'éteins le PC dans 10 secondes. Dis annule si tu changes d'avis."
        except Exception as e:
            return f"Impossible d'éteindre le PC: {str(e)}"
    
    def flashbang(self, commande):
        """Met la luminosité au maximum"""
        try:
            # Utiliser PowerShell pour mettre la luminosité au max
            ps_command = """
            (Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,100)
            """
            subprocess.run(['powershell', '-Command', ps_command], 
                          capture_output=True, shell=True)
            return "Luminosité au maximum ! Flashbang !"
        except Exception as e:
            # Méthode alternative pour les PC portables
            try:
                # Essayer avec l'API Windows
                import wmi
                c = wmi.WMI(namespace='wmi')
                methods = c.WmiMonitorBrightnessMethods()[0]
                methods.WmiSetBrightness(100, 0)
                return "Luminosité au maximum ! Flashbang !"
            except:
                return "Impossible de modifier la luminosité. Ton PC ne supporte peut-être pas cette fonction."
    
    def verrouiller_session(self, commande):
        """Verrouille la session Windows"""
        try:
            subprocess.run(['rundll32.exe', 'user32.dll,LockWorkStation'])
            return _v("Session verrouillée. Je garde un oeil sur le réseau pendant ton absence.", "Je verrouille la session.")
        except Exception as e:
            return f"Impossible de verrouiller la session: {str(e)}"
