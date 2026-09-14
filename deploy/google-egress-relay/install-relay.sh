#!/usr/bin/env bash
set -euo pipefail

readonly install_root="/opt/zhiju-google-egress"
readonly service_user="zhiju-egress"
readonly service_home="/var/lib/zhiju-egress"
readonly image_name="zhiju-google-egress:1"
readonly container_name="zhiju-google-egress"
readonly listen_port="17888"
readonly ssh_dropin="/etc/ssh/sshd_config.d/90-zhiju-google-egress.conf"

if [[ "${EUID}" -ne 0 ]]; then
  echo "must run as root" >&2
  exit 1
fi
if [[ "$#" -ne 1 || ! -f "$1" ]]; then
  echo "usage: $0 PUBLIC_KEY_FILE" >&2
  exit 1
fi
command -v docker >/dev/null || { echo "docker is required" >&2; exit 1; }
command -v ss >/dev/null || { echo "ss is required" >&2; exit 1; }

public_key="$(tr -d '\r\n' < "$1")"
if [[ ! "$public_key" =~ ^ssh-ed25519\  ]]; then
  echo "public key must be one ssh-ed25519 key" >&2
  exit 1
fi
if getent passwd "$service_user" >/dev/null; then
  echo "user $service_user already exists" >&2
  exit 1
fi
if docker container inspect "$container_name" >/dev/null 2>&1; then
  echo "container $container_name already exists" >&2
  exit 1
fi
if docker image inspect "$image_name" >/dev/null 2>&1; then
  echo "image $image_name already exists" >&2
  exit 1
fi
if ss -H -ltn | awk '{print $4}' | grep -Eq "(^|:|\\])${listen_port}$"; then
  echo "port $listen_port is already in use" >&2
  exit 1
fi
if [[ -e "$install_root" || -e "$service_home" ]]; then
  echo "dedicated relay path already exists" >&2
  exit 1
fi
if [[ -e "$ssh_dropin" ]]; then
  echo "dedicated SSH drop-in already exists" >&2
  exit 1
fi

useradd --system --create-home --home-dir "$service_home" \
  --shell /usr/sbin/nologin "$service_user"
install -d -o root -g root -m 0755 "$install_root"
install -o root -g root -m 0644 Dockerfile tinyproxy.conf google-domains.filter "$install_root/"
install -o root -g root -m 0755 uninstall-relay.sh "$install_root/"
install -d -o "$service_user" -g "$service_user" -m 0700 "$service_home/.ssh"
printf '%s %s\n' \
  'restrict,port-forwarding,permitopen="127.0.0.1:17888"' \
  "$public_key" > "$service_home/.ssh/authorized_keys"
chown "$service_user:$service_user" "$service_home/.ssh/authorized_keys"
chmod 0600 "$service_home/.ssh/authorized_keys"

ssh_dropin_tmp="$(mktemp)"
trap 'rm -f -- "$ssh_dropin_tmp"' EXIT
printf '%s\n' \
  'Match User zhiju-egress' \
  '    PubkeyAuthentication yes' \
  '    PasswordAuthentication no' \
  '    AllowTcpForwarding local' \
  '    PermitOpen 127.0.0.1:17888' \
  '    PermitTTY no' \
  '    X11Forwarding no' \
  '    AllowAgentForwarding no' \
  '    PermitTunnel no' \
  'Match all' > "$ssh_dropin_tmp"
install -o root -g root -m 0644 "$ssh_dropin_tmp" "$ssh_dropin"
if ! sshd -t; then
  rm -f -- "$ssh_dropin"
  echo "dedicated SSH configuration is invalid" >&2
  exit 1
fi
systemctl reload ssh

docker build --tag "$image_name" "$install_root"
docker run --detach \
  --name zhiju-google-egress \
  --restart unless-stopped \
  --network host \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=8m \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 64 \
  --memory 128m \
  --cpus 0.5 \
  "$image_name"

for _ in {1..20}; do
  if ss -H -ltn | awk '{print $4}' | grep -Eq "127\\.0\\.0\\.1:${listen_port}$"; then
    echo "relay ready on 127.0.0.1:${listen_port}"
    exit 0
  fi
  sleep 0.25
done

echo "relay did not open 127.0.0.1:${listen_port}" >&2
docker logs "$container_name" >&2 || true
exit 1
