#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER="${BENTO_REPO_OWNER:-ketang}"
REPO_NAME="${BENTO_REPO_NAME:-bento}"
REPO_REF="${BENTO_REPO_REF:-main}"
ARCHIVE_URL="${BENTO_ARCHIVE_URL:-https://codeload.github.com/${REPO_OWNER}/${REPO_NAME}/tar.gz/refs/heads/${REPO_REF}}"

# Populated after the archive is extracted, from the build-generated
# plugins/codex/plugin-names.txt manifest. See load_plugin_names below.
PLUGIN_NAMES=()
INSTALL_SCOPE="${BENTO_INSTALL_SCOPE:?BENTO_INSTALL_SCOPE must be set to home or project}"
INSTALL_ROOT="${BENTO_INSTALL_ROOT:?BENTO_INSTALL_ROOT must be set}"
PLUGIN_ROOT="${BENTO_PLUGIN_ROOT:?BENTO_PLUGIN_ROOT must be set}"
MARKETPLACE_PATH="${BENTO_MARKETPLACE_PATH:?BENTO_MARKETPLACE_PATH must be set}"
CODEX_PLUGIN_CACHE_ROOT="${BENTO_CODEX_PLUGIN_CACHE_ROOT:-}"
CODEX_CONFIG_PATH="${BENTO_CODEX_CONFIG_PATH:-}"
CODEX_ENABLED_PLUGIN="${BENTO_CODEX_ENABLED_PLUGIN:-bento}"
CODEX_ENABLED_PLUGINS=()

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required command: $1" >&2
    exit 1
  fi
}

log() {
  printf '[bento-install:%s] %s\n' "$INSTALL_SCOPE" "$1"
}

require_cmd curl
require_cmd tar
require_cmd python3

add_codex_enabled_plugin() {
  local plugin="$1"
  local existing
  if [[ -z "$plugin" ]]; then
    return 0
  fi
  for existing in "${CODEX_ENABLED_PLUGINS[@]}"; do
    if [[ "$existing" == "$plugin" ]]; then
      return 0
    fi
  done
  CODEX_ENABLED_PLUGINS+=("$plugin")
}

add_codex_enabled_plugin "$CODEX_ENABLED_PLUGIN"

tmpdir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmpdir"
}
trap cleanup EXIT

archive_path="${tmpdir}/bento.tar.gz"
extract_dir="${tmpdir}/extract"
mkdir -p "$extract_dir"

log "downloading ${REPO_OWNER}/${REPO_NAME}@${REPO_REF}"
curl -fsSL "$ARCHIVE_URL" -o "$archive_path"
tar -xzf "$archive_path" -C "$extract_dir"

repo_root="$(find "$extract_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
if [[ -z "${repo_root}" ]]; then
  echo "unable to locate extracted repository root" >&2
  exit 1
fi

plugin_names_manifest="${repo_root}/plugins/codex/plugin-names.txt"
if [[ ! -f "${plugin_names_manifest}" ]]; then
  echo "missing Codex plugin manifest: ${plugin_names_manifest}" >&2
  exit 1
fi
mapfile -t PLUGIN_NAMES < <(grep -v '^[[:space:]]*$' "${plugin_names_manifest}")
if [[ "${#PLUGIN_NAMES[@]}" -eq 0 ]]; then
  echo "Codex plugin manifest is empty: ${plugin_names_manifest}" >&2
  exit 1
fi

mkdir -p "$PLUGIN_ROOT" "$(dirname "$MARKETPLACE_PATH")"

for plugin in "${PLUGIN_NAMES[@]}"; do
  src="${repo_root}/plugins/codex/${plugin}"
  dest="${PLUGIN_ROOT}/${plugin}"
  staging="${PLUGIN_ROOT}/.${plugin}.tmp"

  if [[ ! -d "${src}" ]]; then
    # Plugin has no Codex-compatible content; skip silently.
    continue
  fi

  if [[ ! -f "${src}/.codex-plugin/plugin.json" ]]; then
    echo "missing published plugin bundle for ${plugin}" >&2
    exit 1
  fi

  rm -rf "$staging"
  mkdir -p "$staging"
  cp -R "${src}/." "$staging/"
  rm -rf "$dest"
  mv "$staging" "$dest"
