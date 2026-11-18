# Pipeline cours : de l'enregistrement à la fiche de révision

Tu enregistres ton cours sur le PC. Une minute après la fin, tu as dans le dossier du cours
une **fiche complète en Markdown**, rédigée par Claude à partir de la transcription de Mistral, et
reliée à ce que tu as déjà dans ce dossier.

```text
Choix du dossier du cours ─► Enregistrement (micro du PC) ─► Mistral transcrit (pendant le cours)
                                                                     │
        Fiche « Jour 3.md » (+ PDF en option)  ◄─ Claude rédige ◄────┘ (lit les cours précédents)
```

Ce que contient la fiche : résumé, lien avec les cours précédents, notions clés, cours structuré
(exemples, code, schémas), ce que le prof a souligné, questions de révision. La transcription brute
est gardée en `.txt` dans `transcriptions/`. Un exemple est dans [`exemple/fiche_exemple.md`](exemple/fiche_exemple.md).

## Prérequis

| Quoi | Pourquoi | Coût |
|---|---|---|
| **Windows 10/11** avec un micro | enregistrement et automatisation d'Edge | — |
| **Python 3.11+** ([python.org](https://www.python.org/downloads/), cocher « Add to PATH ») | le script | gratuit |
| **ffmpeg** (installé par `installer.bat` via winget) | enregistrement et découpage audio | gratuit |
| **Microsoft Edge** (déjà présent sur Windows) | piloter la page de transcription Mistral | gratuit |
| **Claude Code** avec un abonnement **Claude Pro ou Max** | rédaction des fiches | inclus dans l'abonnement |
| Un **compte Mistral** (console.mistral.ai) | transcription, via la page « Reconnaissance vocale » de Studio | gratuit (quota mensuel) |

Pour installer Claude Code, dans PowerShell : `irm https://claude.ai/install.ps1 | iex`,
puis tape `claude` et connecte-toi.

## Installation

1. Télécharge ou clone ce dépôt où tu veux.
2. Double-clic sur **`installer.bat`**. Il :
   - vérifie Python, installe les paquets (`requests`, `playwright`), ffmpeg si besoin ;
   - vérifie Claude Code et Edge ;
   - crée ta config perso `config.toml` à partir de `config.example.toml` ;
   - ouvre Edge pour que tu te connectes **une fois** à Mistral ;
   - termine par une vérification complète.
3. Ouvre `config.toml` et adapte au moins la liste `matieres`.

Installation manuelle équivalente :

```powershell
pip install -r requirements.txt
python cours.py login
python cours.py verifier
```

Pas besoin de `playwright install` : le script utilise l'Edge déjà installé.

## Utilisation

**Double-clic sur `enregistrer_cours.bat`**, puis :

1. Une fenêtre demande le **dossier du cours** (là où sont tes notes de cette matière).
   Pendant ce temps, Claude, Mistral et le micro sont vérifiés en arrière-plan.
2. L'enregistrement démarre. **Entrée** pour arrêter.
3. « Convertir la fiche en PDF ? (o/N) » : **Entrée** = non.
4. Le script finit la transcription, Claude rédige la fiche, et le terminal affiche :

```text
────────────────────────────────────────────────────────────
✅ Jour 3.md
   📁 C:\...\Réseaux
   📝 TCP ouvre une connexion par le three-way handshake (SYN, SYN-ACK, ACK).
   ➕ complété : Jour 2.md
────────────────────────────────────────────────────────────
```

5. **Entrée** pour fermer.

Autres commandes :

| Commande | Rôle |
|---|---|
| `python cours.py traiter audio.m4a -d "C:\chemin\du\cours"` | traiter un audio existant (téléphone, etc.) |
| `python cours.py verifier` | vérifier que Claude, Mistral et le micro sont prêts |
| `python cours.py login` | se reconnecter à Mistral |
| `lancer_surveillance.bat` | traiter automatiquement tout audio déposé dans `inbox/` |

## Ce qui se passe en détail

**Pendant l'enregistrement**
- L'audio est découpé en morceaux de 30 min ; chaque morceau terminé est **transcrit tout de suite**
  par Mistral en arrière-plan. À la fin, il ne reste que le dernier morceau : la fiche arrive vite.
  Claude n'est appelé qu'une fois, à la fin.
- **Micro coupé** : vérifié avant de commencer, puis alerte (avec bip) après 15 s de silence total.

**La fiche**
- Claude lit le dossier du cours (fiches précédentes, notes, PDF) pour faire le lien avec ce qui a déjà
  été vu, garder le même vocabulaire, et peut **compléter** un cours existant.
- Le **nom du fichier** suit la convention du dossier : `Jour 1`, `Jour 2` → `Jour 3` ; `CM3 - …` → `CM4 - …`.
  Sinon : `AAAA-MM-JJ - Titre`.
- Format compatible **md2pdf** (Pandoc + XeLaTeX) : voir [`prompts/standard_md2pdf.md`](prompts/standard_md2pdf.md).
  Les champs `author`, `school`, `professor`… sont repris des fiches déjà présentes dans le dossier.

**Rien n'est jamais supprimé ni modifié dans ton dossier de cours**, et c'est garanti par le code :
- Claude n'a que des outils de lecture (pas d'écriture, pas de commandes) ;
- la fiche et la transcription sont de **nouveaux** fichiers (jamais d'écrasement : `(2)` si le nom existe) ;
- un complément est **ajouté à la fin** d'un `.md`/`.txt` (copie de sauvegarde dans `sauvegardes/` avant) ;
  pour un Word/PDF, il va dans un nouveau fichier `… - complément <date>.md`.

**Après le traitement** : l'audio est supprimé pour ne pas prendre de place (`garder_audio = true` pour le garder).
En cas d'erreur, l'audio est conservé et la commande pour relancer est affichée.

## Configuration (`config.toml`)

| Réglage | Rôle |
|---|---|
| `matieres` | tes matières (utilisées quand aucun dossier n'est choisi) |
| `transcription` | `"web"` (page Mistral, gratuit) ou `"api"` (clé payante, ~0,21 $/h de cours) |
| `navigateur_visible` | `true` pour voir Edge travailler (débogage) |
| `garder_audio` | garder les enregistrements après traitement |
| `duree_segment_min` | taille des morceaux transcrits pendant le cours (30 par défaut) |
| `md2pdf_script`, `md2pdf_mode`, `md2pdf_theme` | conversion PDF optionnelle avec un convertisseur md2pdf |
| `claude_model` | modèle Claude (vide = celui de ton abonnement) |
| `dossiers_entree`, `emploi_du_temps` | mode surveillance (`inbox/`, dossier Google Drive…) |

Le format des fiches se change dans [`prompts/notes.md`](prompts/notes.md),
et ce que Claude fait du dossier de cours dans [`prompts/contexte_dossier.md`](prompts/contexte_dossier.md).

## Enregistrer avec le téléphone

Avec **Google Drive pour ordinateur**, ajoute le dossier Drive synchronisé à `dossiers_entree`
(ex. `["inbox", "G:/Mon Drive/Cours-Inbox"]`), envoie l'audio du téléphone dans ce dossier,
et laisse tourner `lancer_surveillance.bat`. Ou traite le fichier à la main avec `python cours.py traiter`.

## En cas d'erreur

Les problèmes sont détectés **avant** d'enregistrer (pendant le choix du dossier) :

```text
Vérifications :
  ✅ Claude : connecté et opérationnel
  ❌ Mistral : Tu n'es plus connecté à Mistral.
   → lance :  python cours.py login
  ✅ Micro : OK, il capte du son (-23 dB)
```

| Message | Que faire |
|---|---|
| Claude n'est plus connecté | `claude` puis `/login` dans un terminal |
| Limite d'utilisation Claude atteinte | attendre, puis relancer la commande affichée |
| Tu n'es plus connecté à Mistral | `python cours.py login` |
| Mistral refuse… quota gratuit épuisé | attendre le mois suivant, ou `transcription = "api"` |
| La page de Mistral ne ressemble plus à ce qui est prévu | Mistral a modifié son site : capture d'écran dans `erreurs/` ; le sélecteur est à adapter dans `mistral_web.py` |
| Le micro ne capte aucun son | touche muet du PC, ou micro désactivé dans les paramètres son de Windows |
| Erreur inattendue | détail complet dans `erreurs/derniere_erreur.txt` |

## Confidentialité et limites

- **`.navigateur/`** contient ta session Mistral connectée : ne le partage jamais (il est dans `.gitignore`).
  `config.toml` (ta config, éventuelle clé API) et tes enregistrements/transcriptions ne sont pas versionnés non plus.
- La transcription « web » automatise l'interface de Mistral Studio : ce n'est sans doute pas prévu
  par leurs conditions d'utilisation. Usage personnel et modéré ; le mode `"api"` est l'alternative officielle.
- Si Mistral modifie sa page, la transcription web peut casser (le message d'erreur le signale).
- Le micro d'un PC portable capte le prof faiblement : pour une meilleure transcription, rapproche le PC
  (ou enregistre au téléphone posé près du prof). Un filtre audio a été testé et n'aide pas.
- Windows uniquement (enregistrement DirectShow, Edge, fichiers `.bat`).

## Structure du projet

```text
cours.py              pipeline : enregistrement, vérifications, transcription, Claude, écriture des fiches
mistral_web.py        pilotage de la page « Reconnaissance vocale » de Mistral Studio
config.example.toml   modèle de configuration (copié en config.toml au premier lancement)
prompts/              consignes données à Claude (fiche, dossier de contexte, standard md2pdf)
installer.bat         installation guidée
enregistrer_cours.bat enregistrer un cours
lancer_surveillance.bat traiter automatiquement les audios déposés dans inbox/
exemple/              exemple de fiche générée
```
