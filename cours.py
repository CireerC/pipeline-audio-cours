"""Pipeline cours : audio -> transcription Mistral (Voxtral) -> fiche de cours Claude -> Markdown.

Usage :
    python cours.py watch                      surveille les dossiers d'entrée et traite tout seul
    python cours.py traiter FICHIER [-m MAT]   traite un fichier audio précis
    python cours.py rec [-d DOSSIER]           choisit le dossier du cours, enregistre (Entrée pour arrêter) puis traite
    python cours.py login                      connexion (une fois) à Mistral dans le Edge dédié
    python cours.py verifier                   vérifie que Claude, Mistral et le micro sont prêts
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import threading
import traceback
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

import os

import requests

ROOT = Path(__file__).resolve().parent
AUDIO_EXT = {".m4a", ".mp3", ".wav", ".ogg", ".opus", ".aac", ".flac", ".webm",
             ".mp4", ".3gp", ".amr", ".mkv", ".mov", ".wma"}
SUPPORT_EXT = (".pdf", ".txt", ".md")
MISTRAL_URL = "https://api.mistral.ai/v1/audio/transcriptions"

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


class PipelineErreur(RuntimeError):
    """Erreur attendue, avec un message lisible (et la solution) : affichée sans trace Python."""


class ClaudeErreur(PipelineErreur):
    pass


LOGIN_CLAUDE = "Claude n'est plus connecté.\n   → dans un terminal, lance :  claude   puis tape  /login"


def is_expected(e: BaseException) -> bool:
    """Erreur « normale » (message déjà lisible) : la nôtre ou celle de mistral_web."""
    return isinstance(e, PipelineErreur) or type(e).__name__ in ("MistralErreur", "SessionExpiree")


def claude_error(output: str) -> ClaudeErreur:
    low = output.lower()
    if any(k in low for k in ("not logged in", "/login", "authenticat", "oauth", "401", "invalid api key")):
        return ClaudeErreur(LOGIN_CLAUDE)
    if any(k in low for k in ("usage limit", "rate limit", "limit reached", "429", "quota", "overloaded")):
        return ClaudeErreur("Limite d'utilisation de ton abonnement Claude atteinte (ou serveurs surchargés) : "
                            f"réessaie plus tard.\n   Détail : {output.strip()[:200]}")
    return ClaudeErreur(f"Claude a échoué : {output.strip()[:300] or '(aucun message)'}")


# ----------------------------------------------------------------- config
def load_config() -> dict:
    cfg_path = ROOT / "config.toml"
    if not cfg_path.exists():   # premier lancement : on part du modèle versionné
        shutil.copy(ROOT / "config.example.toml", cfg_path)
        print(f"ℹ️  config.toml créé à partir de config.example.toml (adapte-le si besoin : {cfg_path})")
    with open(cfg_path, "rb") as f:
        cfg = tomllib.load(f)
    cfg["mistral_api_key"] = cfg.get("mistral_api_key") or os.environ.get("MISTRAL_API_KEY", "")
    return cfg


def p(path: str) -> Path:
    q = Path(path).expanduser()
    return q if q.is_absolute() else ROOT / q


def safe_name(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\n\r\t]', " ", s).strip(" .")
    return re.sub(r"\s+", " ", s)[:90] or "Cours"


# ----------------------------------------------------------------- métadonnées audio
DATE_RE = re.compile(r"(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})(?:[ _T-]?(\d{2})[-_h:.]?(\d{2}))?")


def recording_datetime(audio: Path) -> dt.datetime:
    m = DATE_RE.search(audio.stem)
    if m:
        try:
            y, mo, d, h, mi = (int(x) if x else 0 for x in m.groups())
            return dt.datetime(y, mo, d, h, mi)
        except ValueError:
            pass
    try:
        out = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format_tags=creation_time",
                              "-of", "default=nw=1:nk=1", str(audio)],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        if out:
            return dt.datetime.fromisoformat(out.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except Exception:
        pass
    return dt.datetime.fromtimestamp(audio.stat().st_mtime)


def guess_matiere(audio: Path, cfg: dict, when: dt.datetime) -> str:
    matieres = cfg.get("matieres", [])
    lower = {m.lower(): m for m in matieres}
    # 1) sous-dossier du dossier d'entrée
    for d in cfg.get("dossiers_entree", []):
        try:
            rel = audio.resolve().relative_to(p(d).resolve())
            if len(rel.parts) > 1:
                return lower.get(rel.parts[0].lower(), rel.parts[0])
        except ValueError:
            continue
    # 2) préfixe dans le nom du fichier ("Reseaux - cours 3.m4a")
    for m in matieres:
        if audio.stem.lower().startswith(m.lower()):
            return m
    # 3) emploi du temps
    for slot in cfg.get("emploi_du_temps", []):
        if when.isoweekday() == slot["jour"] and slot["debut"] <= f"{when:%H:%M}" < slot["fin"]:
            return slot["matiere"]
    return "auto"


# ----------------------------------------------------------------- transcription
def split_audio(audio: Path, minutes: int, tmp: Path) -> list[Path]:
    """Convertit en mp3 mono 16 kHz (petit et parfait pour la voix) et découpe en segments."""
    pattern = tmp / "seg_%03d.mp3"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(audio),
                    "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k",
                    "-f", "segment", "-segment_time", str(minutes * 60), "-reset_timestamps", "1",
                    str(pattern)], check=True)
    return sorted(tmp.glob("seg_*.mp3"))


def mistral_transcribe(seg: Path, cfg: dict) -> str:
    key = cfg["mistral_api_key"]
    if not key:
        raise PipelineErreur("Clé Mistral manquante : remplis mistral_api_key dans config.toml.")
    for attempt in range(4):
        data = [("model", cfg.get("mistral_model", "voxtral-mini-latest"))]
        if cfg.get("langue"):
            data.append(("language", cfg["langue"]))
        with open(seg, "rb") as f:
            r = requests.post(MISTRAL_URL, headers={"Authorization": f"Bearer {key}"},
                              data=data, files={"file": (seg.name, f, "audio/mpeg")}, timeout=900)
        if r.ok:
            return r.json().get("text", "").strip()
        if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
            log(f"  Mistral {r.status_code}, nouvel essai dans {10 * (attempt + 1)} s")
            time.sleep(10 * (attempt + 1))
            continue
        raise PipelineErreur(f"Erreur API Mistral (code {r.status_code}) : {r.text[:300]}")
    raise PipelineErreur("API Mistral : échec après plusieurs essais")


def transcribe_parts(files: list[Path], cfg: dict, logf=None) -> list[str]:
    """Transcrit une liste de morceaux audio (web ou API) et renvoie un texte par morceau."""
    logf = logf or log
    if cfg.get("transcription", "web") == "web":
        import mistral_web
        datas = mistral_web.transcribe_files(files, headless=not cfg.get("navigateur_visible", False), log=logf)
        return [mistral_web.format_transcript(d) for d in datas]
    parts = []
    for i, seg in enumerate(files, 1):
        logf(f"  Mistral (API) : segment {i}/{len(files)}")
        parts.append(mistral_transcribe(seg, cfg))
    return parts


def cache_path(audio: Path) -> Path:
    return ROOT / "work" / f"{recording_datetime(audio):%Y%m%d_%H%M}_{safe_name(audio.stem)}.txt"


def transcribe(audio: Path, cfg: dict, cache: Path) -> str:
    if cache.exists() and cache.stat().st_size > 0:
        log("  transcription déjà faite, Mistral n'est pas rappelé")
        return cache.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as t:
        segs = split_audio(audio, int(cfg.get("duree_segment_min", 30)), Path(t))
        parts = transcribe_parts(segs, cfg)
    text = "\n\n".join(parts)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return text


# ----------------------------------------------------------------- Claude
def find_supports(audio: Path) -> list[Path]:
    return [audio.with_suffix(ext) for ext in SUPPORT_EXT if audio.with_suffix(ext).exists()]


MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]


def date_fr(d: dt.datetime) -> str:
    return f"{d.day} {MOIS[d.month - 1]} {d.year}"


def md2pdf_clean(md: str, titre: str, matiere: str, when: dt.datetime) -> str:
    """Filet de sécurité md2pdf : frontmatter présent, pas de `#` ni de `---` dans le corps (hors blocs de code)."""
    md = md.strip()
    if md.startswith("---"):
        end = md.find("\n---", 3)
        front, body = (md[:end + 4], md[end + 4:]) if end != -1 else ("", md)
    else:
        front, body = "", md
    if "title:" not in front:
        t = titre.replace('"', "'")
        front = f'---\ntitle: "{t}"\nsubtitle: "{matiere}"\ndate: "{date_fr(when)}"\n---'
    return front + "\n\n" + clean_body(body) + "\n"


def clean_body(body: str) -> str:
    out, in_code = [], False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_code = not in_code
        elif not in_code:
            if re.fullmatch(r"\s*(-{3,}|\*{3,}|_{3,})\s*", line):
                continue                      # pas de séparateurs entre les sections
            if re.match(r"# ", line):
                line = "#" + line             # pas de titre de niveau 1 dans le corps
        out.append(line)
    return "\n".join(out).strip()


def find_claude() -> str:
    claude = shutil.which("claude")
    if not claude:
        raise ClaudeErreur("Claude Code introuvable (commande `claude`).\n"
                           "   → installe-le : https://claude.com/claude-code")
    return claude


def check_claude() -> str:
    """Vérifie que Claude Code est connecté ET répond (une connexion expirée peut encore dire « connecté »)."""
    claude = find_claude()
    st = subprocess.run([claude, "auth", "status"], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=30)
    try:
        if not json.loads(st.stdout).get("loggedIn"):
            raise ClaudeErreur(LOGIN_CLAUDE)
    except json.JSONDecodeError:
        pass                                   # ancienne version sans JSON : le test ci-dessous tranchera
    r = subprocess.run([claude, "-p", "--output-format", "text",
                        "--disallowedTools", "Write", "Edit", "NotebookEdit", "Bash", "WebFetch", "WebSearch"],
                       input="Réponds uniquement : OK", capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120, cwd=ROOT)
    if r.returncode != 0:
        raise claude_error((r.stderr or "") + "\n" + (r.stdout or ""))
    return "Claude : connecté et opérationnel"


def check_mic() -> str:
    lvl = mic_level(default_mic())
    if lvl < SILENCE_DB:
        raise PipelineErreur(f"{MUTE_MSG}\n   (niveau capté : {lvl:.0f} dB)")
    return f"Micro : OK, il capte du son ({lvl:.0f} dB)"


def check_mistral(cfg: dict) -> str:
    if cfg.get("transcription", "web") == "web":
        import mistral_web
        return mistral_web.check_session()
    if not cfg.get("mistral_api_key"):
        raise PipelineErreur("Mode API choisi mais clé Mistral absente (mistral_api_key dans config.toml).")
    return "Mistral (API) : clé présente"


def start_checks(cfg: dict, with_mic: bool = True) -> list[tuple[str, threading.Thread, dict]]:
    """Lance les vérifications en arrière-plan (pendant que tu choisis le dossier)."""
    checks = [("Claude", check_claude), ("Mistral", lambda: check_mistral(cfg))]
    if with_mic:
        checks.append(("Micro", check_mic))
    started = []
    for name, fn in checks:
        res: dict = {}

        def run(fn=fn, res=res):
            try:
                res["ok"] = fn()
            except Exception as e:
                if is_expected(e):
                    res["err"] = str(e)
                    return
                res["err"] = f"vérification impossible ({type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''})"
        th = threading.Thread(target=run, daemon=True)
        th.start()
        started.append((name, th, res))
    return started


def report_checks(started) -> bool:
    print("\nVérifications :", flush=True)
    all_ok = True
    for name, th, res in started:
        th.join(timeout=150)
        if "ok" in res:
            print(f"  ✅ {res['ok']}")
        else:
            all_ok = False
            print(f"  ❌ {name} : {res.get('err', 'pas de réponse (délai dépassé)')}")
    print(flush=True)
    return all_ok


def show_failure(e: BaseException, audio: Path | None, folder: Path | None) -> None:
    """Affiche une erreur lisible + comment relancer sans rien perdre."""
    print("\n" + "─" * 60)
    if is_expected(e):
        print(f"❌ {e}")
    else:
        ERR = ROOT / "erreurs"
        ERR.mkdir(exist_ok=True)
        (ERR / "derniere_erreur.txt").write_text(traceback.format_exc(), encoding="utf-8")
        print(f"❌ Erreur inattendue : {type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}")
        print(f"   Détail complet : {ERR / 'derniere_erreur.txt'}")
    if audio and audio.exists():
        print(f"\n💾 Rien n'est perdu, l'audio est conservé : {audio}")
        try:
            if cache_path(audio).exists():
                print("   La transcription est déjà faite et gardée : seule l'étape Claude sera refaite.")
        except Exception:
            pass
        cmd = f'python cours.py traiter "{audio}"' + (f' -d "{folder}"' if folder else "")
        print(f"   Pour relancer une fois le problème réglé :\n   {cmd}")
    print("─" * 60, flush=True)


def claude_notes(transcript: str, cfg: dict, matiere: str, supports: list[Path],
                 folder: Path | None = None, when: dt.datetime | None = None) -> dict:
    when = when or dt.datetime.now()
    claude = find_claude()
    sup_txt = ""
    if supports:
        sup_txt = ("Supports du cours fournis par le prof (lis-les avec l'outil Read, ils donnent "
                   "l'orthographe exacte des termes et la structure du cours) :\n"
                   + "\n".join(f"- {s}" for s in supports))
    nommage = f"« {when:%Y-%m-%d} - Titre du cours »."
    if folder:
        nommage = ("regarde les noms des fichiers .md déjà présents dans le dossier (hors transcriptions). "
                   "S'ils suivent une convention (ex. « Jour 1 », « Jour 2 » → « Jour 3 » ; « CM3 - Arbres » → "
                   "« CM4 - … » ; « 2026-11-04 - … »), continue-la avec le numéro ou la date qui suit, "
                   "dans le même style. Si aucune convention n'est claire : " + nommage)
    ctx_txt = ""
    if folder:
        ctx_txt = ((ROOT / "prompts" / "contexte_dossier.md").read_text(encoding="utf-8")
                   .replace("{dossier}", str(folder)).replace("{fichiers}", folder_listing(folder)))
    prompt = (ROOT / "prompts" / "notes.md").read_text(encoding="utf-8")
    prompt = (prompt.replace("{matiere}", matiere if matiere != "auto" else "inconnue (déduis-la)")
                    .replace("{matieres}", ", ".join(cfg.get("matieres", [])) or "—")
                    .replace("{supports}", sup_txt)
                    .replace("{contexte}", ctx_txt)
                    .replace("{date_fr}", date_fr(when))
                    .replace("{nommage}", nommage)
                    .replace("{standard}", (ROOT / "prompts" / "standard_md2pdf.md").read_text(encoding="utf-8")))
    # Claude ne peut que LIRE : tous les outils d'écriture / de commande sont interdits.
    cmd = [claude, "-p", "--output-format", "text",
           "--disallowedTools", "Write", "Edit", "NotebookEdit", "Bash", "WebFetch", "WebSearch",
           "--allowedTools", "Read", "Glob", "Grep"]
    if cfg.get("claude_model"):
        cmd += ["--model", cfg["claude_model"]]
    dirs = {str(s.parent) for s in supports} | ({str(folder)} if folder else set())
    if dirs:
        cmd += ["--add-dir", *dirs]
    log("  Claude lit le contexte et rédige la fiche…" if folder else "  Claude rédige la fiche…")
    try:
        r = subprocess.run(cmd, input=prompt + "\n" + transcript, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=1800, cwd=folder or ROOT)
    except subprocess.TimeoutExpired:
        raise ClaudeErreur("Claude n'a pas répondu en 30 min.")
    if r.returncode != 0:
        raise claude_error((r.stderr or "") + "\n" + (r.stdout or ""))
    if "---NOTES---" not in r.stdout:
        raise ClaudeErreur("La réponse de Claude n'a pas le format attendu : relance simplement le traitement.\n"
                           f"   Début de la réponse : {r.stdout.strip()[:200]}")
    meta_txt, rest = r.stdout.split("---NOTES---", 1)
    meta = {}
    for line in meta_txt.replace("---META---", "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    notes, sep, comp_txt = rest.partition("---COMPLEMENT:")
    meta["notes"] = notes.strip()
    meta["complements"] = re.findall(r"---COMPLEMENT:\s*(.+?)\s*---[ \t]*\n(.*?)\n---FIN COMPLEMENT---",
                                     sep + comp_txt, flags=re.S)
    return meta


# ----------------------------------------------------------------- dossier de cours (contexte)
ETAT = ROOT / ".etat.json"
TEXT_EXT = {".md", ".txt"}


def choose_folder() -> Path | None:
    """Fenêtre Windows pour choisir le dossier du cours (se souvient du dernier choisi)."""
    import json
    import tkinter as tk
    from tkinter import filedialog
    try:
        last = json.loads(ETAT.read_text(encoding="utf-8")).get("dernier_dossier", "")
    except Exception:
        last = ""
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    chosen = filedialog.askdirectory(title="Choisis le dossier du cours (contexte pour Claude)",
                                     initialdir=last or str(Path.home()), mustexist=True, parent=root)
    root.destroy()
    if not chosen:
        return None
    ETAT.write_text(json.dumps({"dernier_dossier": chosen}), encoding="utf-8")
    return Path(chosen)


def folder_listing(folder: Path, limit: int = 150) -> str:
    files = [f for f in folder.rglob("*") if f.is_file()
             and not any(part.startswith(".") for part in f.relative_to(folder).parts)]
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    lines = [f"- {f.relative_to(folder).as_posix()}  "
             f"({dt.datetime.fromtimestamp(f.stat().st_mtime):%Y-%m-%d}, {f.stat().st_size // 1024} Ko)"
             for f in files[:limit]]
    if len(files) > limit:
        lines.append(f"- … et {len(files) - limit} autres fichiers")
    return "\n".join(lines) or "(dossier vide)"


def unique_path(path: Path) -> Path:
    """Ne jamais écraser un fichier existant : ajoute (2), (3)…"""
    n, cand = 2, path
    while cand.exists():
        cand = path.with_name(f"{path.stem} ({n}){path.suffix}")
        n += 1
    return cand


def apply_complements(folder: Path, complements: list[tuple[str, str]], when: dt.datetime, titre: str) -> list[str]:
    """Ajoute les compléments proposés par Claude À LA FIN des fichiers. Rien n'est jamais supprimé ni réécrit."""
    folder = folder.resolve()
    done = []
    for rel, body in complements:
        target = (folder / rel.strip().strip('"`')).resolve()
        if folder not in target.parents:
            log(f"  complément ignoré (hors du dossier) : {rel}")
            continue
        header = f"## Complément — cours du {when:%d/%m/%Y} ({titre})\n\n"
        appendable = target.is_file() and target.suffix.lower() in TEXT_EXT
        if appendable:
            try:
                target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                appendable = False      # encodage inconnu : on ne touche pas au fichier
        if appendable:
            backup = ROOT / "sauvegardes" / f"{dt.datetime.now():%Y%m%d_%H%M%S}" / target.relative_to(folder)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            with open(target, "a", encoding="utf-8") as f:   # mode "a" = ajout à la fin uniquement
                f.write("\n\n" + header + clean_body(body) + "\n")
            done.append(f"complété : {target.relative_to(folder).as_posix()}")
        else:  # Word, PDF, fichier absent… : le complément va dans un nouveau fichier à côté
            new = unique_path(target.with_name(f"{target.stem} - complément {when:%Y-%m-%d}.md"))
            new.parent.mkdir(parents=True, exist_ok=True)
            new.write_text(md2pdf_clean(header + body, f"Complément — {target.stem}", folder.name, when),
                           encoding="utf-8")
            done.append(f"nouveau fichier : {new.relative_to(folder).as_posix()}")
    return done