done

seed_agent_plugins_handoff() {
  local source_template="${PLUGIN_ROOT}/bento/skills/handoff/references/templates/handoff.md"
  if [[ ! -f "$source_template" ]]; then
    return 0
  fi
  local agent_plugins_root
  case "$INSTALL_SCOPE" in
    home)
      agent_plugins_root="${XDG_CONFIG_HOME:-$INSTALL_ROOT/.config}/agent-plugins"
      ;;
    project)
      agent_plugins_root="${INSTALL_ROOT}/.agent-plugins"
      ;;
    *)
      return 0
      ;;
  esac
  local target_dir="${agent_plugins_root}/bento/bento/handoff"
  local target_file="${target_dir}/template.md"
  if [[ -f "$target_file" ]]; then
    log "agent-plugins handoff template already present at ${target_file}"
    return 0
  fi
  mkdir -p "$target_dir"
  cp "$source_template" "$target_file"
  log "seeded agent-plugins handoff template at ${target_file}"
}

seed_agent_plugins_handoff

declare -A CODEX_CACHE_KEYS=()
if [[ -n "$CODEX_PLUGIN_CACHE_ROOT" && "${#CODEX_ENABLED_PLUGINS[@]}" -gt 0 ]]; then
  for plugin in "${CODEX_ENABLED_PLUGINS[@]}"; do
    src="${PLUGIN_ROOT}/${plugin}"
    if [[ ! -f "${src}/.codex-plugin/plugin.json" ]]; then
      echo "missing installed plugin bundle for Codex cache: ${plugin}" >&2
      exit 1
    fi

    cache_key="$(python3 - "$src" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = root / ".codex-plugin" / "plugin.json"
payload = manifest.read_bytes()
print(hashlib.sha1(payload).hexdigest())
PY
)"
    plugin_cache_dir="${CODEX_PLUGIN_CACHE_ROOT}/${plugin}"
    dest="${plugin_cache_dir}/${cache_key}"
    staging="${CODEX_PLUGIN_CACHE_ROOT}/.${plugin}.tmp"

    mkdir -p "$CODEX_PLUGIN_CACHE_ROOT"
    rm -rf "$staging"
    mkdir -p "$staging"
    cp -R "${src}/." "$staging/"
    rm -rf "$plugin_cache_dir"
    mkdir -p "$plugin_cache_dir"
    mv "$staging" "$dest"
    CODEX_CACHE_KEYS["$plugin"]="$cache_key"
  done
fi

if [[ -f "$MARKETPLACE_PATH" ]]; then
  timestamp="$(date +%Y%m%d%H%M%S)"
  backup_path="${MARKETPLACE_PATH}.bak.${timestamp}"
  cp "$MARKETPLACE_PATH" "$backup_path"
  log "backed up existing marketplace to ${backup_path}"
fi

python3 - "$repo_root" "$MARKETPLACE_PATH" "$PLUGIN_ROOT" "${PLUGIN_NAMES[@]}" <<'PY'
import json
import os
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
target_path = Path(sys.argv[2])
plugin_root = Path(sys.argv[3])

local_names = tuple(sys.argv[4:])
bento_names = set(local_names)

def local_source_path(name: str) -> str:
    relative = Path(os.path.relpath(plugin_root / name, start=target_path.parent)).as_posix()
    if relative.startswith("./"):
        return relative
    return f"./{relative}"

