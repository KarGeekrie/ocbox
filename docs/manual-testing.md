# Tests manuels bas niveau (sans ocbox)

Deux exemples minimalistes, en dehors du package ocbox lui-même, pour tester
séparément les mécanismes de base qu'ocbox assemble (`src/ocbox/sandbox.py`,
`src/ocbox/data/`) : installer uv + OpenCode + un venv, puis isoler le réseau
avec un relai TCP↔Unix-socket. Utile pour distinguer un souci propre à ta
machine/config podman (storage, SELinux, partition) d'un souci propre à ce
que fait réellement ocbox - en retirant une couche à la fois plutôt qu'en
déboguant l'image complète d'un coup.

## Exemple 1 - uv + numpy + OpenCode, réseau normal

Le strict nécessaire pour lancer OpenCode avec les skills/agents d'ocbox et
un venv Python, sans aucune isolation réseau.

`Dockerfile` :

```dockerfile
FROM debian:bookworm-slim

# ripgrep : les outils grep/glob d'OpenCode appellent `rg`, absent sinon
# OpenCode tente de le télécharger au premier usage (échoue si pas de réseau)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl python3 ripgrep \
    && rm -rf /var/lib/apt/lists/*

# uv et l'installeur OpenCode assument bash (`set -euo pipefail`), pas sh/dash
RUN curl -LsSf https://astral.sh/uv/install.sh | bash -s -- --no-modify-path \
    && mv /root/.local/bin/uv /root/.local/bin/uvx /usr/local/bin/

RUN curl -fsSL https://opencode.ai/install | bash \
    && mv "$HOME"/.opencode/bin/opencode /usr/local/bin/opencode

# venv en dehors de /workspace : si /workspace est bind-monté par dessus,
# ça n'écrase jamais le venv (même raison que SANDBOX_UV_PROJECT_ENVIRONMENT
# dans sandbox.py)
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
RUN uv venv /opt/venv && uv pip install --python /opt/venv/bin/python numpy
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /workspace
```

Build et run (adapte `/chemin/vers/ocbox` vers ton checkout) :

```bash
podman build -t ocbox-basic-test -f Dockerfile .

podman run --rm -it \
  -v "$(pwd)":/workspace:rw \
  -v /chemin/vers/ocbox/opencode-config/agents:/root/.config/opencode/agents:ro \
  -v /chemin/vers/ocbox/opencode-config/skills:/root/.config/opencode/skills:ro \
  -v /chemin/vers/ocbox/opencode-config/opencode.jsonc:/root/.config/opencode/opencode.jsonc:ro \
  ocbox-basic-test opencode
```

`/root/...` car ce conteneur tourne en root (pas d'utilisateur dédié comme
`/home/ocbox` dans le vrai ocbox) - HOME=/root, donc c'est là qu'OpenCode
cherche ses agents/skills/config globaux.

⚠️ `opencode-config/opencode.jsonc` pointe `baseURL` vers
`http://127.0.0.1:8081/v1`, qui n'a de sens qu'avec le relai (exemple 2)
tournant en face. Sans lui, soit tu passes `--network=host` avec un LLM qui
écoute sur `127.0.0.1` côté host, soit tu modifies temporairement le
`baseURL` vers une adresse réellement joignable depuis le conteneur.

## Exemple 2 - isoler le réseau avec le relai TCP↔Unix

Le mécanisme réel d'ocbox (`src/ocbox/data/relay.py`) : le conteneur tourne
avec `--network none` (aucune carte réseau, seulement `lo`), et le seul
chemin vers l'extérieur est un socket Unix bind-monté depuis le host. Un
petit relai stdlib tourne des deux côtés du socket et fait le pont.

Ajoute au `Dockerfile` de l'exemple 1 :

```dockerfile
RUN mkdir -p /usr/local/lib/ocbox
COPY relay.py /usr/local/lib/ocbox/relay.py
COPY entrypoint.sh /usr/local/lib/ocbox/entrypoint.sh
RUN chmod +x /usr/local/lib/ocbox/entrypoint.sh

WORKDIR /workspace
ENTRYPOINT ["/usr/local/lib/ocbox/entrypoint.sh"]
```