# ----------------------------------------------------------------- traitement
def process(audio: Path, cfg: dict, matiere: str | None = None, folder: Path | None = None) -> Path:
    audio = audio.resolve()
    when = recording_datetime(audio)
    if folder:
        folder = folder.resolve()
        matiere = folder.name
    matiere = matiere or guess_matiere(audio, cfg, when)
    log(f"Traitement de « {audio.name} » — matière : {matiere}, date : {when:%Y-%m-%d %H:%M}")
    cache = cache_path(audio)
    seg_dir = audio.parent / audio.stem
    if not cache.exists() and seg_dir.is_dir() and any(seg_dir.glob("part_*.mp3")):
        # Relance après une erreur : on reprend les morceaux déjà transcrits pendant le cours.
        log("  reprise de l'enregistrement : les morceaux déjà transcrits sont réutilisés")
        finish_recording(seg_dir, None, cfg)
    transcript = transcribe(audio, cfg, cache)
    log(f"  transcription : {len(transcript.split())} mots")

    supports = find_supports(audio)
    meta = claude_notes(transcript, cfg, matiere, supports, folder, when)
    if matiere == "auto":
        found = meta.get("matiere", "").strip()
        known = {m.lower(): m for m in cfg.get("matieres", [])}
        matiere = known.get(found.lower(), found or "Divers")

    titre = meta.get("titre") or audio.stem
    out_dir = folder or p(cfg.get("dossier_sortie", "Cours")) / safe_name(matiere)
    (out_dir / "transcriptions").mkdir(parents=True, exist_ok=True)
    base = safe_name(re.sub(r"\.md$", "", meta.get("fichier", ""), flags=re.I)) if meta.get("fichier") else ""
    base = base or f"{when:%Y-%m-%d} - {safe_name(titre)}"
    note_path = unique_path(out_dir / f"{base}.md")
    trans_path = unique_path(out_dir / "transcriptions" / f"{base} (transcription).txt")

    added = apply_complements(folder, meta.get("complements", []), when, titre) if folder else []
    notes = meta["notes"]
    if added:
        notes += ("\n\n## Compléments ajoutés\n\nCe cours a aussi complété d'autres fichiers du dossier :\n\n"
                  + "\n".join(f"- {a}" for a in added))
    note_path.write_text(md2pdf_clean(notes, titre, matiere, when), encoding="utf-8")
    trans_path.write_text(f"Transcription — {titre}\n{matiere} — {date_fr(when)}\n\n{transcript}\n",
                          encoding="utf-8")

    # Tout est écrit : l'audio et le cache ne servent plus (la transcription est gardée en .txt).
    # En cas d'erreur avant ce point, rien n'est supprimé, pour pouvoir relancer.
    if cfg.get("garder_audio", False):
        dest = p(cfg.get("dossier_archive", "archive")) / safe_name(matiere)
        dest.mkdir(parents=True, exist_ok=True)
        shutil.move(str(audio), unique_path(dest / audio.name))
    else:
        audio.unlink(missing_ok=True)
    cache.unlink(missing_ok=True)
    print("\n" + "─" * 60)
    print(f"✅ {note_path.name}")
    print(f"   📁 {note_path.parent}")
    if meta.get("resume"):
        print(f"   📝 {meta['resume']}")
    for a in added:
        print(f"   ➕ {a}")
    print("─" * 60, flush=True)
    return note_path


