"""Transcription via la page « Reconnaissance vocale » de Mistral Studio (compte gratuit), pilotée par Edge.

La page appelle elle-même l'API de Mistral : on dépose le fichier, on clique « Transcrire »,
et on récupère la réponse JSON (texte + locuteurs) au passage, sans lire l'affichage.
"""
from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

from playwright.sync_api import Error as PWError, TimeoutError as PWTimeout, sync_playwright

ROOT = Path(__file__).resolve().parent
PROFILE = ROOT / ".navigateur"          # profil Edge dédié : garde ta connexion Mistral
URL = "https://console.mistral.ai/audio/speech-to-text"
ERREURS = ROOT / "erreurs"


class MistralErreur(RuntimeError):
    """Erreur Mistral avec un message lisible (et la solution)."""


class SessionExpiree(MistralErreur):
    pass


def _launch(pw, headless: bool):
    try:
        return pw.chromium.launch_persistent_context(
            str(PROFILE), channel="msedge", headless=headless, viewport={"width": 1400, "height": 900})
    except PWError as e:
        if "ProcessSingleton" in str(e) or "already in use" in str(e).lower() or "lock" in str(e).lower():
            raise MistralErreur("Le navigateur de la pipeline est déjà ouvert (une autre transcription ou "
                                "`login` en cours ?). Ferme-le puis réessaie.")
        raise MistralErreur(f"Impossible de lancer Edge : {str(e).splitlines()[0]}")


def _screenshot(page, nom: str) -> Path | None:
    try:
        ERREURS.mkdir(exist_ok=True)
        path = ERREURS / f"{dt.datetime.now():%Y%m%d_%H%M%S}_{nom}.png"
        page.screenshot(path=str(path))
        return path
    except Exception:
        return None


def _open_page(page) -> None:
    """Ouvre la page Reconnaissance vocale et vérifie qu'elle est utilisable, sinon explique pourquoi."""
    try:
        page.goto(URL, timeout=45_000)
    except PWError as e:
        raise MistralErreur("Mistral est injoignable (connexion internet ? site en panne ?).\n"
                            f"   Détail : {str(e).splitlines()[0]}")
    try:
        page.locator("input[type=file]").first.wait_for(state="attached", timeout=25_000)
        page.locator('button:not([id*="trigger"])', has_text="Transcrire").last.wait_for(timeout=10_000)
        return
    except PWTimeout:
        pass
    url = page.url.lower()
    if any(k in url for k in ("auth", "login", "signin", "sign-in", "sso")):
        raise SessionExpiree("Tu n'es plus connecté à Mistral.\n   → lance :  python cours.py login")
    shot = _screenshot(page, "page_mistral")
    raise MistralErreur("La page Reconnaissance vocale de Mistral ne ressemble plus à ce qui est prévu "
                        "(page modifiée par Mistral, ou bloquée).\n"
                        f"   URL : {page.url}\n"
                        + (f"   Capture d'écran : {shot}\n" if shot else "")
                        + "   → mets navigateur_visible = true dans config.toml pour voir ce qui se passe,\n"
                          "     ou passe transcription = \"api\" (payant) en attendant.")


def check_session() -> str:
    """Vérification rapide (sans transcrire) : renvoie un message OK, ou lève MistralErreur."""
    with sync_playwright() as pw:
        ctx = _launch(pw, headless=True)
        try:
            _open_page(ctx.pages[0] if ctx.pages else ctx.new_page())
        finally:
            ctx.close()
    return "Mistral : connecté, page de transcription accessible"


def login() -> None:
    """Ouvre Edge pour que tu te connectes à Mistral. Se ferme tout seul une fois la page atteinte."""
    with sync_playwright() as pw:
        ctx = _launch(pw, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(URL)
        print("Connecte-toi à Mistral dans la fenêtre Edge (15 min max)…", flush=True)
        deadline = time.time() + 15 * 60
        while time.time() < deadline:
            try:
                if URL in page.url and page.locator("input[type=file]").count():
                    print("✅ Connecté. Tu peux lancer la pipeline.")
                    time.sleep(2)
                    break
            except Exception:  # fenêtre fermée par l'utilisateur
                break
            time.sleep(2)
        ctx.close()


def transcribe_files(files: list[Path], headless: bool = True, timeout_min: int = 25, log=print) -> list[dict]:
    """Transcrit chaque fichier et renvoie la réponse JSON de Mistral ({text, segments, ...})."""
    results = []
    with sync_playwright() as pw:
        ctx = _launch(pw, headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            for i, f in enumerate(files, 1):
                log(f"  Mistral (web) : segment {i}/{len(files)}")
                _open_page(page)
                page.locator("input[type=file]").first.set_input_files(str(f))
                btn = page.locator('button:not([id*="trigger"])', has_text="Transcrire").last
                deadline = time.time() + 120
                while not btn.is_enabled():
                    if time.time() > deadline:
                        shot = _screenshot(page, "bouton_transcrire")
                        raise MistralErreur("Le bouton « Transcrire » ne s'active pas (fichier refusé ou page modifiée)."
                                            + (f"\n   Capture d'écran : {shot}" if shot else ""))
                    time.sleep(1)
                try:
                    with page.expect_response(
                            lambda r: "/audio/transcriptions" in r.url and r.request.method == "POST",
                            timeout=timeout_min * 60_000) as info:
                        btn.click()
                except PWTimeout:
                    shot = _screenshot(page, "attente_transcription")
                    raise MistralErreur(f"Mistral n'a pas renvoyé la transcription en {timeout_min} min."
                                        + (f"\n   Capture d'écran : {shot}" if shot else ""))
                resp = info.value
                if not resp.ok:
                    body = resp.text()[:300]
                    if resp.status in (401,):
                        raise SessionExpiree("Tu n'es plus connecté à Mistral.\n   → lance :  python cours.py login")
                    if resp.status in (402, 403, 429):
                        raise MistralErreur(f"Mistral refuse la transcription (code {resp.status}) : quota gratuit "
                                            f"du mois probablement épuisé.\n   Détail : {body}")
                    raise MistralErreur(f"Erreur Mistral (code {resp.status}) : {body}")
                results.append(resp.json())
        finally:
            ctx.close()
    return results


def format_transcript(data: dict) -> str:
    """Texte brut, ou texte découpé par locuteur s'il y a plusieurs voix (questions d'étudiants…)."""
    segs = data.get("segments") or []
    speakers = {s.get("speaker_id") for s in segs if s.get("speaker_id")}
    if len(speakers) < 2:
        return (data.get("text") or "").strip()
    blocks, last = [], None
    for s in segs:
        spk = s.get("speaker_id") or last
        if spk != last:
            blocks.append(f"\n[{spk.replace('speaker_', 'Locuteur ')}]")
            last = spk
        blocks.append(s.get("text", "").strip())
    return " ".join(blocks).strip().replace(" \n", "\n")
