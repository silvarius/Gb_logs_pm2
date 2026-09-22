#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gbLogsPm2_0-13.py
Traitement et mise en forme des fichiers de logs Gunbot generes par pm2.
Version "serveur" : le script est place directement dans le repertoire
pm2/logs et travaille sur les fichiers de logs presents sur disque.
Version cross-platform : Linux et Windows.

Historique des versions : cf. CHANGELOG.md.

Usage :
  placer ce script dans le repertoire pm2/logs, puis : python3 gbLogsPm2_0-13.py

Format des balises GBLOG:BEGIN/END (emises par gunmaster trading_engine.js
ou toute strategie custom, cf. "formatage_logs_gunbot.md") : cle=valeur
libre, parsing insensible a l'ordre et au nombre de champs presents sur
la ligne (seul `pair` est requis, `t_ms` optionnel) :

    [GBLOG:BEGIN schema=1 engine=0-2-3 strategy=maret pair=USDC-XRP exchange=hyperliquid mode=production t_ms=1725263842123]
    ...
    [GBLOG:END schema=1 pair=USDC-XRP status=ok duration_ms=857 t_ms=1725263842980]

Les champs additionnels du schema=1 (engine, strategy, exchange, mode,
status, duration_ms) sont lus sans erreur mais ignores : gbLogs continue
de calculer lui-meme duration_ms a partir de la difference des t_ms de
BEGIN/END. Ce parsing reste egalement compatible avec l'ancien format
simple sans champs additionnels (`[GBLOG:BEGIN pair=... t_ms=...]`).

Detection des cycles : le tableau ASCII (inchange, toujours genere par
le coeur de Gunbot) reste la source de verite pour Round/Exchange/Pair/
Strategy/Timestamp. Deux modes, detectes automatiquement round par
round :
  - MODE BALISE : si un tableau est immediatement suivi d'un
    `[GBLOG:BEGIN ...]` (cf. "formatage_logs_gunbot.md" pour le format
    des balises), le corps du cycle est tout ce qui se trouve
    strictement entre ce BEGIN et le END correspondant pour la meme
    paire (recherche par paire, la plus recente ouverture d'abord :
    tolere un entrelacement reel entre plusieurs paires balisees). Les
    lignes situees entre le END d'un round et le tableau suivant ne
    sont rattachees a aucun cycle. Le `t_ms` de BEGIN/END permet de
    calculer la duree reelle de traitement du round, affichee dans
    l'en-tete du cycle en sortie.
  - MODE HERITE : en l'absence de balises, le corps du cycle est tout ce
    qui suit le tableau jusqu'au tableau suivant (pas de mesure de
    duree possible).
  Limite connue : un entrelacement reel entre une paire balisee (cycle
  encore ouvert) et une paire non balisee peut faire attribuer le
  contenu non balise au cycle balise ouvert.

Coherence paire tableau/BEGIN : si le tableau et la balise BEGIN sont en
desaccord sur la paire, le champ interne "pair" du cycle (routage par
fichier) ET la paire affichee dans le header sont corriges vers celle du
BEGIN, jugee plus fiable car explicite (round et timestamp du header
restent en revanche ceux du tableau d'origine, faute de reconstruction
fiable possible). Un marqueur
`[GBLOGS:HEADER_PAIR_OVERRIDE table_pair=... begin_pair=...]` est insere
au-dessus du header concerne ; le compteur `pair_mismatch` (.stats.json)
comptabilise l'evenement.

Coherence paire contenu : chaque ligne de contenu portant un tag court
de moteur (ex. `[maret_engine v0-1-15 [ETH]]`) est comparee a la paire du
cycle auquel elle est rattachee. En cas de desaccord, compteur
`content_pair_mismatch` incremente et marqueur
`[GBLOGS:PAIR_MISMATCH round_pair=... content_pair=...]` insere avant la
ligne concernee. Resolution court -> complet : table de correspondance
construite dynamiquement a partir des lignes portant les deux formes a
la fois (ex. `pairName="USDC-ETH"` sur la meme ligne que `[ETH]`) ;
repli sur `<quote_du_cycle>-<tag_court>` si le tag court n'a pas encore
ete vu sous forme complete.

Autres anomalies comptabilisees (sans interrompre le traitement) : les
`END` orphelins (sans `BEGIN` correspondant encore ouvert) ; les `BEGIN`
jamais refermes par un `END` en fin de fichier (round tronque) ; le
compteur `pending_meta_overwritten` (tableau ASCII ecrase par le suivant
sans avoir jamais ete rattache a un cycle).

Statistiques : un bloc d'en-tete commente en tete de chaque .txt, et un
fichier <meme_nom>.stats.json associe dans l'archive zip (nom aligne sur
celui du .txt, pour permettre l'association sans ambiguite cote
consommateur). Ces statistiques sont au niveau de l'instance (agregees
sur tous les fichiers pm2 de l'instance), pas ventilees par paire : si
plusieurs paires sont conservees pour une meme instance, le meme jeu de
compteurs est reporte dans le stats.json de chacune.

Le reste (recherche des fichiers -out par instance, selection interactive
des instances a traiter (toutes par defaut), choix explicite entre mode
journalier et mode plage precise (date+heure quelconques, y compris la
journee en cours), filtrage optionnel au 1er cycle par bougie,
separateurs simple/double, suppression des codes ANSI, ignorance des
fichiers -error, selection interactive de paire(s) si plusieurs sont
detectees) est decrit plus bas dans les fonctions correspondantes.

Sortie :
  - Une archive .zip deposee dans le meme repertoire (pm2/logs), contenant
    pour chaque instance (ou chaque instance+paire si plusieurs paires
    conservees) un fichier .txt fusionne ET son fichier de stats associe,
    nommes de facon a etre apparies sans ambiguite (meme base de nom) :
      gunbot_logs_<instance>_<date>_<heure_debut>_<heure_fin>.txt
      gunbot_logs_<instance>_<date>_<heure_debut>_<heure_fin>.stats.json
      gunbot_logs_<instance>_<paire>_<date>_<heure_debut>_<heure_fin>.txt
      gunbot_logs_<instance>_<paire>_<date>_<heure_debut>_<heure_fin>.stats.json
  - Chaque cycle balise affiche sa duree de traitement dans son en-tete :
      GB_31.5.7 USDC-XRP@hyperliquid Round #63016 2026/09/05 17:59:33  [duree: 857 ms]
  - Les fichiers sources ne sont ni modifies ni supprimes.