# ----------------------------------------------------------------- watch
def is_candidate(f: Path) -> bool:
    return (f.is_file() and f.suffix.lower() in AUDIO_EXT
            and not f.name.startswith((".", "~")) and ".tmp" not in f.name.lower())


def watch(cfg: dict) -> None:
    dirs = [p(d) for d in cfg.get("dossiers_entree", ["inbox"])]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    log("Surveillance de : " + ", ".join(str(d) for d in dirs) + "  (Ctrl+C pour arrêter)")
    sizes: dict[Path, tuple[int, int]] = {}
    failed: set[Path] = set()
    while True:
        for d in dirs:
            for f in d.rglob("*"):
                if not is_candidate(f) or f in failed:
                    continue
                size = f.stat().st_size
                prev, stable = sizes.get(f, (-1, 0))
                stable = stable + 1 if size == prev and size > 0 else 0
                sizes[f] = (size, stable)
                if stable < 2:          # taille inchangée depuis ~10 s : la synchro est terminée
                    continue
                try:
                    process(f, cfg)
                except Exception as e:  # on log et on passe au suivant, le cache évite de repayer Mistral
                    failed.add(f)
                    log(f"❌ Échec sur {f.name} : {e}\n   (relance le watch ou `python cours.py traiter` pour réessayer)")
                sizes.pop(f, None)
        time.sleep(5)


