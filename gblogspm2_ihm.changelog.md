# Changelog — gblogspm2_ihm.py (ex gbLogs / gbLogsPm2)

Historique des versions du script de traitement et mise en forme des logs
Gunbot, questions posées interactivement à l'utilisateur (IHM). Toutes les
versions sont cross-platform (Linux et Windows).

Deux lignées se sont succédé avant le renommage en `gblogspm2_ihm.py` (la
version, 0-14, reste indiquée dans le code, cf. en-tête du script) :
- **gbLogs** (0-2, 0-3) : script à placer à côté des fichiers de logs bruts.
- **gbLogsPm2** (0-3 à 0-14) : script dédié aux logs générés par pm2,
  placé directement dans `pm2/logs`. La numérotation repart à 0-3 au
  changement de lignée.

Pour la version pilotée par arguments (automatisation/cron), voir
`gblogspm2_arg.py` et son changelog dédié `gblogspm2_arg.changelog.md`,
dérivée de la 0-14 ci-dessous.

## gbLogsPm2

### [0-16] — (après renommage) prise en compte du fichier de log courant ; sélection par bornes réelles

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

### [0-15 → gblogspm2_ihm.py] — renommage de fichier uniquement

Le fichier est renommé `gbLogsPm2_0-14.py` → `gblogspm2_ihm.py` (nom en
minuscule, cf. `AGENTS.md`, et suffixe `_ihm` pour le distinguer de
`gblogspm2_arg.py`, nouvelle version pilotée par arguments destinée à
l'automatisation quotidienne sur le serveur). La version applicative
reste 0-14 (indiquée dans le code, plus dans le nom de fichier) :
aucun changement fonctionnel.

### [0-14] — nouveau "Killed" (OOM) en production malgré la 0-12 ; passe
metadonnees + rendu par paire filtrée

Un run du 2026-09-22 sur gbt1/gbt2 a de nouveau été tué par l'OOM killer,
juste après le choix "Toutes les paires" sur gbt2 (~49000 cycles, 4
paires). Le correctif de la 0-12 (écriture streaming de l'archive)
n'agissait qu'en sortie : `collect_instance_cycles` continuait
d'accumuler en RAM, pour une même instance, le corps (liste des lignes)
de **tous les cycles de toutes les paires** avant même de savoir
lesquelles seraient conservées — l'essentiel du pic mémoire venait de là,
pas de l'écriture de l'archive.

**Correctif** : traitement de chaque instance en deux passes sur les
fichiers source.
1. Passe "métadonnées seules" (`parse_cycles`/`collect_instance_cycles`,
   nouveau paramètre `keep_body=False`) : découpe tous les cycles de
   l'instance, toutes paires confondues, sans jamais stocker leur corps
   (seuls timestamp/pair/durée/stats sont gardés). Sert à compter les
   paires présentes et poser la question de sélection de paire(s) *avant*
   toute accumulation lourde (reprend la suggestion de l'utilisateur de
   poser la question en amont).
2. Passe réelle, exécutée une fois par paire retenue (nouveau paramètre
   `pair_filter={pair}`) : reparse les mêmes fichiers, mais ne
   construit/garde en mémoire que les cycles (avec corps) de cette seule
   paire, aussitôt écrits dans l'archive zip puis libérés avant de passer
   à la paire suivante.

Le pic mémoire est ainsi borné à la plus grosse paire retenue pour une
instance donnée, plutôt qu'à la somme de toutes ses paires. Contrepartie
assumée : les fichiers sources sont relus/reparsés une fois par paire
retenue (E/S et CPU disque en plus, négligeables par rapport au risque
d'OOM). Comportement fonctionnel et contenu de l'archive de sortie
inchangés (même suffixe de nom de fichier par paire, mêmes stats
d'instance reportées dans chaque `.stats.json`).

### [0-13] — sélection explicite du mode de période + choix des instances

Deux évolutions fonctionnelles demandées par l'utilisateur :

1. Le mode journalier (journées complètes, fichiers 00:00:00 pm2) et le
   mode plage précise (bornes date+heure quelconques, y compris la
   journée en cours jusqu'à l'instant présent) n'étaient auparavant pas
   choisis explicitement : le mode journalier était déduit après coup en
   comparant les heures saisies à 00:00:00/23:59:59
   (`is_whole_day_range`). Une saisie ambiguë ou un besoin de traiter la
   journée en cours en temps réel n'était donc pas correctement couvert.
   **Correctif** : nouvelle question explicite (`ask_processing_mode`)
   posée avant la saisie des bornes ; deux fonctions de saisie dédiées
   (`ask_daily_range` pour des dates seules, `ask_precise_range` pour des
   date+heure avec défaut fin = maintenant). `is_whole_day_range` et
   l'ancienne `ask_date_range` sont supprimées.
2. Ajout de la sélection interactive des instances gunbot à traiter
   (`ask_instance_selection`), sur le même principe que la sélection de
   paire déjà existante. Toutes les instances détectées sont traitées
   par défaut (saisie vide).

### [0-12] — suite à un "Killed" par l'OOM killer Linux constaté en
production (run du 2026-09-22 sur gbt1/gbt2/gbt3)

La 0-11 accumulait en mémoire, pour toutes les instances et paires
traitées, l'intégralité des fichiers de sortie déjà mis en forme
(liste `output_entries`), et n'écrivait l'archive `.zip` qu'une seule
fois à la toute fin du traitement. Avec un gros volume de cycles/paires
(ex. gbt1 et gbt2 en "Toutes les paires", ~96000 cycles cumulés), cette
accumulation pouvait épuiser la RAM disponible sur le serveur avant même
d'avoir fini de traiter la dernière instance, faisant tuer le processus
par l'OOM killer (fichier de sortie jamais créé, sans message d'erreur
Python exploitable).

**Correctif** : l'archive `.zip` est désormais ouverte AVANT la boucle de
traitement des instances, et chaque fichier (`.txt` puis `.stats.json`)
y est écrit immédiatement (`out_zf.writestr`) dès qu'il est généré, au
lieu d'être conservé en mémoire jusqu'à la fin. Les structures
intermédiaires (`all_cycles`, `kept_cycles`, `groups_by_pair`) sont
explicitement libérées dès qu'elles ne sont plus nécessaires. Le pic
mémoire est ainsi proportionnel à une seule instance/paire à la fois,
plutôt qu'à la totalité du run. Comportement fonctionnel et contenu de
l'archive de sortie inchangés.

### [0-11] — suite à gunmaster 0-2-3, qui a changé le format des balises
GBLOG:BEGIN/END émises par `trading_engine.js`

Depuis gunmaster 0-2-3 (cf. `changelog_gunmaster.md` et
`changelog_trading_engine.md`, entrée [0-2-3]), le moteur unifié émet un
schéma de balise clé=valeur enrichi, avec un champ `schema=1` explicite :

```
[GBLOG:BEGIN schema=1 engine=0-2-3 strategy=maret pair=USDC-XRP exchange=hyperliquid mode=production t_ms=1725263842123]
...
[GBLOG:END schema=1 pair=USDC-XRP status=ok duration_ms=857 t_ms=1725263842980]
```

alors que la 0-10 attendait encore l'ancien format simple
`[GBLOG:BEGIN pair=... t_ms=...]` / `[GBLOG:END pair=... t_ms=...]` (champ
`pair` toujours en première position, aucun autre champ). Les anciennes
regex `GBLOG_BEGIN_RE`/`GBLOG_END_RE`, qui capturaient une forme figée, ne
matchaient donc plus AUCUNE balise émise par gunmaster 0-2-3+ : tous les
cycles retombaient silencieusement en mode hérité (perte de la garantie
d'attribution fiable par balise, seul objet de cette fonctionnalité
depuis la 0-8).

**Correctif** (`parse_gblog_line()`) : le parsing des balises BEGIN/END
est désormais générique, clé=valeur, insensible à l'ordre et au nombre de
champs présents sur la ligne — seul le champ `pair` est requis (comme
avant), `t_ms` reste optionnel. Les nouveaux champs émis par gunmaster
0-2-3+ (`schema`, `engine`, `strategy`, `exchange`, `mode` sur BEGIN ;
`status`, `duration_ms` sur END) sont lus sans erreur mais ignorés :
gbLogs continue de calculer lui-même `duration_ms` à partir de la
différence des `t_ms` de BEGIN/END (comportement inchangé depuis la 0-8),
sans les exploiter pour enrichir les statistiques à ce stade (hors
périmètre de ce correctif, qui vise uniquement à rétablir le parsing
cassé par le changement de format). Conséquence directe : ce parsing
générique reste également compatible avec l'ancien format simple (0-8 à
gunmaster 0-2-2), qui n'est qu'un cas particulier sans champs
additionnels.

### [0-10] — suite à la demande de consommateur de niveau 2
(`prompt_demande_correction_gblogs_0-9.md`)

Découverte distincte de celle traitée en 0-9 : quand le tableau ASCII et
la balise BEGIN sont en désaccord sur la paire, le champ interne `pair`
du cycle est déjà corrigé vers celui du BEGIN (mécanisme inchangé,
présent depuis la 0-9, qui garantit le bon routage par fichier). Mais le
texte de "header" affiché dans le `.txt` restait construit à partir du
tableau d'origine (paire, round et timestamp potentiellement
erronés/hérités).

- La paire affichée dans le header est désormais corrigée (celle du
  BEGIN, cohérente avec le champ interne `pair`). Round et timestamp
  restent en revanche inchangés : pas de reconstruction fiable possible
  côté gbLogs.
- Un marqueur `[GBLOGS:HEADER_PAIR_OVERRIDE table_pair=... begin_pair=...]`
  est inséré juste au-dessus du header concerné, pour signaler que ce
  round et ce timestamp restent potentiellement hérités du mauvais
  tableau malgré la paire désormais correcte. Le compteur `pair_mismatch`
  existant couvre déjà cet événement au niveau agrégé (`.stats.json`) ;
  pas de nouveau compteur ajouté.

### [0-9] — suite à la demande de correction du consommateur de niveau 2
(`prompt_demande_correction_gblogs_0-8.md`)

1. Détection du désaccord de paire au niveau du CONTENU (pas seulement
   tableau/BEGIN comme en 0-8) : chaque ligne de contenu portant un tag
   court de moteur (ex. `[maret_engine v0-1-15 [ETH]]`) est comparée à la
   paire du cycle auquel elle est sur le point d'être rattachée (cycle
   balisé ouvert, ou round hérité en cours). En cas de désaccord :
   - compteur `content_pair_mismatch` incrémenté ;
   - un marqueur `[GBLOGS:PAIR_MISMATCH round_pair=... content_pair=...]`
     est inséré dans le corps du cycle juste avant la ligne concernée.

   Résolution court → complet : une table de correspondance est
   construite dynamiquement à partir des lignes qui portent les deux
   formes à la fois (ex. `pairName="USDC-ETH"` sur la même ligne que le
   tag court `[ETH]`) ; si le tag court n'a pas encore été vu sous forme
   complète au moment de la comparaison, repli sur une reconstruction à
   partir du préfixe de cotation de la paire du cycle courant
   (`<quote_du_cycle>-<tag_court>`).
