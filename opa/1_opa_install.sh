#!/bin/bash

# Adding the Gatekeeper Helm repository
echo "Adding the Gatekeeper Helm repository..."
helm repo add gatekeeper https://open-policy-agent.github.io/gatekeeper/charts

# Update the Helm repository to ensure we have the latest charts
echo "Updating the Helm repository..."
helm repo update

# Install Gatekeeper with specified name and namespace
echo "Installing Gatekeeper..."
helm install gatekeeper/gatekeeper \
  --name-template=gatekeeper \
  --namespace gatekeeper-system \
  --create-namespace

# Confirm installation
echo "Installation completed. Verifying the deployment..."
kubectl get pods -n gatekeeper-system
