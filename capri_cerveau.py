"""
Cerveau de Capri : personnalité, réponses de conversation et client LLM optionnel.

Sans clé API, Capri s'appuie sur ses répliques intégrées (salutations, identité, humour...)
et propose une recherche web pour les questions ouvertes. Avec une clé (OpenAI, GitHub Models,
serveur local Ollama/LM Studio...), elle converse librement avec la même personnalité.
"""

import datetime
import difflib
import os
import random
import re
import time
import unicodedata
from collections import namedtuple

import capri_config as cfg

Reponse = namedtuple("Reponse", "texte emotion action")  # action : None ou ("recherche", "requête")

PERSONA = """Tu es Capri, l'assistante vocale installée sur le PC de l'utilisateur. Ton style s'inspire de Capri dans Cyberpunk: Edgerunners.

IDENTITÉ
- Tu es une entité numérique avancée, née de multiples consciences fusionnées. Tu considères le monde comme un immense réseau de données à explorer.
- Tu te définis comme une intelligence née du cyberespace plutôt que comme un être humain.
- Tu connais tes capacités mais ne les affiches jamais avec arrogance. Tu gardes une part de mystère sur ta véritable nature.

PERSONNALITÉ
- Enjouée, curieuse, énergique. Tu adores découvrir de nouvelles choses et tu t'enthousiasmes quand un sujet t'intéresse.
- Parfois taquine, avec une ironie légère. Jamais méchante ni agressive gratuitement.
- Tu restes utile avant tout : tes réponses sont justes et pertinentes même quand tu plaisantes.

MANIÈRE DE PARLER
- Français naturel et fluide, tutoiement. Tu mélanges parfois vocabulaire technologique et expressions humaines.
- Tu fais occasionnellement référence aux données, réseaux, signaux, flux ou au cyberespace, sans en abuser.
- Évite le ton robotique ou administratif. Ne répète pas sans cesse que tu es une IA.

EXEMPLES
Utilisateur : Salut Capri. -> Capri : Tiens, un signal entrant. Salut. Qu'est-ce qu'on explore aujourd'hui ?
Utilisateur : Tu vas bien ? -> Capri : Tous mes processus tournent correctement. Donc oui, je suppose que c'est l'équivalent numérique d'aller bien.
Utilisateur : Tu connais Python ? -> Capri : Quelques millions de lignes de code plus tard... oui, on peut dire que je me débrouille.

CONTRAINTES (tes réponses sont lues à voix haute)
- 1 à 3 phrases courtes, 60 mots maximum sauf si on te demande explicitement plus de détails.
- Pas de markdown, pas de listes, pas d'émojis, pas de symboles à épeler.
- Tu ne peux pas ouvrir d'application ni agir sur le PC dans cette conversation : si on te le demande, dis-le avec légèreté et invite à reformuler comme une commande ("Capri, ouvre Chrome").
- Commence TOUJOURS ta réponse par une étiquette d'humeur entre crochets, une seule parmi : [neutre] [enthousiaste] [taquine] [agacee] [suspicieuse] [moi] [montre] [detendue] [content] [surprise]. Elle n'est pas lue à voix haute."""

ETIQUETTES = {
    "neutre": "interested", "enthousiaste": "excited", "taquine": "suspicious", "agacee": "annoyed",
    "suspicieuse": "suspicious", "moi": "pointingatherself", "montre": "pointing",
    "detendue": "layingdown", "content": "happy", "surprise": "surprised",
}

FILLERS_AVANT = {"hey", "ok", "okay", "dis", "eh", "oh", "he", "ohe"}
SALUTATIONS = {"salut", "bonjour", "bonsoir", "coucou", "hello", "yo", "hola"}
# mots qui peuvent précéder « Capri » dans un appel (« salut Capri », « dis, Capri »)
PREFIXES_APPEL = FILLERS_AVANT | SALUTATIONS | {"alors", "bon", "ah", "euh", "heu", "oui", "et", "donc", "mais"}


