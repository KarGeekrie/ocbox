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