2. Compteur `pending_meta_overwritten` : incrémenté quand un tableau
   ASCII sans BEGIN/contenu associé est écrasé par le tableau suivant
   sans avoir jamais été rattaché à un cycle (perte silencieuse en 0-8).
3. `raw_key` de secours (tableau absent) désormais unique par
   construction (fichier + position dans le fichier), pour éviter toute
   déduplication accidentelle entre deux BEGIN distincts partageant un
   `t_ms` absent.
4. Statistiques archivées avec chaque fichier de sortie : un bloc
   d'en-tête commenté en tête de chaque `.txt`, et un fichier
   `<même_nom>.stats.json` associé dans l'archive zip (nom aligné sur
   celui du `.txt`, donc portant déjà l'instance et la paire, pour
   permettre l'association sans ambiguïté côté consommateur). NB :
   comme en 0-8, ces statistiques restent au niveau de l'instance
   (agrégées sur tous les fichiers pm2 de l'instance), pas ventilées par
   paire : quand plusieurs paires sont conservées pour une même
   instance, le même jeu de compteurs est reporté dans le `.stats.json`
   de chacune.

### [0-8] — changement majeur : détection des cycles par balises

Constat (vérifié sur logs réels gbd1, stratégie `maret_engine`, plusieurs
paires simultanées USDC-XRP/SOL/ZEC/ETH) : en mode websockets, le code
d'une paire peut être suspendu (`await` sur un événement ws ou un appel
réseau) puis reprendre son exécution APRÈS qu'une AUTRE paire ait déjà
affiché son propre tableau ASCII. La 0-7 supposait que tout le contenu
entre deux tableaux appartenait à la paire annoncée par le premier
tableau : c'était faux dans ce cas, et des rounds d'une paire se
retrouvaient dans le fichier de sortie d'une autre paire.

