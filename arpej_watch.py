#!/usr/bin/env python3
"""Surveille les dispos de logement des résidences ARPEJ de Palaiseau et envoie un mail.

Zéro dépendance : uniquement la bibliothèque standard Python 3.9+.

Usage :
    python arpej_watch.py                 # une vérification (mode Planificateur de tâches)
    python arpej_watch.py --status        # affiche les dispos, n'envoie aucun mail
    python arpej_watch.py --test-email    # envoie un mail de test pour valider le SMTP
    python arpej_watch.py --loop 15       # boucle infinie, vérifie toutes les 15 minutes
    python arpej_watch.py --force-notify  # renvoie un mail même si rien n'a changé
"""

import argparse
import gzip
import html
import json
import os
import re
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
STATE_FILE = BASE_DIR / "state.json"
LOG_FILE = BASE_DIR / "watch.log"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
TIMEOUT = 30

# Résidence surveillée : Alexandre Manceau (Palaiseau) uniquement.
# ARPEJ la découpe en deux fiches distinctes ; on suit les deux.
# Si tu ne veux que la partie étudiants, supprime le second bloc.
RESIDENCES = [
    {
        "key": "alexandre-manceau-etu",
        "nom": "Alexandre Manceau — étudiants",
        "url": "https://www.arpej.fr/fr/residence/alexandre-manceau-residence-etudiante-palaiseau/",
    },
    {
        "key": "alexandre-manceau-ja",
        "nom": "Alexandre Manceau — jeunes actifs",
        "url": "https://www.arpej.fr/fr/residence/alexandre-manceau-residence-jeunes-actifs-palaiseau/",
    },
]

# Les autres résidences ARPEJ de Palaiseau, si tu veux les réactiver un jour :
# décommente le bloc voulu et colle-le dans RESIDENCES ci-dessus.
#
#     {
#         "key": "claudie-haignere",
#         "nom": "Claudie Haigneré — étudiants",
#         "url": "https://www.arpej.fr/fr/residence/claudie-haignere-palaiseau/",
#     },
#     {
#         "key": "edgar-faure",
#         "nom": "Edgar Faure — étudiants",
#         "url": "https://www.arpej.fr/fr/residence/edgar-faure-residence-etudiante-palaiseau/",
#     },

# Bloc HTML visé sur la fiche résidence :
#   <span class="folder-points__text">Disponibilité</span>
#   <span class="folder-points__figure folder-points__figure--green">6 logements disponibles</span>
FIGURE_RE = re.compile(
    r'folder-points__figure[^"]*"\s*>\s*(.*?)\s*</span>', re.IGNORECASE | re.DOTALL
)
DISPO_RE = re.compile(
    r"(aucun\s+logement\s+disponible|(\d+)\s+logements?\s+disponibles?)", re.IGNORECASE
)


def log(message):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    print(line, flush=True)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def load_config():
    """Config depuis config.json, surchargeable par variables d'environnement."""
    cfg = {}
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

    for json_key, env_key in [
        ("smtp_host", "ARPEJ_SMTP_HOST"),
        ("smtp_port", "ARPEJ_SMTP_PORT"),
        ("smtp_user", "ARPEJ_SMTP_USER"),
        ("smtp_password", "ARPEJ_SMTP_PASSWORD"),
        ("destinataire", "ARPEJ_TO"),
    ]:
        if os.environ.get(env_key):
            cfg[json_key] = os.environ[env_key]

    cfg.setdefault("smtp_host", "smtp.gmail.com")
    cfg.setdefault("smtp_port", 465)
    cfg["smtp_port"] = int(cfg["smtp_port"])
    cfg.setdefault("destinataire", cfg.get("smtp_user", ""))

    manquant = [k for k in ("smtp_user", "smtp_password", "destinataire") if not cfg.get(k)]
    if manquant:
        raise SystemExit(
            "Configuration incomplète : " + ", ".join(manquant) + "\n"
            f"Renseigne {CONFIG_FILE} (copie config.example.json) "
            "ou définis les variables ARPEJ_SMTP_USER / ARPEJ_SMTP_PASSWORD / ARPEJ_TO."
        )
    return cfg


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log("state.json illisible, on repart de zéro.")
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "fr-FR,fr;q=0.9",
            "Accept-Encoding": "gzip",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace")


def parse_dispo(page):
    """Renvoie le nombre de logements dispos, ou None si le marqueur est introuvable."""
    for bloc in FIGURE_RE.findall(page):
        texte = html.unescape(re.sub(r"<[^>]+>", " ", bloc))
        texte = re.sub(r"\s+", " ", texte).strip()
        m = DISPO_RE.search(texte)
        if m:
            return 0 if m.group(2) is None else int(m.group(2))
    return None


def check_all():
    """[(residence, nb_dispos|None, erreur|None), ...]"""
    resultats = []
    for res in RESIDENCES:
        try:
            nb = parse_dispo(fetch(res["url"]))
            if nb is None:
                resultats.append((res, None, "marqueur de disponibilité introuvable (page modifiée ?)"))
            else:
                resultats.append((res, nb, None))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            resultats.append((res, None, f"erreur réseau : {exc}"))
    return resultats


def build_email(cfg, sujet, corps_texte, corps_html=None):
    msg = EmailMessage()
    msg["Subject"] = sujet
    msg["From"] = cfg["smtp_user"]
    msg["To"] = cfg["destinataire"]
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(corps_texte)
    if corps_html:
        msg.add_alternative(corps_html, subtype="html")
    return msg


