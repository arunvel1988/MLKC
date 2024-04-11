#!/bin/bash

# Function to install Helm for Debian-based systems
install_helm_debian() {
    # Download the latest release of Helm
    curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3

    # Make get_helm.sh executable
    chmod +x get_helm.sh

    # Run the Helm installation script
    ./get_helm.sh

    echo "Helm installed successfully."
}


# Function to install Helm for RPM-based systems
install_helm_rpm() {
    # Download the latest release of Helm
    curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3

    # Make get_helm.sh executable
    chmod +x get_helm.sh

    # Run the Helm installation script
    ./get_helm.sh

    echo "Helm installed successfully."
}

# Check if the OS is Debian-based or RPM-based
if [[ -e /etc/os-release ]]; then
    source /etc/os-release
    if [[ $ID == "debian" || $ID == "ubuntu" || $ID == "linuxmint" ]]; then
        echo "Detected Debian-based or Ubuntu OS."
        install_helm_debian
    elif [[ $ID == "centos" || $ID == "rhel" || $ID == "fedora" ]]; then
        echo "Detected RPM-based OS."
        install_helm_rpm
    else
        echo "Unsupported operating system: $ID"
        exit 1
    fi
else
    echo "Unable to determine the operating system."
    exit 1
fi