# ----------------------------------------------------------------- enregistrement PC
def default_mic() -> str:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    lines = out.splitlines()
    for i, line in enumerate(lines):
        if line.rstrip().endswith("(audio)"):
            alt = next((l for l in lines[i + 1:i + 2] if "Alternative name" in l), None)
            return re.search(r'"(.+)"', alt or line).group(1)
    raise PipelineErreur("Aucun micro trouvé (micro désactivé ou non branché ?).")


# Micro coupé = silence total (≈ -90 dB). Un vrai cours ne descend jamais sous -50 dB pendant 10 s
# (mesuré sur un enregistrement réel), donc -60 dB pendant 15 s ne donne pas de fausse alerte.
SILENCE_DB, SILENCE_S = -60, 15
MUTE_MSG = ("Le micro ne capte aucun son : il est sans doute coupé "
            "(touche muet du PC, ou micro désactivé dans les paramètres son de Windows).")


def mic_level(mic: str, seconds: int = 2) -> float:
    """Niveau max (dB) capté par le micro pendant quelques secondes."""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-f", "dshow", "-i", f"audio={mic}",
                          "-t", str(seconds), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30).stderr
    m = re.search(r"max_volume:\s*(-?[\d.]+|-inf)", out)
    if not m:
        raise PipelineErreur("Impossible de lire le micro (utilisé par une autre application ?).")
    return -200.0 if m.group(1) == "-inf" else float(m.group(1))