Récupère `relay.py` tel quel depuis `src/ocbox/data/relay.py` (générique,
aucune modif nécessaire) à côté du `Dockerfile`.

`entrypoint.sh` (version basique : juste le relai LLM, sans le split
web/tui du vrai `src/ocbox/data/entrypoint.sh`) :

```sh
#!/bin/sh
set -eu

# Démarre le relai côté conteneur : port TCP local -> socket Unix partagé
python3 /usr/local/lib/ocbox/relay.py serve-tcp "127.0.0.1:8081" \
    --connect-unix /run/ocbox/llm.sock &

# Attend que le relai soit prêt avant de lancer OpenCode (sinon la 1ère
# requête au LLM part dans le vide)
i=0
until python3 -c "
import socket, sys
s = socket.socket(); s.settimeout(0.2)
sys.exit(0 if s.connect_ex(('127.0.0.1', 8081)) == 0 else 1)
" 2>/dev/null; do
    i=$((i + 1))
    [ "$i" -ge 50 ] && { echo "relay never came up" >&2; exit 1; }
    sleep 0.2
done

exec opencode "$@"
```

Côté host, avant `podman run`, démarre l'autre bout du pont - ce process
tourne avec le réseau normal du host, pas isolé, c'est lui qui parle
vraiment au LLM :

```bash
mkdir -p ./run
python3 relay.py serve-unix ./run/llm.sock --connect-tcp <ip-du-llm>:<port> &
```

Puis lance le conteneur, réseau coupé :

```bash
podman run --rm -it \
  --network none \
  -v "$(pwd)":/workspace:rw \
  -v "$(pwd)/run":/run/ocbox:rw \
  -v /chemin/vers/ocbox/opencode-config/agents:/root/.config/opencode/agents:ro \
  -v /chemin/vers/ocbox/opencode-config/skills:/root/.config/opencode/skills:ro \
  -v /chemin/vers/ocbox/opencode-config/opencode.jsonc:/root/.config/opencode/opencode.jsonc:ro \
  ocbox-basic-test
```

Cette fois `baseURL: http://127.0.0.1:8081/v1` dans `opencode.jsonc` est
cohérent : c'est exactement le port sur lequel `entrypoint.sh` fait écouter
le relai côté conteneur.

À la fin, arrête le relai host : `kill %1` (ou le pid affiché).

## Exemple 3 - servir l'UI web à travers le relai

Ajoute le service web par-dessus l'exemple 2 : un second relai, dans le
sens inverse du relai LLM (ingress au lieu d'egress), pour le port web
plutôt que le LLM - toujours sans `-p`/`--publish`, tout passe par des
sockets.

`Dockerfile` : rien à ajouter - `python3` et `opencode` sont déjà là depuis
les exemples précédents.

`entrypoint.sh` : remplace `exec opencode "$@"` de l'exemple 2 par le
service web (après le relai LLM, qui reste identique) :

```sh
: "${OPENCODE_SERVER_PASSWORD:?refusing to start web mode without a password}"

# `serve`, pas `web` : `opencode web` appelle xdg-open, absent de l'image,
# qui plante avec une stack trace au lieu de juste servir - `serve` sert
# la même UI sans ça.
opencode serve --hostname 127.0.0.1 --port 4096 >/dev/null &
OPENCODE_PID=$!

i=0
until python3 -c "
import socket, sys
s = socket.socket(); s.settimeout(0.2)
sys.exit(0 if s.connect_ex(('127.0.0.1', 4096)) == 0 else 1)
" 2>/dev/null; do
    i=$((i + 1))
    [ "$i" -ge 150 ] && { echo "opencode serve never started" >&2; exit 1; }
    sleep 0.2
done

# Web ingress : socket Unix partagé -> (relai host) -> navigateur ;
# ce côté-ci -> opencode serve. Symétrique au relai LLM, sens inverse.
python3 /usr/local/lib/ocbox/relay.py serve-unix /run/ocbox/web.sock \
    --connect-tcp "127.0.0.1:4096" &

wait "$OPENCODE_PID"
```

Côté host, en plus du relai LLM de l'exemple 2, attends que le conteneur
crée le socket web avant de démarrer le second relai (`serve-tcp` cette
fois côté host, sens inverse du relai LLM) :

```bash
mkdir -p ./run
python3 relay.py serve-unix ./run/llm.sock --connect-tcp <ip-du-llm>:<port> &

while [ ! -S ./run/web.sock ]; do sleep 0.2; done
python3 relay.py serve-tcp 127.0.0.1:8888 --connect-unix ./run/web.sock &
```

`127.0.0.1:8888` est le port que le navigateur contacte réellement.

Lance le conteneur - toujours `--network none`, aucun `-p`/`--publish`,
deux `-e` en plus pour l'auth Basic (sinon OpenCode expose l'UI sans mot
de passe) :