def send_email(cfg, msg):
    ctx = ssl.create_default_context()
    if cfg["smtp_port"] == 465:
        with smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"], context=ctx, timeout=TIMEOUT) as s:
            s.login(cfg["smtp_user"], cfg["smtp_password"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=TIMEOUT) as s:
            s.starttls(context=ctx)
            s.login(cfg["smtp_user"], cfg["smtp_password"])
            s.send_message(msg)


def notify(cfg, nouveautes, resultats):
    """nouveautes : [(residence, nb, precedent)]"""
    total = sum(nb for _, nb, _ in nouveautes)
    noms = ", ".join(r["nom"] for r, _, _ in nouveautes)
    sujet = f"[ARPEJ Palaiseau] {total} logement{'s' if total > 1 else ''} dispo — {noms}"

    lignes = ["Des logements viennent de se libérer sur ARPEJ Palaiseau :", ""]
    for res, nb, prec in nouveautes:
        avant = "inconnu" if prec is None else prec
        lignes.append(f"  * {res['nom']} : {nb} dispo(s)  (avant : {avant})")
        lignes.append(f"    {res['url']}")
    if len(resultats) > 1:  # inutile de répéter l'état si on ne suit qu'une résidence
        lignes += ["", "--- État complet ---"]
        for res, nb, err in resultats:
            lignes.append(f"  {res['nom']} : {err if err else f'{nb} dispo(s)'}")
    lignes += ["", "Dépôt de dossier : https://ibail.arpej.fr/", "", "-- arpej_watch"]
    texte = "\n".join(lignes)

    items = "".join(
        f'<li><b>{html.escape(res["nom"])}</b> : <b style="color:#0a7d2b">{nb}</b> '
        f'logement(s) disponible(s) <i>(avant : {"inconnu" if prec is None else prec})</i><br>'
        f'<a href="{res["url"]}">Voir la fiche</a></li>'
        for res, nb, prec in nouveautes
    )
    if len(resultats) > 1:
        autres = "".join(
            f'<li>{html.escape(res["nom"])} : {html.escape(err) if err else f"{nb} dispo(s)"}</li>'
            for res, nb, err in resultats
        )
        bloc_etat = f"<h4>État complet</h4><ul>{autres}</ul>"
    else:
        bloc_etat = ""
    corps_html = (
        '<div style="font-family:system-ui,sans-serif;font-size:15px">'
        "<h2>Logement dispo à Palaiseau 🎉</h2>"
        f"<ul>{items}</ul>"
        '<p><a href="https://ibail.arpej.fr/" '
        'style="background:#0a7d2b;color:#fff;padding:10px 16px;border-radius:6px;'
        'text-decoration:none">Déposer mon dossier</a></p>'
        f"{bloc_etat}"
        '<p style="color:#888;font-size:12px">-- arpej_watch</p></div>'
    )

    send_email(cfg, build_email(cfg, sujet, texte, corps_html))
    log(f"Mail envoyé à {cfg['destinataire']} : {sujet}")


def run_once(cfg, force_notify=False):
    resultats = check_all()
    state = load_state()
    nouveautes = []

    for res, nb, err in resultats:
        if err:
            log(f"{res['nom']} : {err}")
            continue  # on ne touche pas à l'état en cas d'échec
        precedent = state.get(res["key"])
        log(f"{res['nom']} : {nb} dispo(s) (précédent : {precedent})")
        if nb > 0 and (force_notify or precedent is None or nb > precedent):
            nouveautes.append((res, nb, precedent))
        state[res["key"]] = nb

    if nouveautes:
        try:
            notify(cfg, nouveautes, resultats)
        except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
            log(f"ÉCHEC envoi du mail : {exc} — l'état n'est pas sauvegardé, nouvelle tentative au prochain tour.")
            return 1
    else:
        log("Rien de neuf, pas de mail.")

    save_state(state)
    return 0


def cmd_status():
    for res, nb, err in check_all():
        print(f"{res['nom']:<38} {err if err else f'{nb} logement(s) disponible(s)'}")
    return 0


def cmd_test_email(cfg):
    etat = "\n".join(
        f"  {res['nom']} : {err if err else f'{nb} dispo(s)'}" for res, nb, err in check_all()
    )
    msg = build_email(
        cfg,
        "[ARPEJ Palaiseau] Mail de test — la surveillance fonctionne",
        "Si tu lis ce message, la configuration SMTP est bonne.\n\n"
        f"État actuel des résidences :\n{etat}\n\n-- arpej_watch",
    )
    send_email(cfg, msg)
    log(f"Mail de test envoyé à {cfg['destinataire']}.")
    return 0


def main():
    p = argparse.ArgumentParser(description="Surveillance des dispos ARPEJ Palaiseau")
    p.add_argument("--status", action="store_true", help="affiche les dispos sans envoyer de mail")
    p.add_argument("--test-email", action="store_true", help="envoie un mail de test")
    p.add_argument("--force-notify", action="store_true", help="envoie un mail même sans changement")
    p.add_argument("--loop", type=int, metavar="MINUTES", help="boucle en continu toutes les N minutes")
    args = p.parse_args()

    if args.status:
        return cmd_status()

    cfg = load_config()

    if args.test_email:
        return cmd_test_email(cfg)

    if args.loop:
        log(f"Démarrage de la boucle (toutes les {args.loop} min). Ctrl+C pour arrêter.")
        while True:
            try:
                run_once(cfg, args.force_notify)
            except Exception as exc:  # la boucle ne doit jamais mourir
                log(f"Erreur inattendue : {exc!r}")
            time.sleep(args.loop * 60)

    return run_once(cfg, args.force_notify)


if __name__ == "__main__":
    sys.exit(main())