source_plugins = []
for name in local_names:
    manifest_path = repo_root / "plugins" / "codex" / name / ".codex-plugin" / "plugin.json"
    if not manifest_path.exists():
        continue
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    interface = manifest.get("interface", {})
    source_plugins.append(
        {
            "name": name,
            "source": {
                "source": "local",
                "path": local_source_path(name),
            },
            "policy": {
                "installation": "AVAILABLE",
                "authentication": "ON_INSTALL",
            },
            "category": interface.get("category", "Coding"),
        }
    )

if target_path.exists():
    try:
        target = json.loads(target_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        target = {}
else:
    target = {}

if not isinstance(target, dict):
    target = {}

plugins = target.get("plugins")
if not isinstance(plugins, list):
    plugins = []

kept = [entry for entry in plugins if not isinstance(entry, dict) or entry.get("name") not in bento_names]
merged = kept + source_plugins

if "name" not in target:
    target["name"] = "bento"

interface = target.get("interface")
if not isinstance(interface, dict):
    interface = {}
if "displayName" not in interface:
    interface["displayName"] = "Bento for Codex"
if interface:
    target["interface"] = interface

target["plugins"] = merged
target_path.parent.mkdir(parents=True, exist_ok=True)
target_path.write_text(json.dumps(target, indent=2) + "\n", encoding="utf-8")
PY

if [[ -n "$CODEX_CONFIG_PATH" && "${#CODEX_ENABLED_PLUGINS[@]}" -gt 0 ]]; then
  mkdir -p "$(dirname "$CODEX_CONFIG_PATH")"
  if [[ -f "$CODEX_CONFIG_PATH" ]]; then
    timestamp="$(date +%Y%m%d%H%M%S)"
    backup_path="${CODEX_CONFIG_PATH}.bak.${timestamp}"
    cp "$CODEX_CONFIG_PATH" "$backup_path"
    log "backed up existing Codex config to ${backup_path}"
  fi

  plugin_ids=()
  for plugin in "${CODEX_ENABLED_PLUGINS[@]}"; do
    plugin_ids+=("${plugin}@bento")
  done

  python3 - "$CODEX_CONFIG_PATH" "${plugin_ids[@]}" <<'PY'
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
plugin_ids = sys.argv[2:]

text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
lines = text.splitlines()

for plugin_id in plugin_ids:
    section = f'[plugins."{plugin_id}"]'
    section_index = None
    for index, line in enumerate(lines):
        if line.strip() == section:
            section_index = index
            break

    if section_index is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([section, "enabled = true"])
    else:
        next_section = len(lines)
        for index in range(section_index + 1, len(lines)):
            stripped = lines[index].strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                next_section = index
                break

        enabled_index = None
        for index in range(section_index + 1, next_section):
            if lines[index].split("=", 1)[0].strip() == "enabled":
                enabled_index = index
                break

        if enabled_index is None:
            lines.insert(section_index + 1, "enabled = true")
        else:
            lines[enabled_index] = "enabled = true"

config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
fi

log "installed Bento plugins to ${PLUGIN_ROOT}"
if [[ -n "$CODEX_PLUGIN_CACHE_ROOT" && "${#CODEX_CACHE_KEYS[@]}" -gt 0 ]]; then
  for plugin in "${CODEX_ENABLED_PLUGINS[@]}"; do
    if [[ -n "${CODEX_CACHE_KEYS[$plugin]:-}" ]]; then
      log "installed ${plugin}@bento to Codex plugin cache at ${CODEX_PLUGIN_CACHE_ROOT}/${plugin}/${CODEX_CACHE_KEYS[$plugin]}"
    fi
  done
fi
log "updated Codex marketplace at ${MARKETPLACE_PATH}"
if [[ -n "$CODEX_CONFIG_PATH" && "${#CODEX_ENABLED_PLUGINS[@]}" -gt 0 ]]; then
  for plugin in "${CODEX_ENABLED_PLUGINS[@]}"; do
    log "enabled ${plugin}@bento in Codex config at ${CODEX_CONFIG_PATH}"
  done
fi
log "restart Codex if it is already running"