```bash
podman run --rm \
  --network none \
  -v "$(pwd)":/workspace:rw \
  -v "$(pwd)/run":/run/ocbox:rw \
  -v /chemin/vers/ocbox/opencode-config/agents:/root/.config/opencode/agents:ro \
  -v /chemin/vers/ocbox/opencode-config/skills:/root/.config/opencode/skills:ro \
  -v /chemin/vers/ocbox/opencode-config/opencode.jsonc:/root/.config/opencode/opencode.jsonc:ro \
  -e OPENCODE_SERVER_PASSWORD=change-moi \
  -e OPENCODE_SERVER_USERNAME=opencode \
  ocbox-basic-test
```

Puis ouvre `http://opencode:change-moi@127.0.0.1:8888` (ou juste
`127.0.0.1:8888` et rentre les identifiants dans la popup du navigateur).

Pas de `-it` ici, contrairement aux exemples 1/2 : `opencode serve` tourne
en arrière-plan, `wait "$OPENCODE_PID"` garde le conteneur vivant tant
qu'il tourne.

À la fin, arrête les deux relais host : `kill %1 %2` (ou les pids
affichés).

## Composer l'AGENTS.md global (environnement + facts + règles d'équipe)

Le vrai ocbox ne mounte jamais `opencode-config/AGENTS.md` tel quel. Il
compose un fichier par run, `_compose_global_agents_md()` (sandbox.py:431),
en concaténant trois morceaux, séparés par une ligne vide :

1. `opencode-config/environments/<environment>.md` - où l'agent tourne.
   Exactement deux fichiers, un par mode d'exécution (pas web vs tui -
   sandbox vs pas de sandbox) : `sandbox.md` si ça passe par podman
   (web *et* tui), `no-sandbox.md` pour `--no-sandbox`.
2. Un bloc de "facts" généré en Python (`_sandbox_facts()`), propre à ce
   run précis - réseau, paquets apt/uv effectivement installés, mounts
   `--mount`. Vide en `--no-sandbox` (rien à décrire).
3. `opencode-config/AGENTS.md` - les règles d'équipe, identiques dans les
   deux modes.

Volontairement pas un moteur de template (Jinja2 ou équivalent) : les
fichiers `environments/*.md` et `AGENTS.md` sont censés être édités à la
main par l'équipe en markdown pur - de la syntaxe de contrôle mélangée au
texte serait plus facile à casser en éditant, et ça ajouterait une
dépendance pour un projet volontairement stdlib-only. Le bloc facts, lui,
n'a rien de statique à templater : il dépend entièrement de l'état du
run, donc du vrai code Python de toute façon.

Reproduis le même mécanisme sur les exemples précédents avec un petit
script, sans dépendance :