def _watch_ffmpeg(proc: subprocess.Popen, state: dict) -> None:
    """Lit les messages de ffmpeg pendant l'enregistrement : alerte si le micro est coupé."""
    for raw in proc.stderr:
        line = raw.decode("utf-8", "replace")
        if "silence_start" in line:
            state["muet"] = True
            print(f"\n\a⚠️  [{dt.datetime.now():%H:%M}] MICRO COUPÉ ? Aucun son depuis {SILENCE_S} s.\n"
                  f"   {MUTE_MSG}\n   L'enregistrement continue. (Entrée pour arrêter)", flush=True)
        elif "silence_end" in line and state.get("muet"):
            state["muet"] = False
            print(f"✅ [{dt.datetime.now():%H:%M}] Le son est revenu.", flush=True)
    if not state.get("arret"):
        print(f"\n\a❌ [{dt.datetime.now():%H:%M}] L'enregistrement s'est arrêté tout seul (micro débranché ?).\n"
              "   Appuie sur Entrée pour traiter ce qui a été enregistré.", flush=True)


def _live_transcribe(seg_dir: Path, cfg: dict, stop: threading.Event) -> None:
    """Pendant l'enregistrement : transcrit chaque morceau terminé (Mistral seulement, pas Claude)."""
    tried: set[Path] = set()
    while not stop.is_set():
        parts = sorted(seg_dir.glob("part_*.mp3"))
        for part in parts[:-1]:             # le dernier morceau est encore en cours d'écriture
            if part in tried or stop.is_set():
                continue
            tried.add(part)
            n = int(part.stem.split("_")[1]) + 1
            try:
                txt = transcribe_parts([part], cfg, logf=lambda m: None)[0]
                part.with_suffix(".txt").write_text(txt, encoding="utf-8")
                log(f"   (morceau {n} transcrit en arrière-plan)")
            except Exception as e:
                log(f"   ⚠️ morceau {n} : transcription en arrière-plan ratée, nouvel essai à la fin "
                    f"({str(e).splitlines()[0] if str(e) else type(e).__name__})")
        stop.wait(15)