"""

import gzip
import os
import platform
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
import zipfile


# ─────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────

IS_WINDOWS = platform.system() == "Windows"

# Codes d'echappement ANSI (couleurs/fond ajoutes par pm2)
ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

# Ancienne ligne d'en-tete de cycle des strategies natives (ex : stepgrid).
# Purement redondante avec le tableau : filtree du corps du cycle si elle
# est rencontree, quel que soit le mode (balise ou herite).
LEGACY_HEADER_RE = re.compile(
    r'^GB[_\s]\S+\s+\S+@\S+\s+Round\s+#\d+\s+\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}$'
)

# Balises sentinelles de debut/fin de cycle (cf. formatage_logs_gunbot.md).
# Format cle=valeur libre (schema=1 : engine, strategy, exchange, mode sur
# BEGIN ; status, duration_ms sur END ; pair/t_ms toujours presents). Le
# parsing ci-dessous (GBLOG_LINE_RE + parse_gblog_line) est generique
# vis-a-vis de l'ordre et du nombre de champs presents sur la ligne : seul
# `pair` est requis, le reste est lu sans erreur mais ignore.
GBLOG_LINE_RE = re.compile(r'^\[GBLOG:(?P<kind>BEGIN|END)\s+(?P<body>.+)\]$')
GBLOG_KV_RE = re.compile(r'(?P<key>[A-Za-z_]\w*)=(?P<value>[^\s\]]+)')


def parse_gblog_line(line: str, kind: str) -> dict | None:
    """
    Parse une balise [GBLOG:BEGIN ...] ou [GBLOG:END ...] au format
    cle=valeur libre (cf. commentaire ci-dessus). Retourne un dict des
    champs presents (t_ms converti en int si numerique, sinon None) si la
    ligne correspond au type demande ('BEGIN' ou 'END') et porte un champ
    `pair`, sinon None.
    """
    m = GBLOG_LINE_RE.match(line)
    if not m or m.group("kind") != kind:
        return None
    fields = dict(GBLOG_KV_RE.findall(m.group("body")))
    if "pair" not in fields:
        return None
    t_ms_raw = fields.get("t_ms")
    fields["t_ms"] = int(t_ms_raw) if t_ms_raw is not None and t_ms_raw.isdigit() else None
    return fields

# Tag court de moteur en tete de ligne de contenu, ex :
#   [maret_engine v0-1-15 [ETH]] LOG BRUT gb.data ...
# Capture uniquement le tag court entre crochets internes ; le nom du
# moteur et le numero de version sont ignores (non necessaires ici).
CONTENT_ENGINE_TAG_RE = re.compile(
    r'^\[\S+(?:\s+v\S+)?\s+\[(?P<short>[^\]]+)\]\]'
)

# Forme complete de la paire, quand elle apparait sur la meme ligne que
# le tag court (payload JSON libre emis par le moteur) :
#   pairName="USDC-ETH" ...   ou   "pair":"USDC-ETH"
CONTENT_FULL_PAIR_RE = re.compile(
    r'pairName="(?P<full1>[^"]+)"|"pair":"(?P<full2>[^"]+)"'
)

# Nom de fichier pm2 : <instance>-out__YYYY-MM-DD_HH-MM-SS.log[.gz]
#                  ou  <instance>-error__YYYY-MM-DD_HH-MM-SS.log[.gz]
PM2_FILENAME_RE = re.compile(
    r'^(?P<instance>.+)-(?P<stream>out|error)__'
    r'(?P<ts>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.log(\.gz)?$'
)

TIMEFRAMES_HINT = ["1", "3", "5", "10", "15", "30", "60", "120", "240", "360", "720", "1440"]

SEP_SINGLE = "#" * 80
SEP_DOUBLE = "#" * 80 + "\n" + "#" * 80

# Formats de saisie acceptes pour les dates/heures utilisateur
DATETIME_FORMATS = ["%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"]
DATE_ONLY_FORMATS = ["%Y-%m-%d", "%d/%m/%Y"]


# ─────────────────────────────────────────────
# UTILITAIRES
# ─────────────────────────────────────────────

def strip_ansi(text: str) -> str:
    """Supprime les codes d'echappement ANSI (couleurs pm2)."""
    return ANSI_RE.sub("", text)


def parse_datetime_input(raw: str, is_end: bool):
    """
    Parse une saisie utilisateur en datetime.
    Accepte 'YYYY-MM-DD HH:MM:SS', 'DD/MM/YYYY HH:MM:SS',
    ou une date seule (heure forcee a 00:00:00 pour un debut,
    23:59:59 pour une fin). Retourne None si la saisie est invalide.
    """
    raw = raw.strip()
    if not raw:
        return None
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    for fmt in DATE_ONLY_FORMATS:
        try:
            d = datetime.strptime(raw, fmt)
            return d.replace(hour=23, minute=59, second=59) if is_end \
                else d.replace(hour=0, minute=0, second=0)
        except ValueError:
            continue
    return "INVALID"


def ask_processing_mode() -> bool:
    """
    Demande explicitement a l'utilisateur le mode de selection de periode
    (aucune deduction automatique a partir des heures saisies).
    Retourne True pour le mode journalier (journees completes, base sur
    les fichiers 00:00:00 de pm2), False pour le mode plage precise
    (bornes date+heure quelconques, y compris la journee en cours).
    """
    print("\nMode de selection de la periode :")
    print("  1 - Mode journalier (journees completes)")
    print("  2 - Plage precise (date + heure quelconques, y compris aujourd'hui)")
    while True:
        raw = input("Votre choix [1/2] : ").strip()
        if raw == "1":
            return True
        if raw == "2":
            return False
        print("  X Entrez 1 ou 2.")