```python
#!/usr/bin/env python3
"""Reprend _compose_global_agents_md() de sandbox.py, en simplifié."""
import sys
from pathlib import Path

CONFIG_DIR = Path("/chemin/vers/ocbox/opencode-config")


def sandbox_facts(apt_pkgs: list[str], uv_pkgs: list[str]) -> list[str]:
    return [
        "## This sandbox",
        "",
        "- Network: none. The only thing reachable is the LLM, through the relay.",
        "- Extra system packages: " + (", ".join(apt_pkgs) or "none") + ".",
        "- Extra Python packages (uv): " + (", ".join(uv_pkgs) or "none") + ".",
    ]


def compose(environment: str, facts: list[str]) -> str:
    sections = []
    env_file = CONFIG_DIR / "environments" / f"{environment}.md"
    if env_file.is_file():
        sections.append(env_file.read_text().strip())
    if facts:
        sections.append("\n".join(facts).strip())
    team_rules = CONFIG_DIR / "AGENTS.md"
    if team_rules.is_file():
        sections.append(team_rules.read_text().strip())
    return "\n\n".join(sections) + "\n"


if __name__ == "__main__":
    environment = sys.argv[1]  # "sandbox" ou "no-sandbox"
    facts = sandbox_facts(["git"], ["numpy"]) if environment == "sandbox" else []
    print(compose(environment, facts), end="")
```

Pour les exemples 2/3 (réseau isolé, l'analogue du vrai mode sandbox) :

```bash
python3 compose_agents_md.py sandbox > ./run/AGENTS.md
```

Pour l'exemple 1 (réseau normal, l'analogue de `--no-sandbox`) :

```bash
python3 compose_agents_md.py no-sandbox > ./run/AGENTS.md
```

Puis mount-le au même endroit que dans le vrai ocbox (`GLOBAL_AGENTS_MD_MOUNT`) :

```bash
-v "$(pwd)/run/AGENTS.md":/root/.config/opencode/AGENTS.md:ro
```

Vérifie que ça a marché avec la commande de la section suivante (le
marqueur du fichier environnement doit apparaître dans le system prompt
qu'OpenCode envoie réellement).

## Vérifier que les mounts arrivent vraiment à OpenCode

Monter un fichier au bon endroit ne prouve pas qu'OpenCode le lit ou le
prend en compte - un mauvais nom de clé dans `opencode.jsonc`, un fichier
au mauvais chemin de découverte, et OpenCode l'ignore silencieusement sans
erreur (voir le commentaire de `_generate_opencode_config` dans
`sandbox.py` : `additionalProperties=false` dans le schéma, mais le
runtime jette les clés inconnues sans le dire). Quatre vérifications
directes, chacune sur ce qu'OpenCode expose réellement, pas sur le
filesystem - reprises telles quelles de `tests/integration/test_opencode_real.py`,
la suite qui tourne contre le vrai binaire en CI.

Les trois premières ne font aucun appel LLM - lance-les directement sur
l'exemple 1 ou 2, en remplaçant le CMD :

**`opencode.jsonc` → `~/.config/opencode/opencode.jsonc`**

```bash
podman run --rm -v ... ocbox-basic-test opencode debug config
```

Imprime le JSON du config *fusionné*. Vérifie que les clés attendues du
fichier de l'équipe sont là (`provider.local.models`,
`permission.external_directory`, `share`, ...) - si une section entière
manque, soit le mount a raté, soit une clé du fichier source a une faute
de frappe qu'OpenCode a silencieusement ignorée.

**`agents/` → `~/.config/opencode/agents/`**

```bash
podman run --rm -v ... ocbox-basic-test opencode agent list
```

