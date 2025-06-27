#!/bin/bash


# Usage: ./setup_nginx_flask_proxy.sh [port]
FLASK_PORT=${1:-5000}
DOMAIN="localhost"
CERT_DIR="/etc/nginx/certs"
KEY_FILE="$CERT_DIR/selfsigned.key"
CRT_FILE="$CERT_DIR/selfsigned.crt"
NGINX_CONF="/etc/nginx/sites-available/flask_ssl"

echo "🔍 Checking OS..."
. /etc/os-release
OS=$ID

if [[ "$OS" =~ (ubuntu|debian) ]]; then
    echo "📦 Installing NGINX and OpenSSL if not already installed..."
    sudo apt update
    sudo apt install -y nginx openssl
else
    echo "❌ Only Ubuntu/Debian are supported right now."
    exit 1
fi

echo "📁 Creating cert directory: $CERT_DIR"
sudo mkdir -p "$CERT_DIR"

# 🔐 Check if certs exist
if [[ -f "$KEY_FILE" && -f "$CRT_FILE" ]]; then
    echo "✅ Certificate and key already exist. Skipping creation."
else
    echo "🔐 Creating self-signed SSL certificate..."
    sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "$KEY_FILE" \
        -out "$CRT_FILE" \
        -subj "/C=IN/ST=Local/L=Local/O=Dev/CN=$DOMAIN"
fi

# 📝 Write NGINX config only if not already created
if [[ -f "$NGINX_CONF" ]]; then
    echo "⚠️  NGINX config already exists at $NGINX_CONF. Skipping overwrite."
else
    echo "📝 Writing NGINX reverse proxy config..."
    cat <<EOF | sudo tee "$NGINX_CONF" > /dev/null
server {
    listen 443 ssl;
    server_name $DOMAIN;

    ssl_certificate     $CRT_FILE;
    ssl_certificate_key $KEY_FILE;

    location / {
        proxy_pass http://localhost:$FLASK_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}

EOF
fi

echo "🔗 Enabling site config and disabling default..."
sudo ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/flask_ssl
sudo rm -f /etc/nginx/sites-enabled/default

echo "🔄 Testing and reloading NGINX..."
if sudo nginx -t; then
    sudo systemctl reload nginx
    sudo systemctl enable nginx
    sudo  systemctl restart nginx
    sudo cp /etc/nginx/certs/selfsigned.crt /usr/local/share/ca-certificates/selfsigned.crt 
    sudo update-ca-certificates

    echo "✅ All good! Visit: https://localhost"
else
    echo "❌ NGINX config test failed. Fix the errors and try again."
    exit 1
fi