def record(cfg: dict, folder: Path | None) -> tuple[Path, threading.Thread]:
    """Enregistre en morceaux de 30 min, transcrits au fur et à mesure. Renvoie le dossier des morceaux."""
    rec_dir = ROOT / "enregistrements"
    now = dt.datetime.now()
    seg_dir = rec_dir / f"{now:%Y-%m-%d_%H%M}{'_' + safe_name(folder.name) if folder else ''}"
    seg_dir.mkdir(parents=True, exist_ok=True)
    mic = default_mic()
    seg_s = int(float(cfg.get("duree_segment_min", 30)) * 60)
    proc = subprocess.Popen(["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "info", "-f", "dshow",
                             "-i", f"audio={mic}", "-af", f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_S}",
                             "-ac", "1", "-ar", "16000", "-b:a", "64k",
                             "-f", "segment", "-segment_time", str(seg_s), "-reset_timestamps", "1",
                             str(seg_dir / "part_%03d.mp3")],
                            stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    state: dict = {}
    threading.Thread(target=_watch_ffmpeg, args=(proc, state), daemon=True).start()
    stop = threading.Event()
    live = threading.Thread(target=_live_transcribe, args=(seg_dir, cfg, stop), daemon=True)
    live.start()
    log("🎙️  Enregistrement en cours… Appuie sur Entrée pour arrêter.")
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        pass
    state["arret"] = True
    try:
        proc.stdin.write(b"q")
        proc.stdin.flush()
    except OSError:
        pass
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
    stop.set()
    log(f"Enregistrement terminé ({(dt.datetime.now() - now).seconds // 60} min).")
    return seg_dir, live


