#!/bin/bash
# sudo iptables -t nat -A PREROUTING -p tcp --dport 443 -j REDIRECT --to-port 8443
# 🔐 Directory where certs will be stored (current dir by default)
CERT_DIR=${1:-.}
CERT_FILE="$CERT_DIR/cert.pem"
KEY_FILE="$CERT_DIR/key.pem"

echo "📁 Creating certificate directory: $CERT_DIR"
mkdir -p "$CERT_DIR"

# Check if certs already exist
if [[ -f "$CERT_FILE" && -f "$KEY_FILE" ]]; then
    echo "✅ Certificate and key already exist at $CERT_DIR. Skipping creation."
    exit 0
fi

echo "🔐 Generating self-signed certificate..."
openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$KEY_FILE" \
    -out "$CERT_FILE" \
    -days 365 \
    -subj "/C=IN/ST=Local/L=Local/O=Dev/CN=localhost"

echo "✅ Certificate and key created:"
echo "   - Cert: $CERT_FILE"
echo "   - Key : $KEY_FILE"