def ask_daily_range() -> tuple[datetime, datetime]:
    """
    Mode journalier : demande les dates de debut/fin (sans heure).
    Par defaut : hier -> hier. Retourne (debut 00:00:00, fin 23:59:59).
    """
    yesterday = (datetime.now() - timedelta(days=1)).date()
    default_str = yesterday.strftime("%Y-%m-%d")

    print("\nJournee(s) a traiter (format 'YYYY-MM-DD' ou 'DD/MM/YYYY') :")
    while True:
        raw = input(f"Date de debut [{default_str}] : ")
        if not raw.strip():
            start_date = yesterday
            break
        parsed = parse_datetime_input(raw, is_end=False)
        if parsed == "INVALID" or parsed is None:
            print("  X Format invalide.")
            continue
        start_date = parsed.date()
        break

    while True:
        raw = input(f"Date de fin [{default_str}] : ")
        if not raw.strip():
            end_date = yesterday
        else:
            parsed = parse_datetime_input(raw, is_end=True)
            if parsed == "INVALID" or parsed is None:
                print("  X Format invalide.")
                continue
            end_date = parsed.date()
        if end_date < start_date:
            print("  X La date de fin doit etre posterieure a la date de debut.")
            continue
        break

    start_dt = datetime.combine(start_date, dtime(0, 0, 0))
    end_dt = datetime.combine(end_date, dtime(23, 59, 59))
    return start_dt, end_dt


def ask_precise_range() -> tuple[datetime, datetime]:
    """
    Mode plage precise : demande des bornes date+heure quelconques,
    y compris sur la journee en cours (la fin peut etre l'instant present).
    Par defaut : aujourd'hui 00:00:00 -> maintenant.
    """
    today_start = datetime.combine(datetime.now().date(), dtime(0, 0, 0))
    now = datetime.now().replace(microsecond=0)

    print("\nPeriode precise a traiter (format 'YYYY-MM-DD HH:MM:SS' ou 'DD/MM/YYYY HH:MM:SS') :")
    while True:
        raw = input(f"Date/heure de debut [{today_start.strftime('%Y-%m-%d %H:%M:%S')}] : ")
        if not raw.strip():
            start_dt = today_start
            break
        parsed = parse_datetime_input(raw, is_end=False)
        if parsed == "INVALID" or parsed is None:
            print("  X Format invalide.")
            continue
        start_dt = parsed
        break

    while True:
        raw = input(f"Date/heure de fin [{now.strftime('%Y-%m-%d %H:%M:%S')}] : ")
        if not raw.strip():
            end_dt = now
            break
        parsed = parse_datetime_input(raw, is_end=True)
        if parsed == "INVALID" or parsed is None:
            print("  X Format invalide.")
            continue
        if parsed < start_dt:
            print("  X La date de fin doit etre posterieure a la date de debut.")
            continue
        end_dt = parsed
        break

    return start_dt, end_dt


def ask_timeframe() -> int:
    """Demande a l'utilisateur le timeframe et retourne la valeur en minutes."""
    print("\nTimeframes courants (en minutes) :")
    print("  " + "  ".join(TIMEFRAMES_HINT))
    print("  (toute autre valeur entiere positive est acceptee)")
    while True:
        raw = input("Timeframe de reference (en minutes) : ").strip()
        try:
            val = int(raw)
            if val > 0:
                return val
        except ValueError:
            pass
        print("  X Valeur invalide, entrez un entier positif.")


def ask_filter_mode() -> bool:
    """
    Demande le mode de filtrage des cycles.
    Retourne True si on ne garde que le premier cycle par bougie.
    """
    print("\nFiltrage des cycles :")
    print("  1 - Conserver tous les cycles")
    print("  2 - Conserver uniquement le premier cycle apres chaque ouverture de bougie")
    while True:
        raw = input("Votre choix [1/2] : ").strip()
        if raw == "1":
            return False
        if raw == "2":
            return True
        print("  X Entrez 1 ou 2.")


def ask_pair_selection(pair_counts: "Counter[str]") -> set[str]:
    """
    Demande a l'utilisateur quelle(s) paire(s) conserver lorsque plusieurs
    paires distinctes sont detectees dans les cycles d'une meme instance.
    Retourne l'ensemble des paires a conserver.
    """
    pairs = sorted(pair_counts.keys())
    print("\n  Plusieurs paires detectees dans les logs de cette instance :")
    for idx, p in enumerate(pairs, start=1):
        print(f"    {idx} - {p} ({pair_counts[p]} cycle(s))")
    all_idx = len(pairs) + 1
    print(f"    {all_idx} - Toutes les paires (un fichier .txt distinct par paire)")
    print("    (plusieurs numeros separes par des virgules acceptes, ex : 1,3)")
    while True:
        raw = input("  Paire(s) a conserver : ").strip()
        if not raw:
            continue
        if raw == str(all_idx):
            return set(pairs)
        try:
            idxs = [int(x.strip()) for x in raw.split(",")]
            if idxs and all(1 <= x <= len(pairs) for x in idxs):
                return {pairs[x - 1] for x in idxs}
        except ValueError:
            pass
        print("    X Selection invalide.")


def ask_instance_selection(instances: list[str]) -> set[str]:
    """
    Demande a l'utilisateur quelle(s) instance(s) gunbot traiter parmi
    celles detectees sur le disque. Saisie vide ou index "toutes" ->
    toutes les instances (comportement par defaut).
    """
    print("\nInstance(s) a traiter :")
    for idx, name in enumerate(instances, start=1):
        print(f"  {idx} - {name}")
    all_idx = len(instances) + 1
    print(f"  {all_idx} - Toutes les instances (par defaut)")
    print("  (plusieurs numeros separes par des virgules acceptes, ex : 1,3)")
    while True:
        raw = input(f"Votre choix [{all_idx}] : ").strip()
        if not raw or raw == str(all_idx):
            return set(instances)
        try:
            idxs = [int(x.strip()) for x in raw.split(",")]
            if idxs and all(1 <= x <= len(instances) for x in idxs):
                return {instances[x - 1] for x in idxs}
        except ValueError:
            pass
        print("  X Selection invalide.")


