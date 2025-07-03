#!/bin/bash

# 🔧 Usage: ./setup_nginx_flask_proxy.sh [FLASK_PORT]
FLASK_PORT=${1:-5000}
NGINX_CONF="/etc/nginx/sites-available/flask_ssl"
NGINX_ENABLED="/etc/nginx/sites-enabled/flask_ssl"

echo "🌐 Is this deployment for a valid domain or localhost?"
read -p "Type 'localhost' for self-signed SSL, or enter your domain name (e.g., tennis-news.in): " SITE_INPUT

if [[ "$SITE_INPUT" == "localhost" ]]; then
    SITE_TYPE="localhost"
    DOMAIN="localhost"
else
    SITE_TYPE="domain"
    DOMAIN="$SITE_INPUT"
fi

. /etc/os-release
OS=$ID

if [[ "$OS" =~ (ubuntu|debian) ]]; then
    echo "📦 Installing NGINX and cert tools..."
    sudo apt update
    sudo apt install -y nginx openssl
    [[ "$SITE_TYPE" == "domain" ]] && sudo apt install -y certbot python3-certbot-nginx
else
    echo "❌ Only Ubuntu/Debian are supported."
    exit 1
fi

if [[ "$SITE_TYPE" == "localhost" ]]; then
    CERT_DIR="/etc/nginx/certs"
    KEY_FILE="$CERT_DIR/selfsigned.key"
    CRT_FILE="$CERT_DIR/selfsigned.crt"
    echo "📁 Creating cert directory: $CERT_DIR"
    sudo mkdir -p "$CERT_DIR"

    if [[ ! -f "$KEY_FILE" || ! -f "$CRT_FILE" ]]; then
        echo "🔐 Creating self-signed SSL certificate..."
        sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout "$KEY_FILE" \
            -out "$CRT_FILE" \
            -subj "/C=IN/ST=Local/L=Local/O=Dev/CN=$DOMAIN"
    else
        echo "✅ Self-signed certificate already exists."
    fi
fi

echo "📝 Writing NGINX reverse proxy config..."

sudo tee "$NGINX_CONF" > /dev/null <<EOF
server {
    listen 443 ssl;
    server_name $DOMAIN;
EOF

if [[ "$SITE_TYPE" == "localhost" ]]; then
    sudo tee -a "$NGINX_CONF" > /dev/null <<EOF
    ssl_certificate     $CRT_FILE;
    ssl_certificate_key $KEY_FILE;
EOF
else
    sudo tee -a "$NGINX_CONF" > /dev/null <<EOF
    ssl_certificate     /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
EOF
fi

sudo tee -a "$NGINX_CONF" > /dev/null <<'EOF'

    location / {
        proxy_pass http://localhost:'"$FLASK_PORT"';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /jenkins-app {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /tekton-app {
        proxy_pass http://localhost:32000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /nexus-app {
        proxy_pass http://localhost:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
EOF

echo "🔗 Enabling config..."
sudo ln -sf "$NGINX_CONF" "$NGINX_ENABLED"
sudo rm -f /etc/nginx/sites-enabled/default

echo "🔄 Testing and reloading NGINX..."
if sudo nginx -t; then
    sudo systemctl reload nginx
    sudo systemctl enable nginx
    sudo systemctl restart nginx

    if [[ "$SITE_TYPE" == "localhost" ]]; then
        echo "🛡️  Updating trusted certs..."
        sudo cp "$CRT_FILE" /usr/local/share/ca-certificates/selfsigned.crt
        sudo update-ca-certificates
        echo "✅ Visit: https://localhost"
    else
        echo "🔐 Running certbot for HTTPS..."
        sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m admin@$DOMAIN || {
            echo "⚠️  Certbot failed. Check your domain DNS and NGINX setup."
        }
        echo "✅ Visit: https://$DOMAIN"
    fi
else
    echo "❌ NGINX config test failed."
    exit 1
fi
