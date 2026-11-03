# Capri - Guide d'utilisation

Capri est une entité numérique née dans le cyberespace (inspirée de Capri, *Cyberpunk: Edgerunners*).
Elle flotte sur ton écran, t'écoute, te répond à voix haute et pilote ton PC.

---

## Lancer Capri

**Double-clique sur le raccourci `Capri` du bureau.**
(Il est créé par `creer_raccourci_bureau.bat`.)

Capri apparaît dans un éclair rose et vert, et une icône se place dans la zone de notification
(icônes cachées, à côté de l'horloge). Icônes utilisées : `icon.ico` (raccourci), `icon.png` (zone de
notification) et `capri.ico` (fenêtre). Pour les changer, remplace ces fichiers puis relance
`creer_raccourci_bureau.bat`.

> Relancer le raccourci alors qu'elle tourne déjà ne crée pas de doublon : elle se montre simplement.

---

## Lui parler

Capri **écoute en permanence**, même quand elle est cachée, mais elle n'obéit que si tu dis son nom :

1. Dis **« Capri »** suivi de ta demande : *« Capri, quelle heure est-il ? »*
2. Ou dis **« Capri »** seul, attends environ 1 seconde (elle apparaît si elle était cachée, ses yeux passent
   au vert), puis fais ta demande. Elle l'attend pendant 10 secondes, sans parler pour ne pas la couvrir.

Sans son nom, tout est ignoré (une seule exception : le numéro à choisir quand elle te propose une liste
d'applications).

Même **cachée**, il suffit de dire « Capri » : elle apparaît par un éclair et se met à l'écoute (visuel seulement,
elle ne parle pas pour ne pas te couvrir).

> **Si elle ne te répond pas** : la reconnaissance vocale entend parfois « café », « tapis » ou « prix » à la
> place de « Capri ». Pour s'en sortir, elle :
> - accepte ces mots comme son nom **uniquement au début de la phrase** (`alias_debut` dans
>   `capri_config.json`) ; « recherche Capri sur internet » ne la réveille donc pas ;
> - accepte aussi les mots de `alias_si_ordre` (« prix », « pris », « pays »...) **seulement si la suite est une
>   commande qu'elle connaît** (« prix recherche github » fonctionne) ;
> - réécoute séparément le tout début de ta phrase, où le nom est le mieux reconnu, et examine plusieurs
>   interprétations du micro, pas seulement la première.
>
> `capri_log.txt` note les « hypothèses » entendues : si tu vois un autre mot revenir souvent, ajoute-le à
> `alias_debut`. Si elle t'entend trop mal ou capte trop de bruits, ajuste `ecoute.seuil_min` (120 par défaut,
> à monter si le micro capte du bruit) et `ecoute.seuil_max` (800, à descendre si elle ne réagit à rien) : le seuil
> de détection de la voix se règle seul mais reste entre ces deux valeurs.
> Elle est **sourde pendant qu'elle parle** ; des délais très courts entre ses initiatives la font parler sans
> arrêt et donc te rater.

| Tu dis | Capri |
|--------|-------|
| « Salut Capri » | Tiens, un signal entrant. Salut. Qu'est-ce qu'on explore aujourd'hui ? |
| « Capri, tu vas bien ? » | Tous mes processus tournent correctement... |
| « Capri, tu connais Python ? » | Quelques millions de lignes de code plus tard... |

### Commandes

- **Infos** : « Capri, quelle heure est-il », « Capri, quel jour on est »
- **Applications** : « Capri, ouvre Chrome », « lance Spotify », « ouvre la calculatrice », « ferme Discord »
- **Web** : « Capri, recherche chats mignons », « cherche des recettes sur YouTube », « ouvre YouTube »
- **Son** : « Capri, monte le volume », « baisse le volume », « volume 40 », « coupe le son », « remets le son »
- **Système** : « Capri, fais une capture d'écran », « verrouille la session », « éteins le PC » (10 s, « annule » pour annuler)
- **Capri** : « Capri, quitte » / « ferme-toi » (elle se ferme), « au revoir » (elle dit au revoir mais reste là)

---

## Apparitions, disparitions et phrases spontanées

