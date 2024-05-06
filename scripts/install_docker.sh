#!/bin/bash

# Function to install Docker for Debian-based systems
install_docker_debian() {
    # Add Docker's official GPG key
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc

    # Add the repository to Apt sources
    echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
    $(lsb_release -cs) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update

    # Install Docker
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io

    # Add the current user to the Docker group
    sudo usermod -aG docker $USER
    sudo chmod 666 /var/run/docker.sock

    # Restart Docker service
    sudo systemctl restart docker

    echo "Docker installed successfully. Please log out and log back in for the changes to take effect."
}

# Function to install Docker for RPM-based systems
install_docker_rpm() {
    # Install prerequisite packages
    sudo yum install -y yum-utils

    # Add the repository to Yum sources
    sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo

    # Install Docker
    sudo yum install -y docker-ce docker-ce-cli containerd.io

    # Start Docker service
    sudo systemctl start docker

    # Enable Docker service to start on boot
    sudo systemctl enable docker

    # Add the current user to the Docker group
    sudo usermod -aG docker $USER

    echo "Docker installed successfully."
}

# Function to install Docker for Amazon Linux
install_docker_amzn() {
    # Update packages
    sudo yum update -y

    # Install Docker
    sudo yum install -y docker 

    # Start Docker service
    sudo systemctl start docker

    # Enable Docker service to start on boot
    sudo systemctl enable docker

    # Add the current user to the Docker group
    sudo usermod -aG docker $USER

    # Adjust permissions for the Docker socket
    sudo chmod 666 /var/run/docker.sock

    echo "Docker installed successfully."
}

# Check if the OS is Debian-based, RPM-based, or Amazon Linux
if [[ -e /etc/os-release ]]; then
    source /etc/os-release
    if [[ $ID == "debian" || $ID == "ubuntu" || $ID == "linuxmint" ]]; then
        echo "Detected Debian-based or Ubuntu OS."
        install_docker_debian
    elif [[ $ID == "centos" || $ID == "rhel" ]]; then
        echo "Detected RPM-based OS."
        install_docker_rpm
    elif [[ $ID == "amzn" ]]; then
        echo "Detected Amazon Linux."
        install_docker_amzn
    else
        echo "Unsupported operating system: $ID"
        exit 1
    fi
else
    echo "Unable to determine the operating system."
    exit 1
fi