**Correction** : le découpage par cycle ne repose plus sur la position
relative aux tableaux, mais sur deux balises sentinelles émises
directement par le code de la stratégie (cf. `formatage_logs_gunbot.md`) :

```
[GBLOG:BEGIN pair=USDC-XRP t_ms=1725263842123]
...(logs spécifiques à la stratégie, contenu libre)...
[GBLOG:END pair=USDC-XRP t_ms=1725263842980]
```

Le tableau ASCII (inchangé, toujours généré par le cœur de Gunbot) reste
la source de vérité pour Round/Exchange/Pair/Strategy/Timestamp ; les
balises donnent l'attribution fiable du corps de log à la bonne paire,
indépendamment de tout entrelacement d'exécution. Le `t_ms` (timestamp OS
en millisecondes) permet de calculer la durée réelle de traitement de
chaque round (affichée dans l'en-tête de chaque cycle en sortie).

**Mode hybride** (rétro-compatibilité pendant la transition) : toutes les
stratégies/paires ne sont pas forcément encore instrumentées avec les
balises GBLOG au même moment. gbLogs détecte automatiquement, round par
round, le mode applicable :
- Si un tableau est immédiatement suivi d'un `[GBLOG:BEGIN ...]` → MODE
  BALISE : le corps du cycle est tout ce qui se trouve strictement entre
  ce BEGIN et le END correspondant (recherche par paire, la plus récente
  ouverture d'abord). Les lignes situées entre le END d'un round et le
  tableau suivant (typiquement `reached end of user code` puis des
  `[WS_DEBUG]` de préchargement pour la paire suivante) ne sont plus
  rattachées à aucun cycle : elles sont ignorées.
- Sinon → MODE HÉRITÉ (identique à la 0-7) : le corps du cycle est tout
  ce qui suit le tableau jusqu'au tableau suivant.

Limite connue du mode hybride : si, au même instant, une paire balisée a
un cycle encore ouvert ET qu'une paire non balisée produit du contenu en
concurrence (entrelacement réel), ce contenu non balisé peut se
retrouver attribué au cycle balisé ouvert (même défaut qu'en 0-7, mais
désormais limité aux seules paires pas encore instrumentées).

Détection d'anomalies ajoutée (comptabilisée et rapportée sans
interrompre le traitement) :
- les `END` orphelins (sans `BEGIN` correspondant encore ouvert) —
  typiquement le tout début d'un fichier issu d'une rotation pm2 en
  plein milieu d'un round ;
- les `BEGIN` jamais refermés par un `END` en fin de fichier (round
  tronqué) ;
- les cas où la paire du tableau et celle du `BEGIN` qui le suit
  diffèrent (la paire du `BEGIN` est alors retenue, jugée plus fiable
  car explicite).

### [0-7] — changement majeur : détection des cycles unifiée native/custom

Les stratégies "custom" (ex. `maret_gunbot`, exécutées sur des paires
alimentées en websockets, comme USDC-HYPE@hyperliquid) ne génèrent PAS la
ligne texte `GB_x.x.x PAIR@exchange Round #N YYYY/MM/DD HH:MM:SS` qui
précédait auparavant le tableau ASCII pour les stratégies natives (ex.
stepgrid). Seul le tableau ASCII est encore émis, et il est strictement
identique dans sa structure (colonnes Round / Exchange / Pair / Strategy
/ Timestamp) que la stratégie soit native ou custom.

Vérifié sur des logs réels (gbd2, stratégie `maret_gunbot` 0-1-9, paire
USDC-HYPE@hyperliquid) : malgré le websocket, le tableau continue d'être
émis à intervalle régulier (~5s) — le websocket ne fait que changer la
SOURCE des données utilisées à l'intérieur de chaque cycle, il ne
supprime pas la notion de cycle ni la génération du tableau. La
détection de cycle est donc unifiée pour les deux types de stratégies :

- Un cycle commence à la bordure supérieure du tableau (`┌─...─┐`), qu'une
  ligne texte `GB_...` la précède ou non.
- Les informations de cycle sont lues directement sur la ligne de données
  du tableau, avant que le tableau ne soit écarté du corps du cycle.
- Le tableau n'est jamais copié dans le corps du cycle.
- L'éventuelle ligne texte `GB_...` héritée des stratégies natives est
  désormais filtrée du corps du cycle (elle finirait sinon en fin de
  corps du cycle précédent, du fait de l'inversion d'ancrage).
- La clé d'unicité utilisée pour le dédoublonnage aux frontières de
  rotation pm2 est désormais la ligne de données brute du tableau (au
  lieu de l'ancienne ligne texte).

**Sélection de paire(s)** : une même instance pm2 peut héberger plusieurs
paires simultanément. Le tableau donnant désormais la paire de façon
fiable pour CHAQUE cycle, gbLogs peut filtrer par paire :
- une seule paire détectée → traitement normal, nommage inchangé
  (rétro-compatible avec la 0-6) ;
- plusieurs paires détectées → sélection interactive, un fichier `.txt`
  distinct par paire conservée (paire ajoutée au nom de fichier).

### [0-6] — correction du mode journalier

En mode journalier, le DERNIER fichier traité est désormais le fichier
daté `<date_fin + 1 jour> 00:00:00` lui-même, inclus en totalité (et non
plus le fichier le précédant immédiatement) : la rotation de minuit vide
le buffer pm2 de la journée qui se termine dans ce nouveau fichier, qui
contient donc les derniers cycles de `<date_fin>` avant d'enchaîner sur
ceux du lendemain. Ce fichier peut donc déborder légèrement sur la
journée suivante.

### [0-5] — ajout du mode journalier

Deux modes de sélection des fichiers à traiter, selon la saisie
utilisateur (date/heure de début et de fin, par défaut hier
00:00:00 → 23:59:59) :

- **Mode journalier** (par défaut, ou dès lors que début=00:00:00 et
  fin=23:59:59) : pm2 génère un fichier `-out` horodaté à 00:00:00 à
  chaque bascule de jour calendaire ; ce fichier est le meilleur point
  de départ pour une journée. Le premier fichier traité est celui daté
  `<date_début> 00:00:00`, le dernier est celui précédant immédiatement
  le fichier daté `<date_fin + 1 jour> 00:00:00` (corrigé en 0-6). Si
  l'un des deux fichiers 00:00:00 attendus est absent pour une instance
  donnée, bascule pour cette instance sur le mode plage précise.
- **Mode plage précise** (dès que l'utilisateur saisit une heure
  différente de 00:00:00/23:59:59) : tous les fichiers dans l'intervalle
  demandé, plus le fichier immédiatement antérieur/postérieur aux bornes
  s'ils existent. Si aucun fichier ne tombe dans l'intervalle, l'instance
  est ignorée (pas de fichier limitrophe récupéré, pour éviter de
  remonter un fichier arbitrairement éloigné pour une instance inactive
  sur la période demandée).

### [0-4] — version "serveur"

Le script est désormais placé directement dans le répertoire `pm2/logs`
et travaille sur les fichiers de logs présents sur disque : fini
l'archive zip en entrée (0-3). Sélection des fichiers par date/heure de
début et de fin saisies par l'utilisateur (par défaut hier
00:00:00 → 23:59:59) : fichiers dans l'intervalle, plus le fichier
immédiatement antérieur/postérieur aux bornes s'ils existent.

### [0-3] — nouvelle lignée pm2 (première version)

Première version de la lignée gbLogsPm2 : traitement des logs générés
par pm2 (fichiers `<instance>-out__YYYY-MM-DD_HH-MM-SS.log`, `.gz`
éventuel), à partir d'une archive `.zip` fournie en entrée (recherchée
automatiquement dans le répertoire courant si aucun chemin n'est passé
en argument). Les fichiers `<instance>-error__*.log` sont ignorés.
Plusieurs instances pm2 peuvent cohabiter dans la même archive, chacune
traitée indépendamment ; pour chaque instance, tous les fichiers `-out`
sont décompressés si besoin, nettoyés des codes ANSI, découpés en
cycles, puis fusionnés et triés chronologiquement (dédoublonnage aux
frontières de fichiers). Sortie : une archive `.zip` contenant un
fichier `.txt` fusionné par instance.

