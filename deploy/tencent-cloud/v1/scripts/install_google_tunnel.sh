#!/usr/bin/env bash
set -euo pipefail

readonly unit_name="zhiju-google-tunnel.service"
readonly unit_path="/etc/systemd/system/${unit_name}"
readonly key_path="/etc/zhiju/google-egress_ed25519"
readonly hosts_path="/etc/zhiju/google-egress_known_hosts"
readonly listen_port="17888"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "must run as root" >&2
  exit 1
fi
if [[ "$#" -ne 2 || ! -f "$1" || ! -f "$2" ]]; then
  echo "usage: $0 PRIVATE_KEY_FILE KNOWN_HOSTS_FILE" >&2
  exit 1
fi
command -v ssh >/dev/null || { echo "ssh is required" >&2; exit 1; }
command -v ss >/dev/null || { echo "ss is required" >&2; exit 1; }
getent passwd zhiju >/dev/null || { echo "zhiju user is required" >&2; exit 1; }
if [[ -e "$unit_path" || -e "$key_path" || -e "$hosts_path" ]]; then
  echo "dedicated Google tunnel resource already exists" >&2
  exit 1
fi
if ss -H -ltn | awk '{print $4}' | grep -Eq "(^|:|\\])${listen_port}$"; then
  echo "port $listen_port is already in use" >&2
  exit 1
fi

install -d -o root -g zhiju -m 0750 /etc/zhiju
install -o root -g zhiju -m 0640 "$1" "$key_path"
install -o root -g zhiju -m 0640 "$2" "$hosts_path"
install -o root -g root -m 0644 \
  "$script_dir/../zhiju-google-tunnel.service" "$unit_path"
systemctl daemon-reload
systemctl enable --now zhiju-google-tunnel.service

for _ in {1..20}; do
  if ss -H -ltn | awk '{print $4}' | grep -Eq "127\\.0\\.0\\.1:${listen_port}$"; then
    echo "Google tunnel ready on 127.0.0.1:${listen_port}"
    exit 0
  fi
  sleep 0.5
done

systemctl status "$unit_name" --no-pager >&2 || true
echo "Google tunnel did not open 127.0.0.1:${listen_port}" >&2
exit 1
