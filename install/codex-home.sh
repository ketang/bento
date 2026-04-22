#!/usr/bin/env bash
set -euo pipefail

install_root="${HOME}"
codex_home="${CODEX_HOME:-${HOME}/.codex}"
raw_base_url="${BENTO_RAW_BASE_URL:-https://raw.githubusercontent.com/${BENTO_REPO_OWNER:-ketang}/${BENTO_REPO_NAME:-bento}/${BENTO_REPO_REF:-main}/install}"

BENTO_INSTALL_SCOPE="home" \
BENTO_INSTALL_ROOT="${install_root}" \
BENTO_PLUGIN_ROOT="${install_root}/plugins" \
BENTO_MARKETPLACE_PATH="${install_root}/.agents/plugins/marketplace.json" \
BENTO_CODEX_PLUGIN_CACHE_ROOT="${codex_home}/plugins/cache/bento" \
BENTO_CODEX_CONFIG_PATH="${codex_home}/config.toml" \
BENTO_CODEX_ENABLED_PLUGIN="bento" \
bash <(curl -fsSL "${raw_base_url}/_codex-installer-lib.sh")
