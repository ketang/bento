#!/usr/bin/env bash
set -euo pipefail

install_root="${BENTO_PROJECT_ROOT:-${PWD}}"
raw_base_url="${BENTO_RAW_BASE_URL:-https://raw.githubusercontent.com/${BENTO_REPO_OWNER:-ketang}/${BENTO_REPO_NAME:-bento}/${BENTO_REPO_REF:-main}/install}"

BENTO_INSTALL_SCOPE="project" \
BENTO_INSTALL_ROOT="${install_root}" \
BENTO_PLUGIN_ROOT="${install_root}/plugins" \
BENTO_MARKETPLACE_PATH="${install_root}/.agents/plugins/marketplace.json" \
bash <(curl -fsSL "${raw_base_url}/_codex-installer-lib.sh")
