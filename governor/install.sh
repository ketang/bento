#!/usr/bin/env bash
# Deliberate, pinned install of the governor (run as root from a reviewed Bento commit).
# Usage: sudo governor/install.sh   (copies to /opt/bento-governor/v1/<commit>/ and repoints `current`)
set -euo pipefail
src=$(cd "$(dirname "$0")/.." && pwd)
release=$(git -C "$src" rev-parse --short=12 HEAD)
dest=/opt/bento-governor/v1/$release
install -d "$dest"
cp -r "$src/governor" "$dest/governor"
install -d "$dest/bin"
ln -sf ../governor/bin/bento-governor-v1 "$dest/bin/bento-governor-v1"
ln -sfn "$dest" /opt/bento-governor/v1/current
ln -sf /opt/bento-governor/v1/current/bin/bento-governor-v1 /usr/local/bin/bento-governor-v1
install -m 0644 "$src/governor/systemd/bento-governor.service" /etc/systemd/system/bento-governor.service
install -m 0644 "$src/governor/polkit/org.bento.governor.policy" /usr/share/polkit-1/actions/org.bento.governor.policy
[[ -f /etc/bento-governor/v1.toml ]] || { install -d /etc/bento-governor; install -m 0644 "$src/governor/v1.toml.example" /etc/bento-governor/v1.toml; echo "edit /etc/bento-governor/v1.toml, then: systemctl enable --now bento-governor"; }
systemctl daemon-reload
echo "installed $release; restart with: systemctl restart bento-governor"