## gbLogs (lignée précédente, sans pm2)

### [0-3]

Changement majeur : détection des cycles désormais ancrée sur le tableau
ASCII lui-même (bordures `┌─...─┐` / `└─...─┘`), Gunbot fonctionnant
désormais avec des websockets et n'émettant plus la ligne texte
`GB_x.x.x PAIR@exchange Round #N YYYY/MM/DD HH:MM:SS` qui précédait
auparavant le tableau. Les informations de cycle (version, round,
exchange, pair, strategy, timestamp) sont lues sur la ligne de données du
tableau avant que celui-ci ne soit écarté du corps du cycle. La largeur
des colonnes variant d'un cycle à l'autre, la détection des bordures ne
se base que sur les caractères de début/fin de ligne, jamais sur une
largeur fixe. La ligne texte `GB_...` héritée d'un fichier plus ancien,
si présente, est désormais filtrée (redondante avec le tableau).

Ajout de la sélection de paire(s) : un même fichier de logs peut
contenir plusieurs paires (bot reconfiguré ou hébergeant plusieurs
stratégies custom) ; le tableau donnant désormais la paire de façon
fiable pour chaque cycle, l'utilisateur peut choisir interactivement la
ou les paires à conserver. Si plusieurs paires sont conservées, un
fichier `.txt` distinct est généré par paire, livré dans une archive
`.zip`.

### [0-2]

Version initiale. Traitement et mise en forme des fichiers de logs
Gunbot (placés dans le même répertoire que le script) : suppression des
tableaux ASCII, présentation de chaque cycle avec séparateur (double
pour le premier cycle après ouverture d'une bougie, simple pour les
autres) et en-tête `GB_xx.x.x PAIR@exchange Round #N YYYY/MM/DD
HH:MM:SS`.
