#!/bin/bash

# Function to install Kind
install_kind() {
    # Download the latest release of Kind
    curl -Lo ./kind https://kind.sigs.k8s.io/dl/latest/kind-linux-amd64

    # Move Kind to /usr/local/bin
    sudo mv ./kind /usr/local/bin/
    sudo chmod +x /usr/local/bin/kind

    echo "Kind installed successfully."
}

# Grant sudo privileges to move and chmod Kind without password
grant_sudo_privileges() {
    echo "$(whoami) ALL=(ALL) NOPASSWD: /bin/mv /usr/local/bin/kind, /bin/chmod +x /usr/local/bin/kind" | sudo tee -a /etc/sudoers >/dev/null
}

# Check if Kind is already installed
if command -v kind &>/dev/null; then
    echo "Kind is already installed."
else
    install_kind
    grant_sudo_privileges
fi
