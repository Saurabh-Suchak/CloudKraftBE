#!/usr/bin/env bash
set -euo pipefail

TF_VERSION="1.9.8"
# Install into project-local bin/ so it persists from build → runtime on Render
BIN_DIR="$(cd "$(dirname "$0")/.." && pwd)/bin"
mkdir -p "$BIN_DIR"

if [ -f "$BIN_DIR/terraform" ]; then
    echo "Terraform already at $BIN_DIR/terraform — skipping download"
    "$BIN_DIR/terraform" version
    exit 0
fi

ARCH=$(uname -m)
case $ARCH in
    x86_64)  TF_ARCH="amd64" ;;
    aarch64) TF_ARCH="arm64" ;;
    *)       echo "Unsupported arch: $ARCH"; exit 1 ;;
esac

URL="https://releases.hashicorp.com/terraform/${TF_VERSION}/terraform_${TF_VERSION}_linux_${TF_ARCH}.zip"
echo "Downloading Terraform ${TF_VERSION} (${TF_ARCH}) from HashiCorp..."
curl -fsSL "$URL" -o /tmp/terraform.zip
unzip -o /tmp/terraform.zip -d "$BIN_DIR"
chmod +x "$BIN_DIR/terraform"
rm /tmp/terraform.zip
echo "Installed: $($BIN_DIR/terraform version)"
