#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "must run as root" >&2
  exit 1
fi

if [[ -e "/etc/systemd/system/zhiju-google-tunnel.service" ]]; then
  systemctl disable --now zhiju-google-tunnel.service
  rm -f -- "/etc/systemd/system/zhiju-google-tunnel.service"
  systemctl daemon-reload
fi
rm -f -- "/etc/zhiju/google-egress_ed25519"
rm -f -- "/etc/zhiju/google-egress_known_hosts"

echo "zhiju Google tunnel removed"
