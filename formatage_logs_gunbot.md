# Format universel des logs de stratégie Gunbot — balisage par paire

## Objectif

Permettre à `gbLogsPm2` d'attribuer sans ambiguïté chaque ligne de log
"corps" à la bonne paire, quelle que soit la stratégie custom en cours
d'exécution, et malgré le fait qu'en mode websockets le code de plusieurs
paires peut s'exécuter de façon entrelacée entre deux tableaux ASCII
(un `await` sur une paire peut se résoudre pendant qu'une autre paire
imprime déjà son tableau).

Ce document sert de référence à appliquer, dans un projet dédié, au code
source de n'importe quelle stratégie custom Gunbot (`maret_engine`,
`maret_gunbot`, ou toute stratégie future), pour la rendre compatible
avec gbLogs.

**Cas gunmaster (moteur unifié `trading_engine.js`, depuis 0-2-3)** : les
balises BEGIN/END décrites ci-dessous sont émises automatiquement par le
moteur (`runTradingCycle()`), avec un schéma enrichi (cf. "Syntaxe exacte"
plus bas) — un auteur de stratégie gunmaster (`maret.js`, `fvg.js`, ou
toute stratégie future respectant le contrat `onCycle`/`onClosedCandle`/
`formatEvent`) n'a **rien à faire lui-même** pour ce balisage, le moteur
restant seul responsable de l'en-tête/pied de cycle. Ce document reste la
référence du FORMAT à respecter (utile pour `gbLogsPm2` et pour toute
stratégie custom hors du moteur unifié, qui devrait alors le faire
elle-même comme décrit ci-dessous) mais ne décrit plus une obligation
d'implémentation pour les stratégies gunmaster.

## Principe

- Le tableau ASCII (RT Edition), généré par le cœur de Gunbot et **jamais
  modifié**, reste la seule source de vérité pour Round / Exchange / Pair
  / Strategy / Timestamp.
- Le code custom de la stratégie doit encadrer l'intégralité de ses propres
  logs (et uniquement les siens) par deux balises sentinelles fixes,
  identiques pour toutes les stratégies :

```
[GBLOG:BEGIN pair=USDC-XRP t_ms=1725263842123]
...(logs spécifiques à la stratégie — contenu libre, non normé)...
[GBLOG:END pair=USDC-XRP t_ms=1725263842980]
```

Le contenu entre les deux balises n'a pas à être uniformisé : il peut
varier librement d'une stratégie à l'autre. Seules les balises comptent
pour le découpage par gbLogs.

Le timestamp `t_ms` permet à gbLogs de calculer la durée réelle de
traitement de chaque round (`END.t_ms - BEGIN.t_ms`), utile pour repérer
les rounds anormalement longs (typiquement ceux interrompus puis achevés
en retard à cause d'un `await` websocket) et pour détecter les balises
mal fermées (durée négative ou aberrante).

## Syntaxe exacte

- Forme générale, clé=valeur, un champ `schema=<N>` obligatoire (permet à
  un parser existant de détecter un changement de forme plutôt que de mal
  interpréter silencieusement un nouveau champ) :
  `[GBLOG:BEGIN schema=<N> <clé>=<valeur> ...]` et
  `[GBLOG:END schema=<N> <clé>=<valeur> ...]`
- Seul le champ `pair` est **requis** par `gbLogsPm2` pour l'attribution
  par paire ; `t_ms` reste nécessaire pour le calcul de durée (voir
  ci-dessous). Tout autre champ est optionnel côté parsing : `gbLogsPm2`
  (depuis la version `0-11`) lit la ligne de façon générique et ignore les
  champs qu'il ne connaît pas, sans erreur — ni l'ordre ni le nombre de
  champs présents ne sont contraints.
- **Schéma `schema=1`** (celui actuellement émis par `trading_engine.js`
  gunmaster, depuis 0-2-3) :
  - `BEGIN` : `schema`, `engine` (version du moteur), `strategy` (nom de
    la stratégie), `pair`, `exchange`, `mode` (`test`/`production`),
    `t_ms`.
  - `END` : `schema`, `pair`, `status` (`ok`/`exception`), `duration_ms`
    (déjà calculé côté moteur — informatif ; `gbLogsPm2` recalcule sa
    propre durée à partir des `t_ms` de BEGIN/END, indépendamment de ce
    champ), `t_ms`.

  Exemple réel (gunmaster 0-2-3+) :
  ```
  [GBLOG:BEGIN schema=1 engine=0-2-3 strategy=maret pair=USDC-XRP exchange=hyperliquid mode=production t_ms=1725263842123]
  ...
  [GBLOG:END schema=1 pair=USDC-XRP status=ok duration_ms=857 t_ms=1725263842980]
  ```
- `<PAIR>` = exactement la valeur affichée dans la colonne "Pair" du
  tableau ASCII pour ce round (ex. `USDC-XRP`, `USDC-HYPE`) — aucune
  transformation, aucune abréviation.
- `<EPOCH_MS>` (`t_ms`) = timestamp OS en **millisecondes depuis epoch**
  au moment précis de l'exécution de la ligne (`Date.now()` en JS,
  `time.time()*1000` en Python, etc.). Pas de format ISO : on veut une
  simple soustraction d'entiers pour calculer la durée, sans ambiguïté de
  fuseau horaire. Ce timestamp est un chrono de performance, distinct du
  timestamp "métier" à la seconde affiché dans le tableau ASCII.
