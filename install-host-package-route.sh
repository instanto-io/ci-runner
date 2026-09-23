#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this installer with sudo" >&2
  exit 1
fi

source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test -s "${source_dir}/package-route-host.conf"
install -d -m 0755 /usr/local/sbin
install -m 0755 "${source_dir}/refresh-host-package-route.py" /usr/local/sbin/instanto-package-route
install -m 0600 "${source_dir}/package-route-host.conf" /etc/instanto-package-route.conf
install -m 0644 "${source_dir}/instanto-host-package-route.service" \
  "${source_dir}/instanto-host-package-route.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now instanto-host-package-route.timer
systemctl start instanto-host-package-route.service
systemctl is-active instanto-host-package-route.timer
