#!/bin/bash

# Function to install kubectl for Debian-based systems
install_kubectl_debian() {
    # Download the latest release of kubectl
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"

    # Move kubectl to /usr/local/bin
    sudo mv kubectl /usr/local/bin/
    sudo chmod +x /usr/local/bin/kubectl
    echo "kubectl installed successfully."

    # Add sudoers entry to allow mv and chmod commands without password for the current user
    echo "$(whoami) ALL=(ALL) NOPASSWD: /bin/mv /usr/local/bin/kubectl, /bin/chmod +x /usr/local/bin/kubectl" | sudo tee -a /etc/sudoers >/dev/null
}

# Function to install kubectl for RPM-based systems
install_kubectl_rpm() {
    # Download the latest release of kubectl
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"

    # Move kubectl to /usr/local/bin
    sudo mv kubectl /usr/local/bin/
    sudo chmod +x /usr/local/bin/kubectl

    echo "kubectl installed successfully."

    # Add sudoers entry to allow mv and chmod commands without password for the current user
    echo "$(whoami) ALL=(ALL) NOPASSWD: /bin/mv /usr/local/bin/kubectl, /bin/chmod +x /usr/local/bin/kubectl" | sudo tee -a /etc/sudoers >/dev/null
}

# Check if the OS is Debian-based or RPM-based
if [[ -e /etc/os-release ]]; then
    source /etc/os-release
    if [[ $ID == "debian" || $ID == "ubuntu" || $ID == "linuxmint" ]]; then
        echo "Detected Debian-based or Ubuntu OS."
        install_kubectl_debian
    elif [[ $ID == "centos" || $ID == "rhel" || $ID == "fedora" ]]; then
        echo "Detected RPM-based OS."
        install_kubectl_rpm
    else
        echo "Unsupported operating system: $ID"
        exit 1
    fi
else
    echo "Unable to determine the operating system."
    exit 1
fi

# Export PATH with /usr/local/bin added
export PATH=$PATH:/usr/local/bin
