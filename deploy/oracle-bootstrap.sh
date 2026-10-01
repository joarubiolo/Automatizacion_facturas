#!/usr/bin/env bash
# Ejecutar con sudo solamente en la nueva VM Ubuntu ARM de Oracle.
set -euo pipefail

if [[ "$(id -u)" != "0" ]]; then
  echo "Ejecutar: sudo bash deploy/oracle-bootstrap.sh" >&2
  exit 1
fi
. /etc/os-release
if [[ "${ID}" != "ubuntu" || "$(dpkg --print-architecture)" != "arm64" ]]; then
  echo "Este instalador requiere Ubuntu ARM64 en la VM de Oracle." >&2
  exit 1
fi

apt-get update
apt-get install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: arm64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker compose version
echo "Docker listo. Seguir ORACLE_DEPLOY.md para configurar Google e iniciar el worker."