- La ligne ne doit contenir **que** la balise, rien d'autre avant ou après.
- Un seul `BEGIN` et un seul `END` par round, jamais imbriqués. Plusieurs
  paires peuvent en revanche avoir un `BEGIN` ouvert simultanément
  (websockets), c'est normal et attendu.
- Historique : le schéma simple `[GBLOG:BEGIN pair=<PAIR> t_ms=<EPOCH_MS>]`
  (0-7 à gunmaster 0-2-2, sans `schema=`) reste reconnu par `gbLogsPm2`
  (0-11+), comme cas particulier du parsing générique ci-dessus — mais
  n'est plus le format émis par gunmaster depuis 0-2-3.

## Règles de placement dans le code

*(Cette section et l'exemple ci-dessous s'adressent à une stratégie custom
qui n'utilise PAS le moteur unifié gunmaster — pour une stratégie
gunmaster, cf. la note en introduction : le moteur émet déjà BEGIN/END
lui-même, avec le schéma `schema=1` décrit plus haut.)*

1. **BEGIN** : première instruction de log exécutée à l'entrée de la
   fonction de stratégie pour ce round, avant tout autre `console.log` /
   `print` (avant les logs `WS_DEBUG`, `LOG BRUT`, etc. s'ils sont émis
   par le code custom lui-même).
2. **END** : dernière instruction de log exécutée avant que la fonction
   ne rende la main à Gunbot (juste avant que le cœur de Gunbot n'imprime
   son propre `reached end of user code`).
3. **Obligatoire : englober tout le corps de la fonction dans un
   `try { ... } finally { console.log(END) }`** (ou équivalent dans le
   langage utilisé), pour garantir que `END` est émis même en cas
   d'exception ou de retour anticipé. Un round sans `END` correspondant
   est traité par gbLogs comme un cycle anormalement inachevé.
4. Ne toucher à **aucune** variable, condition ou calcul métier : ce sont
   des lignes de log pures, purement additives.
5. Ne pas modifier le tableau ASCII lui-même ni son format.

## Exemple avant / après (schématique)

Avant :
```js
async function runStrategy(pair) {
  // ... logs WS_DEBUG, LOG BRUT, calculs, décisions ...
  console.log("Position: [...] ...");
}
```

Après :
```js
async function runStrategy(pair) {
  console.log(`[GBLOG:BEGIN pair=${pair} t_ms=${Date.now()}]`);
  try {
    // ... logs WS_DEBUG, LOG BRUT, calculs, décisions (inchangés) ...
    console.log("Position: [...] ...");
  } finally {
    console.log(`[GBLOG:END pair=${pair} t_ms=${Date.now()}]`);
  }
}
```

## Erreurs à éviter

- Ne pas placer BEGIN/END dans un code appelé pour plusieurs paires à la
  fois (un seul round = un seul BEGIN/END).
- Des champs additionnels dans la balise sont désormais admis (schéma
  `schema=1`, cf. "Syntaxe exacte") tant que `pair` reste présent et que
  `schema` est incrémenté si la forme change — mais round/timestamp/
  exchange restent inutiles pour `gbLogsPm2` : ils sont déjà fiables via
  le tableau ASCII, ne pas les dupliquer sans raison.
- Ne pas oublier le `finally` : un `END` manquant après une exception
  casse le découpage pour toutes les paires suivantes tant que gbLogs n'a
  pas de mécanisme de récupération dédié.

## Checklist rapide avant de livrer une stratégie modifiée

- [ ] `BEGIN` est la toute première ligne de log du round.
- [ ] `END` est émis dans un `finally`, donc toujours exécuté.
- [ ] `<PAIR>` correspond exactement à la colonne "Pair" du tableau ASCII.
- [ ] `t_ms` est un timestamp OS en millisecondes (epoch), pas un format ISO.
- [ ] Aucune ligne de log custom n'est émise avant `BEGIN` ou après `END`.
- [ ] Aucune logique métier n'a été modifiée, uniquement des lignes de log ajoutées.