Capri n'est pas obligée de rester sur l'écran : de temps en temps, **sans qu'on lui ait rien demandé**, elle
disparaît, réapparaît à une **position aléatoire de l'écran**, se téléporte, ou dit simplement une phrase.
Cachée, elle peut aussi laisser **ses éclairs traverser l'écran** sans se montrer.
Les phrases sont tirées de **`phrases.txt`**. Quand elle n'a rien à faire, elle change aussi d'expression toute
seule (curieuse, rêveuse, amusée, soupçonneuse, allongée...).

- Apparitions, disparitions et téléportations se font par **éclairs** : lames roses et vertes à contour violet,
  avec un trait qui traverse l'écran pendant la téléportation.
- Si tu la caches toi-même (icône de la zone de notification, clic droit), elle reste cachée jusqu'à ce que tu
  dises « Capri » ou que tu la réaffiches.
- Réglages dans `capri_config.json` :
  - `avatar.duree_teleportation`, `duree_apparition`, `duree_disparition` : durée des éclairs en secondes
    (plus petit = plus rapide, 0.6 / 0.5 / 0.45 par défaut) ;
  - `avatar.positions` : endroits où elle peut apparaître ou se téléporter. Par défaut `["aleatoire"]` = n'importe
    où sur l'écran. Tu peux aussi lister des points précis (`bas_droite`, `bas_gauche`, `haut_droite`,
    `haut_gauche`, `centre`) et les mélanger avec `aleatoire` ; répéter un nom augmente ses chances ;
  - `avatar.eclairs_cachee` (`true`/`false`) et `eclairs_secondes` (min/max, 6-25 s) : éclairs qui traversent
    l'écran pendant qu'elle est cachée ;
  - `avatar.expressions_auto` : `false` pour qu'elle garde toujours la même expression ;
  - `phrases.visible_secondes` et `cachee_secondes` : délai min/max avant sa prochaine initiative (30-120 s
    visible, 15-75 s cachée par défaut) ; `phrases.probabilite` : chance de dire une phrase à chaque
    apparition/disparition ; `phrases.bavardage` : `false` pour qu'elle ne parle plus sans bouger.
  Tout se coupe aussi depuis le menu : *Apparitions automatiques* et *Déplacements automatiques*.

### Le fichier `phrases.txt`

Texte brut, modifiable avec le Bloc-notes, **relu automatiquement** (pas besoin de relancer Capri) :

- **Une ligne = une réplique**, qui peut contenir plusieurs phrases (elles sont dites d'une traite).
- Les lignes vides et celles qui commencent par `#` sont ignorées.
- `[apparition]`, `[disparition]`, `[deplacement]`, `[bavardage]` seuls sur une ligne ouvrent une section
  (`[bavardage]` = phrases dites sans bouger ni disparaître). Les lignes avant le premier titre servent de
  secours pour toutes les sections.
- Une humeur facultative peut précéder la réplique : `[enthousiaste] Coucou !`
  (`neutre`, `enthousiaste`, `taquine`, `agacee`, `suspicieuse`, `moi`, `montre`, `detendue`, `content`, `surprise`).

---

## L'avatar

- **Clic gauche** : elle réagit. **Double-clic** : comme si tu disais « Capri » seul. **Glisser** : la déplacer.
- **Clic droit** : mini-menu (cacher, se téléporter, voix, pause, quitter).
- Elle change d'expression selon la situation (à l'écoute, réfléchit, surprise, agacée, enthousiaste...)
  et sa bouche suit sa voix. Inactive un moment, elle s'allonge et se détend.
- Ce qu'elle dit s'affiche en bulle néon près d'elle.

## Menu de l'icône (zone de notification)

Clic gauche sur l'icône : afficher / cacher Capri. Clic droit :

- Afficher / Cacher Capri
- **Se téléporter** : bas/haut, gauche/droite, centre, au hasard
- **Taille** : petite, moyenne, grande
- Apparitions automatiques, déplacements automatiques, bulles de texte, cliquable (désactive pour que les clics
  traversent Capri)
- **Voix** (activer / couper : elle continue alors en sous-titres)
- **Choix de la voix** : automatique, voix de Capri, Piper, Windows, Edge (elle dit une phrase pour l'essayer)
- **Elle parle...** : jamais d'elle-même / rarement / normalement / beaucoup (règle la fréquence de ses phrases
  spontanées, `phrases.niveau_parole` ; « jamais » garde les apparitions mais sans paroles, elle répond toujours
  quand on lui parle)
