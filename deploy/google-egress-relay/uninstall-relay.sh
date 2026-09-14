#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "must run as root" >&2
  exit 1
fi

if docker container inspect zhiju-google-egress >/dev/null 2>&1; then
  docker rm -f zhiju-google-egress
fi
if docker image inspect zhiju-google-egress:1 >/dev/null 2>&1; then
  docker image rm zhiju-google-egress:1
fi
if getent passwd zhiju-egress >/dev/null; then
  userdel zhiju-egress
fi
rm -f -- "/etc/ssh/sshd_config.d/90-zhiju-google-egress.conf"
if sshd -t; then
  systemctl reload ssh
fi
rm -rf -- "/var/lib/zhiju-egress"
rm -rf -- "/opt/zhiju-google-egress"

echo "zhiju Google egress relay removed"
