#!/bin/bash

# Function to detect the Linux distribution
detect_linux_distribution() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "$ID"
    else
        echo "Unable to detect Linux distribution."
        exit 1
    fi
}

# Function to add the current user to sudoers with NOPASSWD
add_user_to_sudoers() {
    local user=$(whoami)
    local sudoers_file="/etc/sudoers.d/$user"

    echo "$user ALL=(ALL) NOPASSWD: ALL" | sudo tee "$sudoers_file" > /dev/null
    sudo chmod 0440 "$sudoers_file"
}



# Install Tekton CLI
install_tekton_cli() {
    DISTRO=$(detect_linux_distribution)
    if [ "$DISTRO" == "ubuntu" ] || [ "$DISTRO" == "debian" ]; then
        sudo apt update
        sudo apt install -y curl
        curl -LO https://github.com/tektoncd/cli/releases/download/v0.23.0/tektoncd-cli-0.23.0_Linux-64bit.deb
        sudo dpkg -i tektoncd-cli-0.23.0_Linux-64bit.deb
        rm tektoncd-cli-0.23.0_Linux-64bit.deb
    elif [ "$DISTRO" == "centos" ] || [ "$DISTRO" == "fedora" ] || [ "$DISTRO" == "amzn" ]; then
        sudo yum install -y curl
        curl -LO https://github.com/tektoncd/cli/releases/download/v0.23.0/tektoncd-cli-0.23.0_Linux-64bit.rpm
        sudo rpm -ivh tektoncd-cli-0.23.0_Linux-64bit.rpm
        rm tektoncd-cli-0.23.0_Linux-64bit.rpm
    else
        echo "Unsupported Linux distribution. Please install Tekton CLI manually."
        exit 1
    fi
}

# Download and apply YAML files
apply_yaml() {
    local yaml_url=$1
    local yaml_file=$(basename "$yaml_url")
    local tools_dir="tools"

    mkdir -p "$tools_dir"
    curl -L -o "$tools_dir/$yaml_file" "$yaml_url"
    kubectl apply -f "$tools_dir/$yaml_file"
}

# Install Tekton Pipelines
install_tekton_pipelines() {
    apply_yaml "https://storage.googleapis.com/tekton-releases/pipeline/latest/release.yaml"
}

# Install Tekton Dashboard
install_tekton_dashboard() {
    apply_yaml "https://storage.googleapis.com/tekton-releases/dashboard/latest/release.yaml"
}

# Install Tekton Triggers
install_tekton_triggers() {
    apply_yaml "https://storage.googleapis.com/tekton-releases/triggers/latest/release.yaml"
    apply_yaml "https://storage.googleapis.com/tekton-releases/triggers/latest/interceptors.yaml"
}

# Main script
add_user_to_sudoers

echo "Installing Tekton CLI..."
install_tekton_cli

echo "Installing Tekton Pipelines..."
install_tekton_pipelines

echo "Installing Tekton Dashboard..."
install_tekton_dashboard

echo "Installing Tekton Triggers..."
install_tekton_triggers

echo "Tekton installation completed successfully!"