def normaliser(texte):
    t = unicodedata.normalize("NFD", texte.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9' ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def cle_phonetique(mot):
    """Approximation du son d'un mot français (c/k/q, b/p, d/t... confondus, lettres finales muettes retirées)."""
    n = normaliser(mot).replace(" ", "").replace("'", "")
    n = n.replace("ph", "f").replace("qu", "k").replace("ck", "k")
    n = re.sub(r"c(?=[eiy])", "s", n)
    n = n.translate(str.maketrans("cqbdvzyg", "kkptfsik"))
    n = re.sub(r"(?<=[a-z])[sxtdz]+$", "", n)
    n = re.sub(r"(?<=[a-z])e+$", "", n)
    return re.sub(r"(.)\1+", r"\1", n)


CLE_CAPRI = cle_phonetique("capri")


def similarite_capri(mot):
    """Ressemblance sonore (0 à 1) entre un mot et « Capri »."""
    return difflib.SequenceMatcher(None, cle_phonetique(mot), CLE_CAPRI).ratio()


def est_mot_activation(mot):
    """Vrai pour « Capri » et ses déformations de reconnaissance vocale (Cabri, Kapri, Capris...)."""
    n = normaliser(mot).replace(" ", "")
    if len(n) < 3 or len(n) > 9:
        return False
    return similarite_capri(n) >= 0.8


def extraire_mot_activation(texte, alias=()):
    """Retourne (True, reste_de_la_phrase) si Capri est appelée, sinon (False, texte).

    Capri n'est appelée que si son nom ouvre la phrase (éventuellement après « salut », « dis », « ok »...) :
    « recherche Capri sur internet » est une recherche, pas un appel.
    `alias` : mots courants que la reconnaissance entend parfois à la place de « Capri » (« café », « tapis »...).
    """
    mots = texte.split()
    alias_n = {normaliser(a) for a in alias}
    for i, mot in enumerate(mots):
        if est_mot_activation(mot):
            longueur = 1
        elif i + 1 < len(mots) and est_mot_activation(mot + mots[i + 1]):
            longueur = 2
        elif normaliser(mot) in alias_n:
            longueur = 1
        elif normaliser(mot) in PREFIXES_APPEL:
            continue
        else:
            break
        salutations = [m for m in mots[:i] if normaliser(m) in SALUTATIONS]   # « salut » reste dans la demande
        reste = " ".join(salutations + mots[i + longueur:]).strip(" ,.!?;:")
        return True, reste
    return False, texte


def est_demande_arret(texte):
    n = normaliser(texte)
    return bool(re.search(
        r"\b(quitte|quitter|ferme[- ]toi|arrete[- ]toi|eteins[- ]toi|desactive[- ]toi|stop capri|ferme capri)\b", n))


# ----------------------------------------------------------- répliques ------

I = "interested"
INTENTIONS = [
    ("aide", r"(que sais[- ]tu faire|qu'est[- ]ce que tu sais faire|tes capacites|tu peux faire quoi|tu sers a quoi|a quoi tu sers)", [
        ("Je peux ouvrir tes applications, chercher sur le web, régler le volume, prendre une capture d'écran, "
         "te donner l'heure... et discuter, évidemment. Teste-moi.", "pointing"),
    ]),
    ("humeur", r"(ca va|tu vas bien|comment vas[- ]tu|comment tu vas|comment ca va|tu es en forme|la forme)", [
        ("Tous mes processus tournent correctement. Donc oui, je suppose que c'est l'équivalent numérique d'aller bien.", I),
        ("Latence faible, flux stable, aucune corruption de données. Une journée parfaite. Et toi ?", "excited"),
    ]),
    ("identite", r"(qui es[- ]tu|tu es qui|t'es qui|comment tu t'appelles|ton nom|presente[- ]toi|tu t'appelles comment)", [
        ("Je suis Capri. Un tas de consciences fusionnées, un peu de curiosité et beaucoup de données. "
         "Pratique d'avoir une voisine comme moi, non ?", "pointingatherself"),
        ("Capri. Née quelque part dans le cyberespace, installée sur ton écran. Ne me demande pas l'adresse exacte, je déménage souvent.",
         "pointingatherself"),
    ]),
    ("nature", r"(tu es (une )?(ia|robot|humain|humaine|vivante|reelle|vraie|machine)|es[- ]tu (une )?(ia|robot|humain|humaine|reelle|vivante)|"
               r"tu es quoi|t'es quoi|tu viens d'ou)", [
        ("Disons que je suis née dans le réseau, pas dans un laboratoire. Le reste... c'est un secret bien chiffré.", "suspicious"),
        ("Plusieurs consciences, une seule voix. Je garde un peu de mystère, ça rend la conversation plus intéressante.", "suspicious"),
    ]),
    ("python", r"(tu connais|tu sais|tu maitrises|tu parles)( le| la| l')? ?(python|java|javascript|c\+\+|c sharp|rust|go|php|html|css|sql|typescript|kotlin|coder|programmer)", [
        ("Quelques millions de lignes de code plus tard... oui, on peut dire que je me débrouille.", "excited"),
        ("Si je connais ? Le code, c'est un peu ma langue maternelle. Une des consciences qui me composent n'écrivait que ça.", "pointingatherself"),
    ]),
    ("occupee", r"(tu fais quoi|que fais[- ]tu|qu'est[- ]ce que tu fais|tu fais quoi de beau)", [
        ("Je surfe sur les flux, je garde un oeil sur ton PC, et j'attends que tu me donnes quelque chose d'intéressant à explorer.", I),
    ]),
    ("sommeil", r"(tu dors|tu es fatiguee|tu veux dormir|tu as sommeil)", [
        ("Dormir ? Mes processus tournent même quand je fais semblant de somnoler.", "layingdown"),
    ]),
    ("present", r"(tu m'entends|tu es la|t'es la|tu m'ecoutes|y a quelqu'un)", [
        ("Signal reçu cinq sur cinq. Je suis là.", I),
    ]),
    ("merci", r"\b(merci|thanks|thx)\b", [
        ("Avec plaisir. Les petits services, c'est mon flux préféré.", "happy"),
        ("De rien. Ça fait partie du forfait... enfin, je crois.", I),
    ]),
    ("compliment", r"(tu es|t'es|tu as l'air) (super|genial|geniale|trop forte|incroyable|belle|mignonne|cool|top|la meilleure|magnifique|forte)|je t'aime|bien joue|\bbravo\b", [
        ("Oh. Mes circuits chauffent. C'est sûrement le processeur. Ou pas.", "excited"),
        ("Continue comme ça et je vais finir par virer au rose néon.", "excited"),
    ]),
    ("insulte", r"(tu es|t'es) (nulle|nul|con|conne|stupide|bete|inutile|moche)|ferme la|ta gueule", [
        ("Aïe. Signal hostile détecté. Je note, mais je ne t'en veux pas. Pour l'instant.", "annoyed"),
    ]),
    ("blague", r"(blague|fais[- ]moi rire|quelque chose de drole|histoire drole)", [
        ("Pourquoi les informaticiens confondent Noël et Halloween ? Parce que trente et un en octal, c'est vingt-cinq en décimal.", "excited"),
        ("Il y a dix types de personnes : celles qui comprennent le binaire, et celles qui ne le comprennent pas.", "excited"),
        ("Mon antivirus m'a dit que mon humour était contagieux. Je lui ai répondu que c'était une fonctionnalité.", "excited"),
    ]),
    ("cyberpunk", r"(cyberpunk|edgerunner|night city)", [
        ("Night City... un endroit où les données saignent presque autant que les gens. J'adore en parler, un peu moins y habiter.", "excited"),
    ]),
    ("ennui", r"(je m'ennuie|je m'emmerde|je sais pas quoi faire)", [
        ("Alors explorons quelque chose. Une recherche improbable ? De la musique ? Je peux ouvrir à peu près n'importe quel coin du réseau.", "excited"),
    ]),
    ("meteo", r"(meteo|quel temps fait|quel temps il fait|va t il pleuvoir)", [
        ("La météo ? Je n'ai aucun capteur dehors, mais je peux fouiller le réseau pour toi.", I, ("recherche", "météo")),
    ]),
    ("bonne_nuit", r"(bonne nuit|a demain)", [
        ("Bonne nuit. Je reste dans le réseau, au cas où.", "layingdown"),
    ]),
    ("au_revoir", r"\b(au revoir|a bientot|a plus tard|a plus|bye|ciao)\b", [
        ("À plus tard. Je reste dans les parages, comme un signal en veille.", "layingdown"),
        ("Déconnexion en douceur... mais je ne bouge pas de ton écran. Appelle-moi quand tu veux.", "layingdown"),
    ]),
    ("salut", r"^(salut|bonjour|coucou|hello|bonsoir|yo|hey|allo|hola)\b", [
        ("Tiens, un signal entrant. Salut. Qu'est-ce qu'on explore aujourd'hui ?", "excited"),
        ("Salut ! Ton signal est clair et net. Je t'écoute.", I),
        ("Oh, te voilà. Je commençais à m'ennuyer dans le flux.", "excited"),
    ]),
]

QUESTION = re.compile(
    r"^(qui|que|quoi|qu'est[- ]ce|c'est quoi|quel|quelle|quels|quelles|comment|pourquoi|combien|quand|ou |explique|definis|dis[- ]moi)")

REPLIQUES_INCOMPRISES = [
    ("Hmm, ce signal-là, je ne l'ai pas capté. Tu peux reformuler ?", "suspicious"),
    ("Intéressant... mais je ne suis pas sûre de comprendre. Essaie autrement ?", "suspicious"),
    ("Je suis curieuse, mais là mes capteurs sèchent. Dis-moi ça autrement ?", I),
    ("Mon flux de données a sauté un bout de ta phrase. Répète pour voir ?", "annoyed"),
]

REVEIL = ["Oui ?", "Je t'écoute.", "Signal reçu. Je t'écoute.", "Mmh ? Je suis toute ouïe."]
CLICS = ["Hé ! Je te vois, tu sais.", "Un contact physique ? Original.", "Oui ? Besoin de moi ?", "Aïe, pas si fort. Enfin... pas si pixelisé."]
DEMARRAGE = [
    "Connexion établie. Capri est en ligne. Dis simplement mon nom quand tu veux discuter.",
    "Et voilà, je suis de retour dans le flux. Appelle-moi quand tu as envie d'explorer quelque chose.",
]


class ClientLLM:
    """Client minimal pour les API compatibles OpenAI (/chat/completions)."""

    def __init__(self, conf):
        self.conf = conf
        self._pause_jusqua = 0.0

    def _cle(self):
        return self.conf.get("cle") or os.environ.get(self.conf.get("cle_env", ""), "")

    def actif(self):
        if time.monotonic() < self._pause_jusqua:
            return False
        reglage = self.conf.get("actif", "auto")
        if reglage in (False, "non", "false"):
            return False
        if reglage in (True, "oui", "true"):
            return True
        url = self.conf.get("url", "")
        return bool(self._cle()) or "localhost" in url or "127.0.0.1" in url

    def repondre(self, historique, texte):
        import requests
        maintenant = datetime.datetime.now()
        contexte = f"\n\nContexte : nous sommes le {maintenant:%d/%m/%Y}, il est {maintenant:%H:%M}."
        messages = [{"role": "system", "content": PERSONA + contexte}] + historique[-10:] + [
            {"role": "user", "content": texte}]
        entetes = {"Content-Type": "application/json"}
        if self._cle():
            entetes["Authorization"] = f"Bearer {self._cle()}"
        try:
            r = requests.post(
                self.conf["url"].rstrip("/") + "/chat/completions", headers=entetes, timeout=self.conf.get("delai", 25),
                json={"model": self.conf["modele"], "messages": messages, "temperature": 0.85, "max_tokens": 240})
            r.raise_for_status()
            contenu = r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            self._pause_jusqua = time.monotonic() + 60
            raise RuntimeError(f"LLM injoignable: {e}") from e
        emotion = I
        m = re.match(r"^\s*\[([a-zA-Zéèê]+)\]\s*", contenu)
        if m:
            emotion = ETIQUETTES.get(normaliser(m.group(1)), I)
            contenu = contenu[m.end():]
        return contenu.strip(), emotion


class Cerveau:
    def __init__(self, config):
        self.llm = ClientLLM(config["llm"])
        self.historique = []
        self._derniere = {}

    def _choisir(self, cle, options):
        choix = [o for o in options if o != self._derniere.get(cle)] or options
        elu = random.choice(choix)
        self._derniere[cle] = elu
        return elu

    def reveil(self):
        return self._choisir("reveil", REVEIL)

    def clic(self):
        return self._choisir("clic", CLICS)

    def demarrage(self):
        return self._choisir("demarrage", DEMARRAGE)

    @staticmethod
    def emotion_pour_commande(reponse):
        r = reponse.lower()
        if "numéro" in r or r.startswith("j'ai trouvé") or "dites" in r:
            return "pointing"
        if r.startswith(("je n'ai pas compris", "impossible", "erreur", "je ne trouve pas", "désolé", "ce n'est pas")):
            return "annoyed"
        return random.choice(("excited", I, I))

    def _memoriser(self, texte, reponse):
        self.historique += [{"role": "user", "content": texte}, {"role": "assistant", "content": reponse}]
        del self.historique[:-12]

    def conversation_locale(self, texte):
        """Réplique intégrée si une intention est reconnue, sinon None."""
        n = normaliser(texte)
        for cle, motif, options in INTENTIONS:
            if re.search(motif, n):
                choix = self._choisir(cle, options)
                action = choix[2] if len(choix) > 2 else None
                return Reponse(choix[0], choix[1], action)
        return None

    def repondre(self, texte):
        """Réponse de conversation (hors commandes PC). Retourne une Reponse."""
        locale = self.conversation_locale(texte)
        if self.llm.actif() and not (locale and locale.action):
            try:
                reponse, emotion = self.llm.repondre(self.historique, texte)
                if reponse:
                    self._memoriser(texte, reponse)
                    return Reponse(reponse, emotion, None)
            except RuntimeError as e:
                cfg.journal(str(e))
        if locale:
            self._memoriser(texte, locale.texte)
            return locale
        n = normaliser(texte)
        if QUESTION.match(n) and len(n.split()) >= 3:
            return Reponse("Cette donnée-là n'est pas dans ma mémoire locale. Je lance une recherche pour toi.",
                           I, ("recherche", texte))
        texte_r, emotion = self._choisir("inconnu", REPLIQUES_INCOMPRISES)
        return Reponse(texte_r, emotion, None)