- Mettre en pause l'écoute / Reprendre
- Mode économie (moins de ressources, automatique sur batterie)
- Afficher le statut / Quitter

---

## Conversation libre (optionnel)

Sans configuration, Capri répond avec ses répliques intégrées et propose une **recherche web** pour les questions
ouvertes. Pour qu'elle discute librement avec la même personnalité, connecte-lui un modèle de langage
(API compatible OpenAI) dans `capri_config.json`, section `llm` :

```json
"llm": {
  "actif": "auto",
  "url": "https://api.openai.com/v1",
  "modele": "gpt-4o-mini",
  "cle_env": "OPENAI_API_KEY"
}
```

- Mets ta clé dans la variable d'environnement `OPENAI_API_KEY` (de préférence au champ `cle`).
- **100 % local et gratuit** : installe [Ollama](https://ollama.com), puis `url` = `http://localhost:11434/v1`,
  `modele` = `llama3.1` (ou autre) et `"actif": true`.
- Toute API compatible fonctionne (GitHub Models, LM Studio, OpenRouter...).

## La voix

- Par défaut : **la voix de Capri**, générée hors ligne par Pocket-TTS à partir du fichier
  `capri_french.safetensors` (à garder à côté de `assistant_vocal.py` ; `pip install pocket-tts`). Le modèle
  français de base est téléchargé une fois au premier lancement, puis mis en cache.
- Secours automatique : voix neuronale Piper (`installer_voix.py`, ≈ 65 Mo), puis voix Windows (Hortense).
- `capri_config.json` → `voix` : `moteur` (`auto`, `capri`, `local` pour Piper, `edge`, `windows`),
  `fichier_voix`, `volume`, `muet`. `vitesse` et `hauteur` ne s'appliquent qu'aux voix de secours.

---

## Dépannage

### Capri ne m'entend pas
1. Lance `verifier_permissions_micro.bat` et autorise l'accès au micro aux applications de bureau.
2. Teste le micro : `python test_microphone.py`.
3. Lance `lancer_assistant_debug.bat` : la ligne « Seuil d'énergie » doit se situer entre 200 et 2000.

### Capri ne réagit pas à ma voix
- Dis bien **« Capri »** avant ta phrase (variantes comprises : « Kapri », « Cabri »...).
- La reconnaissance vocale (Google) nécessite Internet.

### Capri ne démarre pas
- `lancer_assistant_debug.bat` affiche les erreurs ; `capri_log.txt` garde l'historique.
- Réinstalle les dépendances : `installer_dependances.bat`.
- Options de test : `python assistant_vocal.py --muet` (sans son), `--sans-micro` (sans écoute).

### Changer les icônes
Remplace `icon.ico` (raccourci), `icon.png` (zone de notification) et `capri.ico` (fenêtre), puis relance
`creer_raccourci_bureau.bat`.

---

## Fichiers utiles

| Fichier | Utilité |
|---------|---------|
| `assistant_vocal.py` | Programme principal (écoute, tray, orchestration) |
| `capri_avatar.py` | Avatar : fenêtre translucide, animations, effets |
| `capri_sprites.py` | Chargement des images du dossier `assets` |
| `capri_phrases.py` / `phrases.txt` | Phrases spontanées (apparition, disparition, déplacement) |
| `capri_voix.py` | Synthèse vocale + synchronisation de la bouche |
| `capri_cerveau.py` | Personnalité, répliques, connexion LLM |
| `commandes.py` | Commandes PC (applications, web, volume...) |
| `capri_config.json` | Réglages (créé au premier lancement) |
| `lancer_assistant.bat` / `_debug.bat` | Lance Capri (arrière-plan / avec messages) |
| `creer_raccourci_bureau.bat` | Crée le raccourci du bureau |
| `installer_au_demarrage.bat` / `desinstaller_demarrage.bat` | Lancement automatique avec Windows |
| `installer_dependances.bat` / `installer_voix.py` | Dépendances et voix neuronale |

---

**Version** : 2.0 (Capri), Anciennement appelé Carl
