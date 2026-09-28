# Changelog — gblogspm2_arg.py

Historique des versions du script de traitement et mise en forme des logs
Gunbot, piloté par arguments en ligne de commande (pas de question
interactive), destiné à l'automatisation quotidienne (cron) sur le
serveur. Pour le moteur de parsing des logs proprement dit (partagé à
l'identique avec `gblogspm2_ihm.py`), voir `gblogspm2_ihm.changelog.md`.

## gblogspm2_arg

### [0-2] — prise en compte du fichier de log courant ; sélection par bornes réelles

Constat (scan de test du 2026-09-28) : `scan` signalait 95 min (gbt1) et
75 min (gbt2) sans cycle alors que les cycles existaient. Cause :
`scan_out_files` n'acceptait que les archives logrotate
`<instance>-out__<date>.log[.gz]` ; le fichier courant `<instance>-out.log`
(cycles écrits depuis la dernière rotation) était ignoré.

Correctif :
- `scan_out_files` accepte aussi `<instance>-out.log` (trié en dernier).
- Nouvelle `file_time_bounds` : premier/dernier horodatage de cycle (UTC)
  lus dans le contenu du fichier (début et fin seulement pour les fichiers
  non compressés). Ni le nom (= heure de rotation, indicatif) ni la date
  de modification (heure locale, modifiable) ne font foi.
- Nouvelle `select_files_by_bounds` : retient les fichiers dont la période
  réelle chevauche [start, end]. Remplace `select_files_daily` et
  `select_files_in_range` (le mode daily n'exige plus les archives
  00:00:00 et fonctionne aussi pour la journée en cours).
- Les cycles présents à la fois dans une archive et le fichier courant
  restent dédupliqués par `raw_key`.

Coût : chaque fichier est ouvert pour lire ses bornes (les `.gz` sont
décompressés entièrement).

### [0-1] — première version, dérivée de gblogspm2_ihm.py (0-14)

Demande utilisateur : automatiser le lancement quotidien du script sur le
serveur (cron), ce qui suppose de remplacer toutes les questions
interactives (`input()`) de `gblogspm2_ihm.py` par des arguments en ligne
de commande. Le moteur de parsing des logs (détection des cycles, balises
GBLOG:BEGIN/END, résolution de paire, statistiques) est repris à
l'identique de la version 0-14 de `gblogspm2_ihm.py` ; seule la couche
« saisie utilisateur » change.

Arguments ajoutés (`argparse`), avec valeurs par défaut choisies pour
permettre une exécution sans aucun argument (cron quotidien) :

- `--instances` (défaut `all`) : équivalent de `ask_instance_selection`.
- `--mode {daily,precise}` (défaut `daily`) : équivalent de
  `ask_processing_mode`.
- `--start-date`/`--end-date` (mode `daily`, défaut hier/hier) :
  équivalent de `ask_daily_range`.
- `--start`/`--end` (mode `precise`, obligatoires dans ce mode) :
  équivalent de `ask_precise_range` (pas de défaut « maintenant » ici,
  volontairement, pour qu'un cron sans borne de fin explicite en mode
  précis échoue plutôt que de traiter une période inattendue).
- `--tf` (défaut `1440`, minutes) : équivalent de `ask_timeframe`.
- `--filter {none,first-per-candle}` (défaut `none`) : équivalent de
  `ask_filter_mode`.
- `--pairs` (défaut `all`) : équivalent de `ask_pair_selection`. Un cron
  ne pouvant pas répondre à une question posée dynamiquement selon les
  paires réellement détectées dans les logs, le choix retenu est de
  conserver **toutes les paires détectées** par défaut (comportement de
  l'option « Toutes les paires » de `gblogspm2_ihm.py`), avec un fichier
  `.txt` distinct par paire. Une paire explicitement demandée mais
  absente pour une instance donnée est ignorée pour cette instance
  (message affiché), sans faire échouer le run pour les autres instances.
- `--dir` (défaut : répertoire du script) : permet de pointer vers un
  autre répertoire `pm2/logs` que celui où réside le script, utile pour
  des tests ou une exécution hors du répertoire cible.

Décisions de conception actées avec l'utilisateur :
- Nom de fichier sans version (`gblogspm2_arg.py`, pas
  `gblogspm2_arg_0-1.py`) ; la version applicative reste indiquée dans le
  code (en-tête du module) et dans ce changelog.
- Mode par défaut = journalier sur la journée d'hier (`--mode daily` sans
  bornes), pour reproduire le comportement par défaut de la version IHM
  et permettre un cron sans aucun argument.
- `--tf`/`--filter` ont des valeurs par défaut (1440 / aucun filtrage)
  plutôt que d'être obligatoires, cohérent avec un traitement journalier
  automatique sans perte de cycles.

Comportement fonctionnel du moteur de parsing (cycles, statistiques,
nommage des fichiers de sortie, archive zip streamée) strictement
inchangé par rapport à `gblogspm2_ihm.py` [0-14].