Chaque agent apparaît en `<nom> (primary|subagent|all)`. Vérifie que
chaque `.md` de `opencode-config/agents/` apparaît sous son nom de
fichier (sans l'extension), et qu'un fichier qui ne doit *pas* être un
agent (`README.md`) n'apparaît pas.

**`skills/` → `~/.config/opencode/skills/`**

```bash
podman run --rm -v ... ocbox-basic-test opencode debug skill
```

Liste JSON avec un champ `location` par skill, pointant vers le chemin
monté (`/root/.config/opencode/skills/<nom>/SKILL.md` dans ces exemples
basiques, `/home/ocbox/.config/opencode/skills/...` dans le vrai ocbox).
Vérifie que chaque sous-dossier de `opencode-config/skills/` contenant un
`SKILL.md` apparaît, avec le bon `location`.

**`AGENTS.md` → `~/.config/opencode/AGENTS.md`**

Pas de commande `debug` qui l'affiche directement - AGENTS.md n'est pas
interrogeable, il est juste envoyé au modèle. La seule façon fiable de
vérifier qu'il est bien reçu est de capturer la vraie requête qu'OpenCode
envoie au LLM et de regarder son system prompt. Réutilise
`tests/integration/stub_llm.py` tel quel (stdlib pur, aucune dépendance) :

```python
import sys
from pathlib import Path

sys.path.insert(0, "/chemin/vers/ocbox/tests/integration")
from stub_llm import StubLLM

with StubLLM() as llm:
    print(f"stub LLM sur 127.0.0.1:{llm.port}")
    input("lance ta session opencode pointée dessus, puis Entrée ici...")
    requests = llm.tool_requests()
    assert requests, "OpenCode n'a jamais contacté le LLM"
    system = llm.system_prompt(requests[0])
    marker = Path("/chemin/vers/ocbox/opencode-config/AGENTS.md").read_text().splitlines()[0]
    assert marker in system, "AGENTS.md de l'équipe absent du system prompt"
    print("AGENTS.md bien reçu")
```

Démarre ce script, note le port affiché, pointe `opencode.jsonc` dessus
(comme dans `_config_pointing_at` du vrai test - remplace juste le
`baseURL`), lance une session (`opencode run --model local/<un-modèle>
"salut"` suffit, pas besoin d'un vrai prompt de travail), puis appuie sur
Entrée dans le script pour qu'il vérifie.

## Pour diagnostiquer un `Permission denied` sur l'exec

Si l'exemple 1 (le plus simple, sans `--init`/`--read-only`/`--userns` ni
storage particulier) échoue déjà avec `exec ... Permission denied`, le
problème est dans le storage podman lui-même (`podman info --format
'{{.Store.GraphRoot}}'`), pas dans ce qu'ocbox ajoute par dessus - voir la
partie SELinux/`noexec` plus haut dans la conversation.

Si l'exemple 1 passe mais que le vrai `ocbox` échoue, ajoute les flags
d'ocbox un par un sur l'exemple 2 jusqu'à isoler lequel déclenche l'échec.
Delta complet entre l'exemple 2 et `build_podman_run_argv` (sandbox.py) :

| Flag/option | Exemple 2 | ocbox réel | Pourquoi |
|---|---|---|---|
| `--name` + `--label ocbox.*` | absent | présent | Identification pour `ocbox list/stop/attach` - sans impact sur l'exec |
| `--userns keep-id` | absent (root/UID0 mappé rootless par défaut) | présent | Remappe l'UID conteneur pour matcher l'UID host - fichiers écrits dans `/workspace` t'appartiennent, pas à un UID namespace arbitraire |
| `--cap-drop ALL` | absent (capabilities par défaut) | présent | Retire toutes les capabilities Linux |
| `--security-opt no-new-privileges` | absent | présent | Bloque l'escalade de privilèges |
| `--read-only` | absent (rootfs writable) | présent | Rootfs en lecture seule - rien n'est persistant hors des mounts explicites |
| `--tmpfs /tmp:rw,mode=1777` | absent | présent | Compagnon obligatoire de `--read-only` : sans ça, rien n'écrit dans `/tmp` |
| `--init` | absent | présent | Le flag qui plante sur `/dev/init` si le storage podman n'est pas exécutable |
| Volume nommé `/home/ocbox` | absent (`/root` = couche writable, perdue au `--rm`) | présent | Persistance du home (venv uv, état OpenCode) entre les runs - nécessaire *parce que* `--read-only` empêche d'écrire ailleurs |
| `-e HOME=/home/ocbox` + `XDG_*` | absent (défauts root) | présent | Pointe OpenCode/uv vers ce home persistant plutôt que `/root` |
| `--env-file` (token web) | N/A (pas de mode web ici) | présent | Secret jamais en `-e` inline (visible via `podman inspect`) |
| `-v opencode_config:/etc/ocbox/opencode.json:ro` | absent | présent | Config générée par run (override `baseURL`), séparée du `opencode.jsonc` statique de l'équipe |

Le plus pertinent pour un `Permission denied` à l'exec : `--init`,
`--read-only` et `--userns keep-id` sont les trois qui touchent à *qui peut
exécuter quoi où*. Les autres (labels, capabilities, env-vars) ne changent
rien côté exec/storage.