def parse_cycle_timestamp(ts_str: str) -> datetime:
    """Convertit '2026/04/26 19:15:46' en objet datetime (naif, UTC implicite)."""
    return datetime.strptime(ts_str.strip(), "%Y/%m/%d %H:%M:%S")


def candle_open_time(dt: datetime, tf_minutes: int) -> datetime:
    """Retourne l'heure d'ouverture de la bougie dans laquelle tombe dt."""
    total_seconds = int(dt.timestamp())
    tf_seconds = tf_minutes * 60
    candle_start_ts = (total_seconds // tf_seconds) * tf_seconds
    return datetime.fromtimestamp(candle_start_ts, tz=timezone.utc).replace(tzinfo=None)


# ─────────────────────────────────────────────
# DECOUVERTE DES FICHIERS SUR DISQUE
# ─────────────────────────────────────────────

def scan_out_files(directory: str) -> dict[str, list[tuple[datetime, str]]]:
    """
    Parcourt le repertoire et regroupe les fichiers -out par instance.
    Les fichiers -error sont ignores.
    Retourne { instance: [(timestamp_nom_fichier, chemin_complet), ...] }
    trie par timestamp croissant pour chaque instance.
    """
    groups: dict[str, list[tuple[datetime, str]]] = {}
    for fname in os.listdir(directory):
        fpath = os.path.join(directory, fname)
        if not os.path.isfile(fpath):
            continue
        m = PM2_FILENAME_RE.match(fname)
        if not m or m.group("stream") != "out":
            continue
        instance = m.group("instance")
        ts = datetime.strptime(m.group("ts"), "%Y-%m-%d_%H-%M-%S")
        groups.setdefault(instance, []).append((ts, fpath))

    for instance in groups:
        groups[instance].sort(key=lambda t: t[0])

    return groups


def select_files_in_range(
    files: list[tuple[datetime, str]], start: datetime, end: datetime
) -> list[tuple[datetime, str]]:
    """
    Selectionne les fichiers dont l'horodatage tombe dans [start, end],
    plus le fichier le plus proche juste avant start et celui le plus
    proche juste apres end (un seul de chaque cote), s'ils existent.

    Si aucun fichier ne tombe dans [start, end], l'instance est consideree
    comme inactive sur la periode demandee : on ne va PAS chercher un
    fichier limitrophe.
    """
    in_range = [(ts, f) for ts, f in files if start <= ts <= end]
    if not in_range:
        return []

    before_candidates = [(ts, f) for ts, f in files if ts < start]
    after_candidates = [(ts, f) for ts, f in files if ts > end]

    selected = list(in_range)
    if before_candidates:
        selected.append(max(before_candidates, key=lambda t: t[0]))
    if after_candidates:
        selected.append(min(after_candidates, key=lambda t: t[0]))

    selected.sort(key=lambda t: t[0])
    return selected


def select_files_daily(
    files: list[tuple[datetime, str]], start_date, end_date
) -> list[tuple[datetime, str]] | None:
    """
    Mode journalier : le premier fichier retenu est celui date exactement
    <start_date> 00:00:00, le dernier est celui date <end_date + 1 jour>
    00:00:00, INCLUS EN TOTALITE.

    Retourne None si l'un des deux fichiers 00:00:00 attendus n'existe pas
    pour cette instance : l'appelant doit alors basculer sur le mode de
    secours (select_files_in_range).
    """
    start_midnight = datetime.combine(start_date, dtime(0, 0, 0))
    next_day_midnight = datetime.combine(end_date + timedelta(days=1), dtime(0, 0, 0))

    has_start_file = any(ts == start_midnight for ts, _ in files)
    has_next_day_file = any(ts == next_day_midnight for ts, _ in files)
    if not has_start_file or not has_next_day_file:
        return None

    selected = [
        (ts, f) for ts, f in files
        if start_midnight <= ts <= next_day_midnight
    ]
    selected.sort(key=lambda t: t[0])
    return selected


def read_file_text(filepath: str) -> str:
    """Lit un fichier de log (decompresse .gz si besoin) en texte UTF-8."""
    if filepath.endswith(".gz"):
        with gzip.open(filepath, "rb") as f:
            raw_bytes = f.read()
    else:
        with open(filepath, "rb") as f:
            raw_bytes = f.read()
    return raw_bytes.decode("utf-8", errors="replace")


# ─────────────────────────────────────────────
# PARSING DES CYCLES (tableau ASCII + balises GBLOG:BEGIN/END)
# ─────────────────────────────────────────────

def _is_table_top(line: str) -> bool:
    s = line.strip()
    return s.startswith("┌") and s.endswith("┐")


def _is_table_bottom(line: str) -> bool:
    s = line.strip()
    return s.startswith("└") and s.endswith("┘")


def extract_cycle_metadata(data_row: str) -> dict | None:
    """
    Extrait les informations de cycle (version, round, exchange, pair,
    strategy, timestamp) a partir de la 2e ligne de donnees du tableau
    ASCII (celle qui suit la ligne d'en-tetes de colonnes) :

      │                   │ GB 31.5.7  │ 63016 │ hyperliquid │ USDC-XRP │ custom/custom │ 2026/09/05 17:59:33 │

    Colonnes attendues, dans l'ordre : (label, Version, Round, Exchange,
    Pair, Strategy, Timestamp). Retourne None si la ligne ne matche pas la
    structure attendue (tableau malforme/tronque).
    """
    cells = [c.strip() for c in data_row.strip().strip("│").split("│")]
    if len(cells) != 7:
        return None
    _, version, round_s, exchange, pair, strategy, ts_s = cells
    try:
        timestamp = parse_cycle_timestamp(ts_s)
    except ValueError:
        return None
    version_num = version.replace("GB", "").strip()
    header = f"GB_{version_num} {pair}@{exchange} Round #{round_s} {ts_s}"
    return {
        "header": header,
        "timestamp": timestamp,
        "round": round_s,
        "exchange": exchange,
        "pair": pair,
        "strategy": strategy,
        "raw_key": data_row.strip(),
    }


def resolve_content_pair(
    short: str, short_pair_map: dict[str, str], cycle_pair: str | None
) -> tuple[str | None, bool]:
    """
    Resout un tag court de moteur (ex. "ETH") en paire complete.

    Retourne (paire_resolue, est_reconstruite) :
      - si le tag court a deja ete observe sous forme complete (via une
        ligne portant les deux a la fois) -> paire connue, est_reconstruite=False ;
      - sinon, si la paire du cycle courant est disponible et suit le
        format "QUOTE-BASE" -> reconstruction "<quote_du_cycle>-<short>",
        est_reconstruite=True (best-effort, non confirme par une donnee
        reellement observee) ;
      - sinon -> (None, False) : aucune comparaison possible.
    """
    known = short_pair_map.get(short)
    if known is not None:
        return known, False
    if cycle_pair and "-" in cycle_pair:
        quote = cycle_pair.split("-")[0]
        return f"{quote}-{short}", True
    return None, False


def parse_cycles(
    text: str, short_pair_map: dict[str, str] | None = None, source_label: str = ""
) -> tuple[list[dict], dict[str, int], dict[str, str]]:
    """
    Decoupe le texte brut (deja nettoye des codes ANSI) en liste de cycles.

    Mode hybride, round par round :
      - si le tableau est immediatement suivi d'un [GBLOG:BEGIN ...],
        le corps du cycle est tout ce qui se trouve entre ce BEGIN et le
        END correspondant (recherche par paire, la plus recente ouverture
        d'abord - tolere un entrelacement reel entre plusieurs paires
        balisees) ;
      - sinon, mode herite : le corps du cycle est tout ce qui suit le
        tableau jusqu'au tableau suivant.

    Chaque cycle : { header, timestamp, round, exchange, pair, strategy,
                     raw_key, body, duration_ms }
    duration_ms vaut None pour les cycles traites en mode herite (pas de
    balise -> pas de mesure de duree possible).

    short_pair_map : table de correspondance {tag_court: paire_complete}
    a reutiliser/enrichir d'un fichier a l'autre de la meme instance
    (voir collect_instance_cycles). Un nouveau dict est cree si omis.

    Retourne (cycles, stats, short_pair_map) ou stats comptabilise :
      tag_mode, legacy_mode      : nombre de cycles produits dans chaque mode
      pair_mismatch              : tableau et BEGIN en desaccord sur la paire
                                    (le cycle porte alors un marqueur
                                    GBLOGS:HEADER_PAIR_OVERRIDE au-dessus de
                                    son header)
      content_pair_mismatch      : ligne de contenu en desaccord avec la
                                    paire du cycle auquel elle est rattachee
      pending_meta_overwritten   : tableau ecrase sans jamais avoir ete
                                    rattache a un cycle
      orphan_end                 : balise END sans BEGIN ouvert correspondant
      unclosed_begin             : balise BEGIN jamais refermee (fin de fichier)
    """
    lines = text.splitlines()
    n = len(lines)
    cycles: list[dict] = []
    stats = {
        "tag_mode": 0, "legacy_mode": 0,
        "pair_mismatch": 0, "content_pair_mismatch": 0,
        "pending_meta_overwritten": 0,
        "orphan_end": 0, "unclosed_begin": 0,
    }
    if short_pair_map is None:
        short_pair_map = {}

    in_table = False
    pending_meta: dict | None = None       # meta du tableau qui vient d'etre lu
    legacy_meta: dict | None = None        # round herite en cours (sans balises)
    legacy_body: list[str] = []
    open_tag_cycles: list[dict] = []       # pile des cycles balises actuellement ouverts
    begin_counter = 0                      # discriminant pour raw_key de secours

    i = 0
    while i < n:
        raw_line = lines[i].rstrip("\r")

        if not in_table and _is_table_top(raw_line):
            # Un round herite en cours (sans balises) se termine forcement
            # au prochain tableau : on le cloture ici.
            if legacy_meta is not None:
                cycles.append({**legacy_meta, "body": legacy_body, "duration_ms": None})
                stats["legacy_mode"] += 1
                legacy_meta = None
                legacy_body = []
            elif pending_meta is not None:
                # Un tableau precedent n'a jamais ete rattache a un cycle
                # (ni BEGIN, ni contenu ne l'ayant bascule en mode herite)
                # avant l'apparition de ce nouveau tableau -> perte silencieuse.
                stats["pending_meta_overwritten"] += 1

            pending_meta = extract_cycle_metadata(lines[i + 3].rstrip("\r")) if i + 3 < n else None
            in_table = True
            i += 1
            continue

        if in_table:
            if _is_table_bottom(raw_line):
                in_table = False
            i += 1
            continue

        stripped = raw_line.strip()

        begin_fields = parse_gblog_line(stripped, "BEGIN")
        if begin_fields is not None:
            pair = begin_fields["pair"]
            t_ms = begin_fields["t_ms"]
            meta = pending_meta
            pending_meta = None
            if meta is not None and meta["pair"] != pair:
                stats["pair_mismatch"] += 1
                table_pair = meta["pair"]
                # La balise BEGIN, explicite, prevaut pour le champ interne
                # "pair" (routage par fichier). Le texte de "header" est
                # corrige de la meme facon (paire affichee = celle du
                # BEGIN), mais round et timestamp restent tels quels : ils
                # proviennent du tableau d'origine et il n'y a pas de moyen
                # fiable de les reconstituer cote gbLogs. Un marqueur est
                # pose juste au-dessus du header a l'affichage pour signaler
                # que ce round et ce timestamp restent potentiellement
                # herites du mauvais tableau, malgre la paire desormais
                # correcte.
                corrected_header = meta["header"].replace(
                    f"{table_pair}@{meta['exchange']}", f"{pair}@{meta['exchange']}", 1
                )
                meta = {
                    **meta,
                    "pair": pair,
                    "header": corrected_header,
                    "header_pair_override": {"table_pair": table_pair, "begin_pair": pair},
                }
            if meta is None:
                # Tableau absent/malforme : on retombe sur t_ms comme
                # timestamp approximatif, a defaut de mieux.
                approx_ts = datetime.fromtimestamp(t_ms / 1000) if t_ms is not None else None
                begin_counter += 1
                # Discriminant fichier+position : garantit l'unicite meme si
                # t_ms est absent, pour eviter une deduplication accidentelle
                # entre deux BEGIN distincts (voir doc de demande, section 3.3).
                meta = {
                    "header": f"pair={pair} (metadonnees tableau indisponibles)",
                    "timestamp": approx_ts,
                    "round": None, "exchange": None, "pair": pair, "strategy": None,
                    "raw_key": f"GBLOG_BEGIN:{pair}:{t_ms}:{source_label}:{begin_counter}",
                }
            open_tag_cycles.append({"meta": meta, "pair": pair, "t_begin": t_ms, "body": []})
            i += 1
            continue

        end_fields = parse_gblog_line(stripped, "END")
        if end_fields is not None:
            pair = end_fields["pair"]
            t_ms = end_fields["t_ms"]
            match_idx = None
            for k in range(len(open_tag_cycles) - 1, -1, -1):
                if open_tag_cycles[k]["pair"] == pair:
                    match_idx = k
                    break
            if match_idx is None:
                stats["orphan_end"] += 1
                i += 1
                continue
            oc = open_tag_cycles.pop(match_idx)
            duration_ms = (t_ms - oc["t_begin"]) if (t_ms is not None and oc["t_begin"] is not None) else None
            if oc["meta"].get("timestamp") is not None:
                cycles.append({**oc["meta"], "body": oc["body"], "duration_ms": duration_ms})
                stats["tag_mode"] += 1
            i += 1
            continue

        # Ligne de contenu normale (ni tableau, ni balise)
        content_line = None if LEGACY_HEADER_RE.match(stripped) else raw_line
        if content_line is not None:
            # Mise a jour opportuniste de la table court -> complet, et
            # verification de coherence avec le cycle cible (balise ou
            # herite), quel que soit le mode d'attribution retenu ensuite.
            m_tag = CONTENT_ENGINE_TAG_RE.match(stripped)
            if m_tag:
                short = m_tag.group("short")
                m_full = CONTENT_FULL_PAIR_RE.search(stripped)
                if m_full:
                    short_pair_map[short] = m_full.group("full1") or m_full.group("full2")

                target_pair = None
                if open_tag_cycles:
                    target_pair = open_tag_cycles[-1]["pair"]
                elif legacy_meta is not None:
                    target_pair = legacy_meta.get("pair")
                elif pending_meta is not None:
                    target_pair = pending_meta.get("pair")

                if target_pair is not None:
                    resolved, _ = resolve_content_pair(short, short_pair_map, target_pair)
                    if resolved is not None and resolved != target_pair:
                        stats["content_pair_mismatch"] += 1
                        marker = (
                            f"[GBLOGS:PAIR_MISMATCH round_pair={target_pair} "
                            f"content_pair={resolved}]"
                        )
                        content_line = marker + "\n" + content_line

            if open_tag_cycles:
                # Attribuee au cycle balise le plus recemment ouvert
                # (celui dont l'execution est la plus probable en cours).
                open_tag_cycles[-1]["body"].append(content_line)
            elif pending_meta is not None:
                # Premiere ligne de contenu apres un tableau non suivi
                # d'un BEGIN -> repli mode herite pour ce round.
                legacy_meta = pending_meta
                pending_meta = None
                legacy_body = [content_line]
            elif legacy_meta is not None:
                legacy_body.append(content_line)
            # sinon : ligne orpheline (avant le premier tableau, ou entre
            # un END et le tableau suivant) -> ignoree, cf. docstring.
        i += 1

    # Fin de fichier : round herite encore ouvert -> on le cloture.
    if legacy_meta is not None:
        cycles.append({**legacy_meta, "body": legacy_body, "duration_ms": None})
        stats["legacy_mode"] += 1

    # Balises BEGIN jamais refermees (fichier tronque) -> rejetees.
    stats["unclosed_begin"] += len(open_tag_cycles)

    return cycles, stats, short_pair_map


def collect_instance_cycles(filepaths: list[str]) -> tuple[list[dict], dict[str, int]]:
    """
    Lit tous les fichiers -out selectionnes pour une instance, les nettoie,
    les decoupe en cycles, fusionne le tout et trie chronologiquement.
    Deduplique les cycles identiques (meme ligne de donnees de tableau,
    ou meme cle synthetique si tableau indisponible) pouvant apparaitre a
    la frontiere entre deux fichiers issus d'une rotation pm2.

    La table court->complet (short_pair_map) est partagee et enrichie au
    fil des fichiers traites pour une meme instance, pour beneficier d'une
    correspondance deja etablie sur un fichier precedent (rotation pm2).
    """
    all_cycles: list[dict] = []
    total_stats = {
        "tag_mode": 0, "legacy_mode": 0,
        "pair_mismatch": 0, "content_pair_mismatch": 0,
        "pending_meta_overwritten": 0,
        "orphan_end": 0, "unclosed_begin": 0,
    }
    short_pair_map: dict[str, str] = {}
    for filepath in filepaths:
        text = read_file_text(filepath)
        text = strip_ansi(text)
        cycles, stats, short_pair_map = parse_cycles(
            text, short_pair_map=short_pair_map, source_label=os.path.basename(filepath)
        )
        all_cycles.extend(cycles)
        for k in total_stats:
            total_stats[k] += stats[k]

    all_cycles = [c for c in all_cycles if c.get("timestamp") is not None]
    all_cycles.sort(key=lambda c: c["timestamp"])

    deduped: list[dict] = []
    seen_keys: set[str] = set()
    for cycle in all_cycles:
        if cycle["raw_key"] in seen_keys:
            continue
        seen_keys.add(cycle["raw_key"])
        deduped.append(cycle)

    return deduped, total_stats


# ─────────────────────────────────────────────
# FILTRAGE
# ─────────────────────────────────────────────

def filter_cycles_by_candle(cycles: list[dict], tf_minutes: int) -> list[dict]:
    """
    Ne conserve que le premier cycle de chaque tranche de bougie
    (celui dont le timestamp depasse pour la premiere fois l'ouverture de la bougie).
    """
    seen: set = set()
    kept = []
    for cycle in cycles:
        key = candle_open_time(cycle["timestamp"], tf_minutes)
        if key not in seen:
            seen.add(key)
            kept.append(cycle)
    return kept


# ─────────────────────────────────────────────
# FORMATAGE DE LA SORTIE
# ─────────────────────────────────────────────

def build_stats_header(
    instance: str, pair_suffix: str | None, start_dt: datetime, end_dt: datetime,
    stats: dict[str, int], n_cycles: int
) -> str:
    """
    Bloc d'en-tete commente, place en tete du .txt de sortie. Format libre
    mais reconnaissable, sans intersection avec les regex du parser de
    niveau 2 (ENTREE/SORTIE/CB_SUMMARY/en-tete de round).
    """
    lines = [
        SEP_SINGLE,
        "# gbLogs stats (gbLogsPm2_0-13)",
        f"# instance={instance} pair={pair_suffix or '(toutes, fichier non separe par paire)'}",
        f"# periode={start_dt.strftime('%Y-%m-%d %H:%M:%S')} -> {end_dt.strftime('%Y-%m-%d %H:%M:%S')}",
        f"# cycles={n_cycles}",
        "# " + " ".join(f"{k}={v}" for k, v in stats.items()),
        SEP_SINGLE,
    ]
    return "\n".join(lines) + "\n\n"


def build_stats_json(
    instance: str, pair_suffix: str | None, start_dt: datetime, end_dt: datetime,
    stats: dict[str, int], n_cycles: int
) -> str:
    """Serialise les memes informations que build_stats_header, en JSON."""
    import json
    payload = {
        "instance": instance,
        "pair": pair_suffix,
        "periode_debut": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "periode_fin": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "cycles": n_cycles,
        "stats": stats,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_output(cycles: list[dict], tf_minutes: int, stats_header: str = "") -> str:
    """
    Construit le texte final a partir de la liste de cycles a afficher.
    sep = SEP_DOUBLE pour le premier cycle de chaque bougie, SEP_SINGLE sinon.
    Le corps de chaque cycle ne contient deja plus le tableau ASCII (jamais
    copie par parse_cycles) : pas de filtrage supplementaire necessaire ici.
    La duree de traitement (mode balise uniquement) est ajoutee en fin
    d'en-tete quand elle est disponible.
    """
    first_of_candle: set = set()
    seen: set = set()
    for c in cycles:
        key = candle_open_time(c["timestamp"], tf_minutes)
        if key not in seen:
            seen.add(key)
            first_of_candle.add(c["timestamp"])

    parts = []
    for cycle in cycles:
        sep = SEP_DOUBLE if cycle["timestamp"] in first_of_candle else SEP_SINGLE

        body = list(cycle["body"])
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()

        header = cycle["header"]
        if cycle.get("duration_ms") is not None:
            header += f"  [duree: {cycle['duration_ms']} ms]"

        override = cycle.get("header_pair_override")
        header_block = header
        if override is not None:
            marker = (
                f"[GBLOGS:HEADER_PAIR_OVERRIDE table_pair={override['table_pair']} "
                f"begin_pair={override['begin_pair']}]"
            )
            header_block = marker + "\n" + header

        block = sep + "\n" + header_block + "\n" + sep + "\n" + "\n".join(body)
        parts.append(block)

    return stats_header + "\n\n".join(parts) + "\n"


def build_output_filename(instance: str, cycles: list[dict], pair_suffix: str | None = None) -> str:
    """
    Construit le nom de fichier de sortie :
      gunbot_logs_<instance>_<date>_<heure_debut>_<heure_fin>.txt
      gunbot_logs_<instance>_<paire>_<date>_<heure_debut>_<heure_fin>.txt
    date/heures = periode couverte par les cycles reellement trouves
    (avant filtrage eventuel par bougie). pair_suffix n'est ajoute que
    lorsque plusieurs paires distinctes sont conservees pour l'instance.
    """
    start_dt = cycles[0]["timestamp"]
    end_dt = cycles[-1]["timestamp"]
    date_str = start_dt.strftime("%Y-%m-%d")
    start_str = start_dt.strftime("%H%M%S")
    end_str = end_dt.strftime("%H%M%S")
    if pair_suffix:
        return f"gunbot_logs_{instance}_{pair_suffix}_{date_str}_{start_str}_{end_str}.txt"
    return f"gunbot_logs_{instance}_{date_str}_{start_str}_{end_str}.txt"


# ─────────────────────────────────────────────
# POINT D'ENTREE
# ─────────────────────────────────────────────

def main() -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))

    print("=" * 60)
    print("  Gunbot Log Processor (pm2 / serveur)")
    print(f"  OS detecte : {'Windows' if IS_WINDOWS else platform.system()}")
    print(f"  Repertoire : {script_dir}")
    print("=" * 60)

    # 1. Scanner le repertoire pour trouver les fichiers -out par instance
    groups = scan_out_files(script_dir)
    if not groups:
        print("\nX Aucun fichier '<instance>-out__...log' trouve dans le repertoire.")
        sys.exit(1)

    all_instances = sorted(groups.keys())
    print(f"\nInstance(s) detectee(s) : {', '.join(all_instances)}")
    for instance in all_instances:
        print(f"  - {instance} : {len(groups[instance])} fichier(s) au total")

    # 2. Selection des instances a traiter (toutes par defaut)
    selected_instances = ask_instance_selection(all_instances)
    instances = [i for i in all_instances if i in selected_instances]

    # 3. Mode de selection de periode (choix explicite) puis bornes
    daily_mode = ask_processing_mode()
    if daily_mode:
        start_dt, end_dt = ask_daily_range()
    else:
        start_dt, end_dt = ask_precise_range()
    print(f"\nPeriode retenue : {start_dt.strftime('%Y-%m-%d %H:%M:%S')} "
          f"-> {end_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    if daily_mode:
        print("  Mode journalier (fichiers 00:00:00 de pm2) - "
              "repli automatique par instance si besoin.")
    else:
        print("  Mode plage precise (heures personnalisees saisies).")

    # 4. Questions utilisateur (appliquees a toutes les instances)
    tf_minutes = ask_timeframe()
    filter_mode = ask_filter_mode()

    # 5. Traitement par instance
    # L'archive zip est ouverte et alimentee au fil du traitement (chaque
    # fichier de sortie y est ecrit des qu'il est pret, puis sa chaine de
    # caracteres en memoire est liberee) plutot que d'accumuler tous les
    # contenus generes (toutes instances/paires confondues) dans une liste
    # jusqu'a la fin : sur un serveur avec beaucoup de cycles/paires, cette
    # accumulation peut epuiser la RAM disponible (processus tue par l'OOM
    # killer).
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_zip_path = os.path.join(script_dir, f"gunbot_logs_processed_{run_ts}.zip")
    written_filenames: list[str] = []

    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as out_zf:
        for instance in instances:
            if daily_mode:
                selected = select_files_daily(groups[instance], start_dt.date(), end_dt.date())
                if selected is None:
                    print(f"\n  Instance {instance} : fichier(s) 00:00:00 manquant(s) "
                          f"(instance probablement inactive a la bascule de jour) "
                          f"-> repli sur le mode plage precise pour cette instance.")
                    selected = select_files_in_range(groups[instance], start_dt, end_dt)
                else:
                    print(f"\n  Instance {instance} : mode journalier applique "
                          f"(fichiers 00:00:00 trouves).")
            else:
                selected = select_files_in_range(groups[instance], start_dt, end_dt)

            if not selected:
                print(f"  Instance {instance} : aucun fichier dans/autour de la periode, ignoree.")
                continue

            print(f"\n  Traitement de l'instance {instance} "
                  f"({len(selected)} fichier(s) selectionne(s)) :")
            for ts, fpath in selected:
                print(f"    - {os.path.basename(fpath)}")

            all_cycles, stats = collect_instance_cycles([f for _, f in selected])
            print(f"    {len(all_cycles)} cycle(s) detecte(s) "
                  f"({stats['tag_mode']} en mode balise, {stats['legacy_mode']} en mode herite).")
            if any(stats[k] for k in (
                "pair_mismatch", "content_pair_mismatch", "pending_meta_overwritten",
                "orphan_end", "unclosed_begin",
            )):
                print(f"    ! Anomalies : {stats['pair_mismatch']} desaccord(s) tableau/BEGIN sur la paire, "
                      f"{stats['content_pair_mismatch']} desaccord(s) contenu/cycle sur la paire, "
                      f"{stats['pending_meta_overwritten']} tableau(x) perdu(s) sans rattachement, "
                      f"{stats['orphan_end']} END orphelin(s), "
                      f"{stats['unclosed_begin']} BEGIN jamais referme(s) (rejetes).")

            if not all_cycles:
                print("    X Aucun cycle trouve pour cette instance, ignoree.")
                continue

            # 5bis. Selection de paire(s) si plusieurs paires distinctes
            pair_counts = Counter(c["pair"] for c in all_cycles)
            if len(pair_counts) > 1:
                print(f"    {len(pair_counts)} paire(s) distincte(s) detectee(s) : "
                      f"{', '.join(f'{p} ({n})' for p, n in sorted(pair_counts.items()))}")
                selected_pairs = ask_pair_selection(pair_counts)
            else:
                selected_pairs = set(pair_counts.keys())

            kept_cycles = [c for c in all_cycles if c["pair"] in selected_pairs]
            if not kept_cycles:
                print("    X Aucun cycle conserve apres selection de paire, instance ignoree.")
                continue

            distinct_pairs_kept = sorted(set(c["pair"] for c in kept_cycles))
            if len(distinct_pairs_kept) == 1:
                groups_by_pair = {None: kept_cycles}
            else:
                groups_by_pair = {}
                for c in kept_cycles:
                    groups_by_pair.setdefault(c["pair"], []).append(c)

            # Liberation explicite : all_cycles/kept_cycles ne sont plus
            # necessaires une fois groups_by_pair construit (evite de les
            # garder en memoire pendant le rendu, potentiellement volumineux,
            # des paires de cette instance).
            del all_cycles, kept_cycles

            for pair_suffix, group_cycles in groups_by_pair.items():
                group_cycles.sort(key=lambda c: c["timestamp"])

                if filter_mode:
                    cycles_to_render = filter_cycles_by_candle(group_cycles, tf_minutes)
                    label = pair_suffix or instance
                    print(f"    [{label}] {len(cycles_to_render)} cycle(s) conserve(s) "
                          f"apres filtrage (TF {tf_minutes} min).")
                else:
                    cycles_to_render = group_cycles

                output_filename = build_output_filename(instance, group_cycles, pair_suffix)
                period_start = group_cycles[0]["timestamp"]
                period_end = group_cycles[-1]["timestamp"]
                stats_header = build_stats_header(
                    instance, pair_suffix, period_start, period_end, stats, len(group_cycles)
                )
                content = format_output(cycles_to_render, tf_minutes, stats_header=stats_header)
                out_zf.writestr(output_filename, content)
                written_filenames.append(output_filename)
                del content

                stats_json_filename = output_filename[:-len(".txt")] + ".stats.json"
                stats_json_content = build_stats_json(
                    instance, pair_suffix, period_start, period_end, stats, len(group_cycles)
                )
                out_zf.writestr(stats_json_filename, stats_json_content)
                written_filenames.append(stats_json_filename)

            del groups_by_pair

    if not written_filenames:
        os.remove(output_zip_path)
        print("\nX Aucune instance n'a pu etre traitee.")
        sys.exit(1)

    print(f"\n  OK Archive de sortie creee : {os.path.basename(output_zip_path)}")
    for filename in written_filenames:
        print(f"    - {filename}")


if __name__ == "__main__":
    main()