def finish_recording(seg_dir: Path, live: threading.Thread | None, cfg: dict) -> Path:
    """Recolle les morceaux en un seul audio, transcrit ceux qui restent, et prépare la transcription complète."""
    if live and live.is_alive():
        log("  (fin de la transcription du morceau en cours…)")
        live.join()
    parts = sorted(seg_dir.glob("part_*.mp3"))
    if not parts:
        raise PipelineErreur("Aucun audio n'a été enregistré (micro indisponible ?).")
    out = seg_dir.parent / f"{seg_dir.name}.mp3"
    lst = seg_dir / "liste.txt"
    lst.write_text("".join(f"file '{q.as_posix()}'\n" for q in parts), encoding="utf-8")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "fatal", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(out)], check=True)
    missing = [q for q in parts if not q.with_suffix(".txt").exists()]
    done = len(parts) - len(missing)
    if done:
        log(f"  {done} morceau(x) déjà transcrit(s) pendant le cours")
    if missing:
        for q, txt in zip(missing, transcribe_parts(missing, cfg)):
            q.with_suffix(".txt").write_text(txt, encoding="utf-8")
    text = "\n\n".join(q.with_suffix(".txt").read_text(encoding="utf-8") for q in parts)
    cache = cache_path(out)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    shutil.rmtree(seg_dir, ignore_errors=True)
    return out


