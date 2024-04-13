#!/bin/bash

# Function to check if ArgoCD is installed
is_argocd_installed() {
    if kubectl get deployment argocd-server -n argocd >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# Install ArgoCD
install_argocd() {
    # Create the argocd namespace
    kubectl create namespace argocd

    # Install ArgoCD
    kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
}

# Main script
if is_argocd_installed; then
    echo "ArgoCD is already installed."
else
    echo "Installing ArgoCD..."
    install_argocd
    echo "ArgoCD installation completed successfully!"
fi