#!/bin/bash

# Function to install packages for Debian-based systems
install_packages_debian() {
    sudo apt-get update
    sudo apt-get install -y git python3 python3-pip
}

# Function to install packages for RPM-based systems
install_packages_rpm() {
    sudo yum install -y git python3 python3-pip
}

# Function to install packages for Amazon Linux
install_packages_amzn() {
    sudo yum install -y git
    sudo yum install -y python3
    sudo yum install -y python3-pip
}

# Function to check if a package is installed
is_installed() {
    command -v "$1" >/dev/null 2>&1
}

# Check if the OS is Debian-based, RPM-based, or Amazon Linux
if [[ -e /etc/os-release ]]; then
    source /etc/os-release
    if [[ $ID == "debian" || $ID == "ubuntu" || $ID == "linuxmint" ]]; then
        echo "Detected Debian-based or Ubuntu OS."
        install_packages_debian
    elif [[ $ID == "centos" || $ID == "rhel" ]]; then
        echo "Detected RPM-based OS."
        install_packages_rpm
    elif [[ $ID == "amzn" ]]; then
        echo "Detected Amazon Linux."
        install_packages_amzn
    else
        echo "Unsupported operating system: $ID"
        exit 1
    fi
else
    echo "Unable to determine the operating system."
    exit 1
fi

# Check if Git is installed, and install it if not
if ! is_installed git; then
    echo "Git is not installed. Installing Git..."
    install_packages_"$ID"
    echo "Git installed successfully."
else
    echo "Git is already installed."
fi

# Check if Python3 is installed, and install it if not
if ! is_installed python3; then
    echo "Python3 is not installed. Installing Python3..."
    install_packages_"$ID"
    echo "Python3 installed successfully."
else
    echo "Python3 is already installed."
fi

# Check if pip3 is installed, and install it if not
if ! is_installed pip3; then
    echo "pip3 is not installed. Installing pip3..."
    install_packages_"$ID"
    echo "pip3 installed successfully."
else
    echo "pip3 is already installed."
fi

# Install packages from requirements.txt
if [[ -f "requirements.txt" ]]; then
    echo "Installing packages from requirements.txt..."
    pip3 install -r requirements.txt
    echo "Packages installed successfully."
else
    echo "requirements.txt not found. Skipping package installation."
fi
