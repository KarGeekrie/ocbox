# Revue delta fonctionnel — ocbox

> Revue fichier par fichier, méthode par méthode, du code source `src/ocbox/`,
> des Containerfiles, de la configuration `opencode-config/` et des tests,
> confrontés à ce que le `README.md` et l'`AGENTS.md` promettent.
>
> Objectif double :
> 1. **Conformité** — le code fait-il ce que la doc annonce ?
> 2. **Écarts** — le code fait-il des choses non documentées, ou la doc
>    annonce-t-elle des choses que le code ne fait pas ?
>
> Environnement de revue : Python 3.12, `pytest` **231 passed, 6 skipped**,
> `ruff check src tests` **All checks passed**, Podman rootless réel
> disponible et utilisé pour rejouer les scénarios d'isolation.
> Branche : `review/delta-fonctionnel`.

> **Statut :** chaque point ci-dessous porte son **✅ Correctif appliqué** (fichiers
> touchés + tests), livrés sur cette branche (PR
> [#8](https://github.com/KarGeekrie/ocbox/pull/8)). Après correctifs :
> `pytest` **244 passed, 6 skipped**, `ruff check src tests` clean, suite
> d'intégration Podman réelle **6 passed**.

Légende de sévérité :
🔴 bug fonctionnel ou risque sécurité · 🟠 écart doc/code notable ·
🟡 comportement surprenant / robustesse · 🟢 conforme, noté pour mémoire.

---

## Synthèse

Le cœur du projet — l'isolation réseau `--network=none` + relais Unix, le
durcissement du conteneur (`--cap-drop ALL`, `--read-only`,
`no-new-privileges`, `--userns=keep-id`), la génération d'auth web, la lecture
du `baseURL` dans `opencode.jsonc`, la composition per-mode de l'`AGENTS.md`,
la logique de mise à jour git — **fait bien ce que le README décrit**, et c'est
correctement couvert par les tests (unitaires + intégration Podman réelle).
Les vérifications dynamiques que j'ai rejouées le confirment (voir §Conformités).

Les problèmes se concentrent sur les **bords** : noms de projet non
normalisés pour Podman, résolution des chemins d'options, validation absente
des `conf.py`, et un scénario d'écriture hôte depuis un conteneur compromis.
Aucun ne remet en cause l'architecture ; deux méritent une correction avant un
usage large (🔴 #1 slug, 🔴 #2 symlink run_dir).

| # | Sévérité | Emplacement | Résumé |
|---|----------|-------------|--------|
| 1 | 🔴 | `project.py:project_slug` | Un répertoire projet avec majuscule/espace produit un nom d'image/volume/conteneur que Podman **refuse** → `ocbox` échoue |
| 2 | 🔴 | `sandbox.py` run_dir + `auth.write_env_file` | Un conteneur compromis peut planter un symlink dans `run_dir` et faire écrire ocbox (run suivant) dans un fichier hôte arbitraire |
| 3 | 🟠 | `config.py:_apply_overrides` | `EXTRA_APT_DEFAULT = "git"` (chaîne au lieu de liste) devient silencieusement `['g','i','t']` ; clés mal orthographiées ignorées sans erreur |
| 4 | 🟠 | `cli.py` (options `--agents-dir/--skills-dir/--opencode-config`) | Chemins **non résolus** : une valeur relative sans `/` est interprétée par Podman comme un **volume nommé** vide, pas comme le dossier voulu |
| 5 | 🟠 | `opencode-config/` | README/workflow parlent de skills livrés ; **aucun `SKILL.md`** n'est présent, et `opencode.jsonc` autorise des skills `code-review`/`sota-review` inexistants |
| 6 | 🟡 | `config.py` (chargement) | `ocbox.conf.py` d'un projet est du **code Python exécuté sur l'hôte** avant tout sandbox — non signalé comme surface de confiance |
| 7 | 🟡 | `sandbox.py` port LLM | Port LLM conteneur **codé en dur à 8081** ; `CONTAINER_WEB_PORT = 8081` en `conf.py` crée une collision intra-conteneur, sans garde |
| 8 | 🟡 | `--mount /` | Basename vide → montage `/mnt/` et permission `"/mnt//**"` ; pas de garde sur le basename vide |
| 9 | 🟡 | `update_check.check` | `OCBOX_SKIP_UPDATE_CHECK=0` **désactive** aussi le check (test de vérité brute) ; README ne documente que `=1` |
| 10 | 🟡 | `check_opencode_args` | `--port`/`--hostname` refusés **aussi en TUI** alors qu'ocbox ne les fixe pas dans ce mode ; message d'erreur inexact pour TUI |
| 11 | 🟢 | Containerfiles + `_find_or_install_opencode` | `curl \| bash` de uv/OpenCode **sans vérification d'intégrité** (installeur amont sans checksum) — délibéré et documenté « unpinned », noté pour la chaîne d'appro |
| 12 | 🟢 | cycle de rebuild | Chaque update reconstruit la base en `--no-cache` → **images orphelines** s'accumulent (1,4 Go reclaimable observés) ; pas de purge documentée |

---

## Conformités vérifiées (le code fait ce que dit le README)

Rejoué dynamiquement, pas seulement lu :

- 🟢 **`--network=none` + relais** : `build_podman_run_argv` pose bien
  `--network none`, aucun `-p`/`--publish`, et le test d'intégration prouve
  qu'un conteneur de la même image ne peut pas joindre `1.1.1.1:80` tandis que
  le LLM et l'UI web transitent par les seules sockets Unix. Conforme à
  « How the isolation works ».
- 🟢 **Durcissement** : `--cap-drop ALL`, `--security-opt no-new-privileges`,
  `--read-only`, `--tmpfs /tmp`, `--userns keep-id`, `--init` tous présents.
  J'ai confirmé dans un conteneur réel avec les flags d'ocbox que `git` est
  absent, que le reste du FS est en lecture seule, et que `--userns keep-id`
  rend les fichiers de `/workspace` propriété de l'utilisateur hôte.
- 🟢 **Auth web** : token frais par run, `--env-file` (jamais de secret en
  `-e` inline), fichier `0600` créé atomiquement, `entrypoint.sh` **fail-closed**
  si mot de passe vide (`: "${OPENCODE_SERVER_PASSWORD:?...}"`). Le test
  d'intégration vérifie 401/200. Conforme à la section « Auth ».
- 🟢 **`serve` et non `web`** : `entrypoint.sh` lance `opencode serve` (pas
  `web`, qui appellerait `xdg-open` absent), drop du stdout de bannière,
  attente de port. Conforme à « Verified against real OpenCode ».
- 🟢 **Lecture du `baseURL`** : `llm_endpoint()` lit
  `provider.local.options.baseURL`, refuse `https` et les placeholders, dérive
  le relais `http://127.0.0.1:<port><path>`. `run()` échoue **avant** tout
  travail d'image si le baseURL est inutilisable (testé).
- 🟢 **`conf.py` refuse `LLM_HOST`/`LLM_PORT`** avec un message pointant vers
  `opencode.jsonc` (global et projet). Conforme.
- 🟢 **AGENTS.md composé par mode** : ordre environnement → faits → règles
  d'équipe ; `sandbox.md` en sandbox, `no-sandbox.md` en `--no-sandbox` ;
  jamais le mauvais environnement. `chat`/`review` décrivent un rôle sans
  environnement. Conforme à « Workflow » et aux agents.
- 🟢 **`--no-sandbox`** : trouve OpenCode sur PATH/`~/.opencode/bin`/`.ocbox/bin`,
  sinon installe avec `--no-modify-path` sous un `HOME` jetable dans `.ocbox/`
  (j'ai confirmé sur l'installeur amont qu'il code en dur `$HOME/.opencode/bin`
  et honore bien `--no-modify-path`), déplace le binaire, ne touche pas les rc
  shell, purge `OPENCODE_CONFIG`, `execvpe` OpenCode. Conforme au README.
- 🟢 **Mise à jour git** : tag `v*` plus récent → run refusé ; commits sans tag
  → notice seulement ; version = `git describe` du checkout (pas les métadonnées
  d'install) ; fetch une fois/jour ; `update_command` = pull + pip. Suite de
  tests sur de vrais dépôts git. Conforme à « Updating ».
- 🟢 **`--mount`** : chaque dossier atterrit en `/mnt/<basename>:rw`,
  indépendant, basenames distincts imposés (CLI + `RunPlan.__post_init__`), et
  ocbox ajoute `"/mnt/<basename>/**": "allow"` fusionné aux règles d'équipe
  (test d'intégration : `/etc/hostname` reste refusé, `/mnt/extra` autorisé).
- 🟢 **Rebuild base `--no-cache`** : `ensure_base_image` passe bien
  `no_cache=True` (sinon la couche `curl|bash` recyclerait les vieux uv/OpenCode).
  Le fingerprint inclut la révision ocbox. Conforme.
- 🟢 **Passthrough `--` / refus en mode web** : `split_opencode_args` coupe au
  premier `--`, garde les suivants pour OpenCode ; web refuse tout passthrough.
- 🟢 **Dépendances runtime stdlib only** : `pyproject.toml` `dependencies = []`,
  `rich` seulement en extra `pretty` (et jamais importé — voir note §Divers).
  Conforme à la convention AGENTS.md.

---

## Détail des écarts

### 🔴 1 — Un nom de projet avec majuscule ou espace fait échouer ocbox
**`src/ocbox/project.py:10` (`project_slug`) → `sandbox.py:433,483,484`**

`project_slug` construit `f"{cwd.resolve().name}-{digest}"` en réutilisant le
nom du dossier **verbatim**. Ce slug sert ensuite à nommer l'image
(`ocbox/project-{slug}:latest`), le conteneur (`ocbox-{slug}`) et le volume
(`ocbox-home-{slug}`). Or Podman impose :
- noms de dépôt **en minuscules** uniquement ;
- noms de volume/conteneur restreints à `[a-zA-Z0-9][a-zA-Z0-9_.-]*`.

Vérifié :
```
$ podman build -t ocbox/project-MyApp-0123456789ab:latest ...
Error: invalid reference format: repository name must be lowercase
$ podman volume create "ocbox-home-mes projets-abc"
Error: names must match [a-zA-Z0-9][a-zA-Z0-9_.-]*: invalid argument
```
`project_slug(Path("MyApp"))` → `MyApp-0059af1ab31c` ;
`project_slug("mes projets")` → contient une espace. Le premier `ocbox` lancé
depuis `~/projects/MyApp` (cas très courant) échouera au build d'image avec une
erreur Podman brute. Le README (« cd ~/projects/myapp ») n'utilise que du
minuscule, donc le problème est invisible dans la doc.

**✅ Correctif appliqué** — `src/ocbox/project.py` : `project_slug` met le nom
en minuscules et remplace toute suite de caractères hors `[a-z0-9]` par `-`
(strip des `-` de bord) avant d'ajouter le hash ; si le préfixe est vide, le
slug est le hash seul. Le hash sha256 continue de garantir l'unicité par chemin
même quand deux noms se normalisent pareil.
Tests : `tests/test_project.py::test_project_slug_normalises_uppercase_and_spaces`
et `::test_project_slug_still_unique_when_prefixes_collapse_together`.

---

### 🔴 2 — Écriture hôte arbitraire via un symlink planté dans `run_dir`
**`src/ocbox/network.py:106` (teardown) + `src/ocbox/auth.py:28` (`write_env_file`) + `sandbox.py`**

`run_dir` (`$XDG_RUNTIME_DIR/ocbox/<slug>`) est monté **rw** dans le conteneur
en `/run/ocbox`, et `--userns=keep-id` fait que le processus conteneur a le
**même uid** que l'hôte : il peut donc y créer des fichiers *et* `chmod` le
dossier. Scénario (rejoué) :

1. Un OpenCode compromis dans le sandbox exécute
   `ln -sf /home/kar/.bashrc /run/ocbox/env ; chmod 500 /run/ocbox`.
2. Fin de run : `teardown_bridges` fait `shutil.rmtree(run_dir, ignore_errors=True)`.
   Avec le dossier en `0500`, la suppression **échoue silencieusement** ; le
   symlink survit.
3. Run suivant : `auth.write_env_file(run_dir/"env", token)` ouvre le chemin
   avec `os.open(..., O_CREAT|O_WRONLY|O_TRUNC)` — qui **suit le symlink** et
   écrit le contenu env dans `~/.bashrc`.

Rejoué en laboratoire (fichier victime dans le scratchpad, jamais le vrai
`.bashrc`) :
```
run_dir survives teardown: True | symlink survives: True
victim now: ['OPENCODE_SERVER_USERNAME=opencode', 'OPENCODE_SERVER_PASSWORD=tok']
```
Le contenu du fichier hôte a été remplacé.

C'est un primitive d'écriture hôte limitée (contenu = variables d'auth, cible
choisie par l'attaquant), qui suppose un conteneur déjà compromis + un second
run — mais c'est précisément la frontière que le projet promet de tenir
(« Only these sandboxed modes protect the host machine »).

**✅ Correctif appliqué** (défense en profondeur) :
- `src/ocbox/auth.py` : `write_env_file` fait `os.unlink` puis
  `os.open(..., O_CREAT|O_EXCL|O_WRONLY|O_NOFOLLOW)` → ne suit plus un symlink.
- `src/ocbox/sandbox.py` : nouveau helper `_write_private()` (même schéma
  unlink + `O_NOFOLLOW|O_EXCL`) utilisé pour l'écriture de `opencode.json` et
  de l'`AGENTS.md` composé ; le log de `--detach` (`daemonize`) ouvre aussi son
  fichier avec `O_NOFOLLOW`.
- `src/ocbox/project.py` : `runtime_dir` réaffirme `0700` même sur un dossier
  déjà existant, pour qu'un `/run/ocbox` remis en `0500` par le conteneur ne
  bloque plus le nettoyage du teardown.

Tests : `tests/test_sandbox_run.py::test_run_writes_generated_files_without_following_a_planted_symlink`
et `tests/test_project.py::test_runtime_dir_reasserts_private_perms_on_an_existing_dir`.
*(Restent hors périmètre de ce correctif, à considérer plus tard : monter les
fichiers générés individuellement en `:ro` plutôt que tout le run dir en `:rw`.)*

---

### 🟠 3 — `conf.py` : pas de validation de type ni des clés
**`src/ocbox/config.py:50` (`_apply_overrides`)**

Chaque option est lue par `hasattr(module, NAME)` puis coercée. Deux pièges,
tous deux rejoués :
- `EXTRA_APT_DEFAULT = "git"` (chaîne) → `list("git")` → `['g','i','t']`.
  Trois « paquets » invalides passés à `apt-get install`, échec de build
  opaque. Idem `EXTRA_UV_DEFAULT`.
- `MEMORY_LIMITS = "2g"` (faute de frappe pour `MEMORY_LIMIT`) → **ignoré
  silencieusement**, `memory_limit` reste `None`. L'utilisateur croit avoir
  plafonné la mémoire.

C'est exactement le type de « feature qui ne fait rien silencieusement » que
l'AGENTS.md du projet dit vouloir éviter côté OpenCode ; ici c'est côté ocbox.
Le README liste les clés mais ne prévient d'aucun garde-fou.

**✅ Correctif appliqué** — `src/ocbox/config.py` :
- helper `_string_list()` : `EXTRA_APT_DEFAULT`/`EXTRA_UV_DEFAULT` doivent être
  des listes/tuples ; une chaîne (ou autre) lève une `ConfigError` explicite
  (`must be a list … e.g. ["git"]`).
- toute variable `ALL_CAPS` du module conf.py absente de `KNOWN_SETTINGS`
  (et non déjà rejetée par `MOVED_TO_OPENCODE_JSONC`) déclenche un avertissement
  sur stderr nommant la clé et suggérant les clés valides.

Tests : `tests/test_config.py::test_extra_apt_default_as_a_bare_string_is_rejected`,
`::test_extra_uv_default_as_a_bare_string_is_rejected`,
`::test_unrecognised_setting_is_ignored_with_a_warning`,
`::test_known_settings_do_not_warn`.

---

### 🟠 4 — `--agents-dir` / `--skills-dir` / `--opencode-config` non résolus
**`src/ocbox/cli.py:152` vs `:185-217`**

`--mount` est bien résolu (`p.resolve()`), pas les trois autres chemins de
dossier, passés tels quels dans `RunPlan` puis dans `-v <val>:<dest>:ro`.
Podman interprète un `-v NAME:/dest` où `NAME` ne contient pas de `/` comme un
**volume nommé**, pas un bind-mount. Rejoué :
```
$ podman create -v agents-review-probe:/x:ro ...
Mount: volume agents-review-probe -> /x   (volume nommé créé, dossier vide)
```
Donc `ocbox --tui --agents-dir agents` (relatif, sans `./`) monterait un volume
vide au lieu du dossier `agents/`, et OpenCode ne verrait aucun agent — sans
erreur. Un chemin absolu fonctionne, mais rien ne l'impose ni ne le documente.

**✅ Correctif appliqué** — `src/ocbox/cli.py` : avant tout le reste, `main()`
fait `.resolve()` sur `--agents-dir`/`--skills-dir`/`--opencode-config` fournis
et vérifie l'existence de la cible (`is_dir()` pour les deux dossiers,
`is_file()` pour la config), avec un message d'erreur nommant le flag ; la
valeur absolue est réécrite dans `args` avant d'être transmise à `run()`/
`run_no_sandbox()`.
Tests : `tests/test_cli.py::test_main_rejects_agents_dir_that_is_not_a_directory`,
`::test_main_rejects_opencode_config_that_is_not_a_file`,
`::test_main_resolves_agents_dir_to_an_absolute_path`.

---

### 🟠 5 — Skills annoncés mais aucun livré ; permissions vers des skills fantômes
**`opencode-config/skills/` et `opencode-config/opencode.jsonc:121-126`**

- `opencode-config/skills/` ne contient qu'un `README.md` : **zéro `SKILL.md`**.
  Le README (« Default skills & agents », workflow étape 3) et le titre de
  section suggèrent des skills d'équipe fournis ; en pratique aucun n'est là.
  (Ce n'est pas faux au mot près — le README dit surtout « comment en écrire » —
  mais c'est trompeur.)
- `opencode.jsonc` autorise `~/.config/opencode/skills/code-review/*` et
  `.../sota-review/*` en `external_directory`, or ces skills n'existent nulle
  part dans le dépôt. Config résiduelle pointant vers des dossiers absents.

**✅ Correctif appliqué** — `opencode-config/opencode.jsonc` : les deux entrées
`allow` vers `code-review`/`sota-review` sont retirées ; `external_directory` ne
garde que `"*": "deny"`, avec un commentaire rappelant que `--mount` ajoute les
`"/mnt/<name>/**": "allow"` par run. (Retrait sans effet fonctionnel : elles
autorisaient des dossiers de skills inexistants.) Le point « aucun `SKILL.md`
livré » n'est pas un bug de code — laissé tel quel ; le README documente
« comment en écrire ».

---

### 🟡 6 — `ocbox.conf.py` d'un projet = code exécuté sur l'hôte
**`src/ocbox/config.py:38` (`_load_module_from_path`)**

`load_config` importe et **exécute** `~/.config/ocbox/conf.py` *et* le
`ocbox.conf.py` du répertoire courant. Rejoué : un `ocbox.conf.py` contenant
`pathlib.Path(...).write_text(...)` s'exécute sur l'hôte au simple lancement
d'`ocbox`, **avant** toute création de sandbox.

C'est un choix légitime (conf.py Python), mais cela signifie que faire
`cd` dans un dépôt tiers puis lancer `ocbox` exécute le code arbitraire de ce
dépôt hors sandbox. Le README présente `conf.py` comme « settings » sans
signaler cette surface de confiance. À noter d'autant que l'outil vise
justement à se protéger de code non fiable.

**✅ Correctif appliqué** — `README.md` (section conf.py) : encadré signalant
que les deux `conf.py` sont du Python **exécuté sur l'hôte** avant tout sandbox
— le `ocbox.conf.py` d'un projet s'exécute au simple `cd` + `ocbox` — et
invitant à traiter le `ocbox.conf.py` d'un dépôt non fiable comme tout code
qu'on s'apprête à lancer. *(Le passage à un format déclaratif type TOML est
volontairement laissé de côté : changement de surface plus large, à décider par
l'équipe.)*

---

### 🟡 7 — Port LLM conteneur codé en dur, collision possible avec le port web
**`src/ocbox/sandbox.py:457` (`container_llm_port = 8081`)**

Le port LLM *dans* le conteneur est figé à `8081` ; le port web *dans* le
conteneur vient de `cfg.container_web_port` (défaut 4096, réglable). Rien ne
vérifie qu'ils diffèrent : `CONTAINER_WEB_PORT = 8081` en `conf.py` est accepté
sans erreur (rejoué), et les deux relais de l'`entrypoint.sh` tenteraient de
lier `127.0.0.1:8081` dans le conteneur → conflit et run non fonctionnel.

**✅ Correctif appliqué** — `src/ocbox/sandbox.py` : le port LLM devient la
constante de module `CONTAINER_LLM_PORT` (8081), et `run()` lève une
`ConfigError` claire en mode web si `cfg.container_web_port == CONTAINER_LLM_PORT`,
avant tout travail d'image.
Test : `tests/test_sandbox_run.py::test_run_rejects_a_web_port_colliding_with_the_llm_relay_port`.

---

### 🟡 8 — `--mount /` produit un basename vide
**`src/ocbox/cli.py:157` + `sandbox.py:135,288`**

`Path("/").name` est `""`. Rejoué : `--mount /` donne `-v /:/mnt/:rw` et une
permission `"/mnt//**": "allow"`. La collision de basenames est bien gardée,
mais pas le basename vide. Cas extrême (monter `/` est déjà absurde), mais
mérite un rejet explicite.

**✅ Correctif appliqué** — `src/ocbox/cli.py` : la boucle de validation des
`--mount` refuse désormais un chemin sans basename (`not path.name`) avec un
message dédié.
Test : `tests/test_cli.py::test_main_rejects_mount_without_a_basename`.

---

### 🟡 9 — `OCBOX_SKIP_UPDATE_CHECK=0` désactive aussi le check
**`src/ocbox/update_check.py:134`**

`if os.environ.get("OCBOX_SKIP_UPDATE_CHECK")` est vrai pour toute valeur non
vide, `"0"`/`"false"` inclus (rejoué : `=0` → check ignoré). Idiome courant,
mais le README ne parle que de `=1` ; un utilisateur posant `=0` pour
« réactiver » obtiendrait l'inverse.

**✅ Correctif appliqué** — `README.md` (section Updating) : précise que **toute
valeur non vide** désactive le check (`=0` et `=false` compris) et qu'il faut
*retirer* la variable pour le réactiver. Sémantique inchangée (documentation),
pour ne pas casser les usages existants qui posent une valeur quelconque.

---

### 🟡 10 — `--port`/`--hostname` refusés en TUI sans raison réelle
**`src/ocbox/sandbox.py:221` (`check_opencode_args`)**

En mode `tui`, l'entrypoint fait `exec opencode "$@"` : ocbox **ne fixe pas**
`--port`/`--hostname`. Pourtant `check_opencode_args` les refuse aussi en TUI
avec le message « `--port` is set by ocbox … it would detach OpenCode from the
relay » — inexact pour ce mode (le TUI n'a pas de relais web). Sur-restriction
bénigne, mais le message induit en erreur. (Le TUI OpenCode nu n'accepte de
toute façon pas `--port`, donc pas de perte de fonctionnalité.)

**✅ Correctif appliqué** — `src/ocbox/sandbox.py` : le refus est conservé (garde
défensive) mais le message ne prétend plus que « ocbox les fixe » dans
l'invocation courante ; il explique qu'ocbox contrôle la liaison d'OpenCode (en
mode web il les pose pour le brancher au relais) et renvoie vers `--web-port`.
Le test existant `test_check_opencode_args_rejects_flags_ocbox_owns` reste vert.

## Notes diverses (non bloquantes)

- 🟢 **11 — Chaîne d'appro `curl | bash`** : les Containerfiles et
  `_find_or_install_opencode` installent uv et OpenCode via `curl … | bash`
  **sans checksum ni signature** (confirmé sur l'installeur amont : aucune
  vérification d'intégrité). C'est cohérent avec le choix « unpinned »
  documenté, et l'AGENTS.md justifie le « stdlib only » pour réduire la surface
  de confiance — mais il y a une tension : la dépendance runtime est minimale
  tandis que le contenu de l'image dépend d'un script distant non vérifié. À
  garder en tête pour un durcissement futur (pin de version + checksum).
- 🟢 **12 — Images orphelines** : chaque update reconstruit la base en
  `--no-cache`, laissant l'ancienne base et les images projet en dangling.
  `podman system df` sur la machine de dev montre 115 images / 1,47 Go
  « 100% reclaimable ». **✅ Correctif appliqué** — `README.md` (section Updating)
  documente désormais l'accumulation et pointe `podman image prune` /
  `podman system prune` (ocbox ne supprime jamais d'image lui-même).
- 🟢 **`rich`** est déclaré en extra `pretty` mais **jamais importé** dans
  `src/` — extra mort (inoffensif).
- 🟢 **Auto-cohérence `opencode.jsonc`** : le fichier se signale lui-même deux
  incohérences de modèles (clé `Qwen3.8-27B-medium` dont le `name` dit
  `smart-think`). Déjà annotées par les auteurs, non traitées ici.
- 🟢 **Couverture de tests** : chaque module de `src/ocbox/` a son
  `tests/test_<module>.py` (convention AGENTS.md respectée), `run()` est bien
  couvert par mocking, et l'intégration Podman couvre isolation/relais/auth/
  ownership/TUI/fail-closed. Aucun module orphelin de test constaté.

---

*Revue produite sur la branche `review/delta-fonctionnel`. Les scénarios 🔴/🟠
ont été rejoués dynamiquement (Podman rootless réel, exécution du code ocbox,
WebFetch de l'installeur OpenCode) et non seulement lus.*
