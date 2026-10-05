# AGENTS.md — socle partagé (Regles_agents)

Fichier unique, partagé entre tous les projets (Cursor, Claude Code,
etc.), lié par symlink à la racine de chaque projet — ne contient que
du contenu **agnostique au projet**. Le contenu spécifique à un projet
donné vit dans ce projet (ex. `.cursor/rules/00-<projet>-general.mdc` /
`.claude/rules/00-<projet>-general.md`), jamais ici.

Toute modification de ce fichier s'applique immédiatement à tous les
projets qui le symlinkent — pas de copier-coller à répercuter.

## Contexte utilisateur

- Trader professionnel, style trading algorithmique.
  Outils : Amibroker (backtest AFL), Gunbot (exécution live), Claude
  (backtests), Cursor (développement).
- Connaissance intermédiaire en programmation : PHP, JavaScript, Python,
  AFL. Connaissance intermédiaire en administration système.
- Environnement de travail : alterne Linux et Windows. LibreOffice en
  anglais.
- Langue de travail par défaut : français (bonne maîtrise de l'anglais,
  connaissance moyenne du russe).

## Convention de nommage des fichiers

- Tous les fichiers de code, changelogs et règles sont nommés en
  **minuscule**, sauf les noms d'actifs (jetons, contrats futures, etc. :
  `BTC`, `ETH`) et les noms de fichiers imposés par un outil
  (`CLAUDE.md`, `AGENTS.md`, `SKILL.md`, `README.md`).
- Piège cross-OS à connaître : un renommage qui ne change QUE la casse
  n'est pas fiable avec `git mv` sur un système de fichiers insensible à
  la casse (Windows/NTFS, macOS/APFS) — Git peut ne pas détecter le
  changement. Effectuer ce type de renommage depuis Linux (sensible à la
  casse) plutôt que Windows.

## Commits

- Avant tout `git commit` : présenter le message de commit proposé et
  attendre validation explicite de l'utilisateur avant de l'exécuter.
  Ne jamais lancer `git commit` directement sans cette étape.
- **Format du message** : en anglais, compact, une ligne par élément
  séparée par un point-virgule (`;`) — pas de paragraphe, pas de détail
  narratif. Le détail complet vit dans les changelogs du projet quand
  il en existe. Aucun résultat chiffré ni détail de mise en œuvre dans
  le message : seulement ce qui change (fichiers, périmètre, version),
  jamais les valeurs ni les effets mesurés.
- **Ne jamais ajouter de ligne d'attribution `Co-Authored-By` (ou
  équivalente) dans le message de commit.**

## Proposition de règles et de skills en cours de projet

- Un projet démarre en général sans règles propres ; elles émergent au
  fil des discussions. En fin de session, ou dès qu'un signal fort
  apparaît (correction explicite de l'utilisateur, décision actée,
  pattern qui se répète), analyser la discussion et proposer les
  règles et/ou skills qui semblent pertinents à en tirer — pas de
  proposition systématique après chaque échange mineur.
- Une règle proposée est par défaut de portée **spécifique au projet**
  (`.cursor/rules/*.mdc` + jumeau `.claude/rules/*.md`). Si elle semble
  agnostique au projet (transposable ailleurs), le signaler et proposer
  également son placement dans ce socle partagé (`AGENTS.md`) — la
  décision finale de portée revient à l'utilisateur.
- **Aucune règle ni skill n'est ajouté sans accord explicite de
  l'utilisateur.** Présenter la proposition (contenu + emplacement) et
  attendre validation avant toute écriture.

## Scripts

- Tout script (shell, PowerShell, Python, etc.) doit être versionné dans
  git et accompagné d'un changelog dédié, colocalisé avec lui. Nom :
  `<nom_du_script>.changelog.md` (même nom de base que le script, en
  minuscule, cf. convention de nommage ci-dessus) pour un script isolé ;
  `changelog_<groupe>.md` lorsqu'un même changelog couvre plusieurs
  fichiers versionnés ensemble (il liste alors, en tête, les fichiers
  couverts).
- Le changelog liste les entrées par ordre antéchronologique (la plus
  récente en premier), chacune datée (`AAAA-MM-JJ`) et décrivant le
  changement en une ligne concise. Langue : français (langue de travail
  par défaut), indépendamment de la langue anglaise des messages de
  commit.
- Toute modification fonctionnelle du script s'accompagne d'une entrée
  correspondante dans son changelog, dans le même commit.

## Diagnostic SSH sous Windows

- Sur Windows, Git Bash a son propre binaire/agent SSH, distinct de
  l'agent Windows OpenSSH natif que `git` utilise réellement via
  `core.sshCommand` — un `ssh -T git@github.com` lancé depuis Git Bash
  peut donc échouer ("Permission denied") alors que `git push`/`git
  ls-remote` fonctionnent déjà. Ne pas conclure à un problème de clé SSH
  sans avoir vérifié `core.sshCommand` et testé avec `git ls-remote`.
  Procédure complète : `ssh-windows-diagnostic.md` (même dossier).
  Ne s'applique pas à macOS/Linux.

## Portabilité Cursor / Claude Code

- Le symlink `AGENTS.md` (créé par `init_projet.ps1` sous Windows ou
  son jumeau `init_projet.sh` sous Linux/macOS) est **relatif**, pas
  absolu — un chemin absolu Windows (`C:\Users\...`) ne veut rien dire
  sous Linux et casse le lien au checkout. Prérequis pour que le lien
  survive un `git clone`/`checkout` sur l'autre OS :
  `git config --global core.symlinks true` des deux côtés (sous
  Windows, nécessite aussi le Mode Développeur actif) — sans ça, Git
  stocke le symlink comme un fichier texte ordinaire contenant le
  chemin cible, pas comme un vrai lien.
- Claude Code ne lit pas `AGENTS.md` nativement mais l'importe via un
  `CLAUDE.md` de projet (`@AGENTS.md`).
- Bug connu Cursor (non résolu à ce jour) : `AGENTS.md` peut être traité
  comme "requestable" plutôt que "toujours appliqué" quand le workspace
  est ouvert via un `.code-workspace` — vérifier si c'est le cas.
- Si un projet a des règles ciblées par dossier, leur double s'écrit
  `.cursor/rules/*.mdc` (frontmatter `globs`) côté Cursor et
  `.claude/rules/*.md` (frontmatter `paths`) côté Claude Code. Pas
  d'import fiable entre les deux formats à ce jour : dupliquer le
  contenu par paire de fichiers jumeaux, avec un pointeur croisé en tête
  de chaque fichier, et répercuter toute modification de fond dans les
  deux au même commit.
