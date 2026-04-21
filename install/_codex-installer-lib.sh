#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER="${BENTO_REPO_OWNER:-ketang}"
REPO_NAME="${BENTO_REPO_NAME:-bento}"
REPO_REF="${BENTO_REPO_REF:-main}"
ARCHIVE_URL="${BENTO_ARCHIVE_URL:-https://codeload.github.com/${REPO_OWNER}/${REPO_NAME}/tar.gz/refs/heads/${REPO_REF}}"

PLUGIN_NAMES=("bento" "trackers" "stacks")
declare -A EXTERNAL_PLUGIN_REPOS=(["bugshot"]="ketang/bugshot")
declare -A EXTERNAL_PLUGIN_REFS=(["bugshot"]="main")
INSTALL_SCOPE="${BENTO_INSTALL_SCOPE:?BENTO_INSTALL_SCOPE must be set to home or project}"
INSTALL_ROOT="${BENTO_INSTALL_ROOT:?BENTO_INSTALL_ROOT must be set}"
PLUGIN_ROOT="${BENTO_PLUGIN_ROOT:?BENTO_PLUGIN_ROOT must be set}"
MARKETPLACE_PATH="${BENTO_MARKETPLACE_PATH:?BENTO_MARKETPLACE_PATH must be set}"

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

mkdir -p "$PLUGIN_ROOT" "$(dirname "$MARKETPLACE_PATH")"

for plugin in "${PLUGIN_NAMES[@]}"; do
  src="${repo_root}/plugins/${plugin}"
  dest="${PLUGIN_ROOT}/${plugin}"
  staging="${PLUGIN_ROOT}/.${plugin}.tmp"

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

# Install external plugins from their own GitHub repos
for ext_name in "${!EXTERNAL_PLUGIN_REPOS[@]}"; do
  ext_repo="${EXTERNAL_PLUGIN_REPOS[$ext_name]}"
  ext_ref="${EXTERNAL_PLUGIN_REFS[$ext_name]:-main}"
  ext_archive="${tmpdir}/${ext_name}.tar.gz"
  ext_extract="${tmpdir}/ext-${ext_name}"
  mkdir -p "$ext_extract"

  log "downloading external plugin ${ext_name} from ${ext_repo}@${ext_ref}"
  curl -fsSL "https://codeload.github.com/${ext_repo}/tar.gz/refs/heads/${ext_ref}" -o "$ext_archive"
  tar -xzf "$ext_archive" -C "$ext_extract"

  ext_root="$(find "$ext_extract" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  if [[ -z "${ext_root}" ]]; then
    echo "unable to locate extracted root for external plugin ${ext_name}" >&2
    exit 1
  fi

  if [[ ! -f "${ext_root}/.codex-plugin/plugin.json" ]]; then
    echo "missing .codex-plugin/plugin.json in external plugin ${ext_name}" >&2
    exit 1
  fi

  dest="${PLUGIN_ROOT}/${ext_name}"
  staging="${PLUGIN_ROOT}/.${ext_name}.tmp"
  rm -rf "$staging"
  mkdir -p "$staging"
  cp -R "${ext_root}/." "$staging/"
  rm -rf "$dest"
  mv "$staging" "$dest"
done

if [[ -f "$MARKETPLACE_PATH" ]]; then
  timestamp="$(date +%Y%m%d%H%M%S)"
  backup_path="${MARKETPLACE_PATH}.bak.${timestamp}"
  cp "$MARKETPLACE_PATH" "$backup_path"
  log "backed up existing marketplace to ${backup_path}"
fi

python3 - "$repo_root" "$MARKETPLACE_PATH" "$PLUGIN_ROOT" <<'PY'
import json
import os
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
target_path = Path(sys.argv[2])
plugin_root = Path(sys.argv[3])

local_names = ("bento", "trackers", "stacks")
external_names = ("bugshot",)
bento_names = set(local_names) | set(external_names)

def local_source_path(name: str) -> str:
    relative = Path(os.path.relpath(plugin_root / name, start=target_path.parent)).as_posix()
    if relative.startswith("."):
        return relative
    return f"./{relative}"

source_plugins = []
for name in local_names:
    manifest_path = repo_root / "plugins" / name / ".codex-plugin" / "plugin.json"
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

for name in external_names:
    manifest_path = plugin_root / name / ".codex-plugin" / "plugin.json"
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

log "installed Bento plugins to ${PLUGIN_ROOT}"
log "updated Codex marketplace at ${MARKETPLACE_PATH}"
log "restart Codex if it is already running"
