# ARPEJ Alexandre Manceau (Palaiseau) — alerte logement dispo

Bot qui surveille la résidence **Alexandre Manceau** à Palaiseau (campus Paris-Saclay) et **envoie un mail dès qu'un logement se libère**.

Zéro dépendance : uniquement la bibliothèque standard Python (testé avec Python 3.12).

ARPEJ découpe Alexandre Manceau en deux fiches, les deux sont surveillées :

| Partie | Fiche |
|---|---|
| Étudiants (259 logements) | [lien](https://www.arpej.fr/fr/residence/alexandre-manceau-residence-etudiante-palaiseau/) |
| Jeunes actifs (54 logements) | [lien](https://www.arpej.fr/fr/residence/alexandre-manceau-residence-jeunes-actifs-palaiseau/) |

Si tu ne veux que la partie étudiants, supprime le second bloc de `RESIDENCES` dans [arpej_watch.py](arpej_watch.py). Les 2 autres résidences de Palaiseau (Claudie Haigneré, Edgar Faure) sont en commentaire juste en dessous : décommente le bloc voulu et colle-le dans `RESIDENCES` pour l'ajouter.

## 1. Vérifier que ça lit bien le site

Aucune config nécessaire, aucun mail envoyé :

```bash
python arpej_watch.py --status
```

## 2. Configurer l'envoi de mail (Gmail)

Gmail refuse ton mot de passe habituel : il faut un **mot de passe d'application** (16 caractères). À créer toi-même, je n'y touche pas :

1. Active la validation en 2 étapes : https://myaccount.google.com/signinoptions/two-step-verification
2. Crée un mot de passe d'application : https://myaccount.google.com/apppasswords (nom au choix, ex. « arpej-watch »)
3. Copie `config.example.json` en `config.json` et colle le mot de passe généré (sans les espaces) :

```bash
copy config.example.json config.json
```

```json
{
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 465,
  "smtp_user": "baffaliecelian@gmail.com",
  "smtp_password": "abcdefghijklmnop",
  "destinataire": "baffaliecelian@gmail.com"
}
```

`config.json`, `state.json` et `watch.log` sont dans le `.gitignore` — le mot de passe ne partira jamais dans un commit.

> Alternative sans fichier : définir les variables d'environnement `ARPEJ_SMTP_USER`, `ARPEJ_SMTP_PASSWORD`, `ARPEJ_TO`.

Test de la config :

```bash
python arpej_watch.py --test-email
```

## 3. Lancer la surveillance en continu

### Option A — GitHub Actions (recommandé : tourne 24/7, PC éteint, gratuit)

Le workflow [.github/workflows/arpej-watch.yml](.github/workflows/arpej-watch.yml) exécute la vérification toutes les 15 min sur les serveurs GitHub, et recommite `state.json` pour se souvenir de l'état entre deux exécutions.

1. Crée un dépôt **public** sur GitHub (public = minutes Actions illimitées ; en privé tu n'as que 2000 min/mois, passe alors le cron à `*/30`).
2. Pousse ce dossier :
   ```bash
   git remote add origin https://github.com/TON-PSEUDO/arpej-watch.git
   git push -u origin main
   ```
3. Dans le dépôt → **Settings → Secrets and variables → Actions → New repository secret**, crée 3 secrets :

   | Nom | Valeur |
   |---|---|
   | `ARPEJ_SMTP_USER` | ton adresse Gmail |
   | `ARPEJ_SMTP_PASSWORD` | le mot de passe d'application (16 lettres, sans espaces) |
   | `ARPEJ_TO` | l'adresse qui reçoit l'alerte |

4. Onglet **Actions** → *ARPEJ Alexandre Manceau* → **Run workflow** pour un premier essai.

`config.json` est gitignoré : le mot de passe reste chez toi et dans les secrets GitHub, jamais dans le code.

⚠️ Deux limites de GitHub Actions à connaître :
- le cron est « au mieux » : en heure de pointe, une exécution prévue à 15 min peut tomber 20 à 40 min plus tard ;
- GitHub **désactive les workflows planifiés après 60 jours sans activité sur le dépôt**. Il t'envoie un mail : un clic sur « Enable workflow » suffit à relancer.

### Option B — tâche planifiée Windows (tourne tant que le PC est allumé)

```bash
powershell -ExecutionPolicy Bypass -File install_task.ps1
```

Vérification toutes les 15 minutes par défaut. Autre intervalle :

```bash
powershell -ExecutionPolicy Bypass -File install_task.ps1 -IntervalMinutes 10
```

Déclencher tout de suite pour tester :

```bash
powershell -Command "Start-ScheduledTask -TaskName ARPEJ-Palaiseau-Watch"
```

Désinstaller :

```bash
powershell -ExecutionPolicy Bypass -File install_task.ps1 -Remove
```

### Option C — boucle dans un terminal (s'arrête si tu fermes la fenêtre)

```bash
python arpej_watch.py --loop 15
```

## Quand reçois-tu un mail ?

Le script mémorise le nombre de logements dispos de chaque partie dans `state.json`.

| Situation | Mail ? |
|---|---|
| 1er lancement avec des dispos | ✅ |
| 0 → 3 dispos | ✅ |
| 2 → 5 dispos (ça augmente) | ✅ |
| 6 → 6 dispos (rien ne bouge) | ❌ pas de spam |
| 5 → 2 dispos (ça baisse) | ❌ |
| Le site est down / timeout | ❌ (loggé, l'état est préservé, nouvel essai au tour suivant) |

Le mail contient le nombre de logements, le lien vers la fiche concernée et le lien de dépôt de dossier.

Pour forcer un envoi sans attendre un changement : `python arpej_watch.py --force-notify`.
Pour repartir de zéro : supprime `state.json`.

## Journal

Tout est tracé dans `watch.log` (même chose que la sortie console).

## Si ça casse un jour

Le script lit le bloc « Disponibilité » de la fiche résidence (`folder-points__figure` dans le HTML). Si ARPEJ refond son site, `--status` affichera *« marqueur de disponibilité introuvable (page modifiée ?) »* : il suffira d'ajuster `FIGURE_RE` / `DISPO_RE` dans [arpej_watch.py](arpej_watch.py).

Note : au moment de l'écriture, les deux parties d'Alexandre Manceau affichent « Aucun logement disponible » — c'est exactement le cas d'usage du bot, il t'alertera à la première place qui se libère.
