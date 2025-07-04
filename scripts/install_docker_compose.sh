#!/bin/bash

set -e

COMPOSE_VERSION="v2.32.0"
BINARY_URL="https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64"
DEST_PATH="/usr/local/bin/docker-compose"

echo "🔍 Detecting OS..."

# Detect OS family
if [ -f /etc/debian_version ]; then
    OS_FAMILY="debian"
elif [ -f /etc/redhat-release ]; then
    OS_FAMILY="redhat"
else
    echo "❌ Unsupported OS. This script works only on Debian/Ubuntu and RHEL/CentOS."
    exit 1
fi

echo "✅ Detected $OS_FAMILY-based system"

# Install curl if not present
if ! command -v curl >/dev/null 2>&1; then
    echo "📦 Installing curl..."
    if [ "$OS_FAMILY" = "debian" ]; then
        sudo apt update && sudo apt install -y curl
    elif [ "$OS_FAMILY" = "redhat" ]; then
        sudo yum install -y curl
    fi
fi

# Download docker-compose binary
echo "📥 Downloading Docker Compose $COMPOSE_VERSION..."
sudo curl -SL "$BINARY_URL" -o "$DEST_PATH"

# Make it executable
echo "🔧 Setting permissions..."
sudo chmod +x "$DEST_PATH"

# Create symlink
echo "🔗 Creating symlink to /usr/bin/docker-compose..."
sudo ln -sf "$DEST_PATH" /usr/bin/docker-compose

# Verify installation
echo "✅ Installed Docker Compose version:"
docker-compose version