def ask_pdf(cfg: dict) -> bool:
    if not cfg.get("md2pdf_script"):
        return False
    try:
        return input("📄 Convertir la fiche en PDF à la fin ? (o/N) ").strip().lower() in ("o", "oui", "y", "yes")
    except EOFError:
        return False


def convert_pdf(note: Path, cfg: dict) -> None:
    script = p(cfg["md2pdf_script"])
    if not script.exists():
        print(f"   ⚠️ PDF non créé : convertisseur introuvable ({script})")
        return
    cmd = [sys.executable, str(script), str(note), "-m", cfg.get("md2pdf_mode", "academic")]
    if cfg.get("md2pdf_theme"):
        cmd += ["-t", str(p(cfg["md2pdf_theme"]))]
    log("  Conversion en PDF…")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           cwd=script.parent, timeout=600)
        ok = r.returncode == 0 and note.with_suffix(".pdf").exists()
        detail = (r.stderr or r.stdout).strip()[-300:]
    except subprocess.TimeoutExpired:
        ok, detail = False, "délai dépassé (10 min)"
    print(f"   📄 {note.with_suffix('.pdf').name}" if ok else f"   ⚠️ Conversion PDF ratée (la fiche .md est bien là) : {detail}",
          flush=True)


# ----------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description="Audio de cours -> fiche Markdown")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("watch", help="surveille les dossiers d'entrée")
    sub.add_parser("login", help="se connecter à Mistral (une fois)")
    sub.add_parser("verifier", help="vérifie que Claude, Mistral et le micro sont prêts")
    t = sub.add_parser("traiter", help="traite un fichier audio")
    t.add_argument("fichier", type=Path)
    t.add_argument("-m", "--matiere")
    t.add_argument("-d", "--dossier", type=Path, help="dossier du cours (contexte + destination)")
    r = sub.add_parser("rec", help="choisit le dossier du cours, enregistre depuis le micro du PC puis traite")
    r.add_argument("-d", "--dossier", type=Path, help="dossier du cours (sinon une fenêtre demande)")
    a = ap.parse_args()
    cfg = load_config()
    if a.cmd == "login":
        import mistral_web
        mistral_web.login()
    elif a.cmd == "verifier":
        sys.exit(0 if report_checks(start_checks(cfg)) else 1)
    elif a.cmd == "watch":
        watch(cfg)
    elif a.cmd == "traiter":
        try:
            process(a.fichier, cfg, a.matiere, a.dossier)
        except Exception as e:
            show_failure(e, a.fichier.resolve(), a.dossier)
            sys.exit(1)
    else:
        print("Vérification de Claude, Mistral et du micro pendant que tu choisis le dossier…", flush=True)
        checks = start_checks(cfg)
        folder = a.dossier or choose_folder()
        if folder:
            log(f"📁 Dossier du cours : {folder}")
        else:
            log("Aucun dossier choisi : la fiche ira dans Cours/ (sans contexte).")
        if not report_checks(checks):
            print("⚠️  Tu peux quand même enregistrer : l'audio sera gardé et tu pourras le traiter plus tard.")
            if input("   Enregistrer quand même ? (o/N) ").strip().lower() not in ("o", "oui", "y"):
                return
        out = None
        try:
            seg_dir, live = record(cfg, folder)
            out = seg_dir.parent / f"{seg_dir.name}.mp3"
            pdf = ask_pdf(cfg)
            out = finish_recording(seg_dir, live, cfg)
            note = process(out, cfg, folder=folder)
            if pdf:
                convert_pdf(note, cfg)
        except Exception as e:
            show_failure(e, out if out and out.exists() else None, folder)
            sys.exit(1)


if __name__ == "__main__":
    main()
