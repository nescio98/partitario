#!/bin/sh
# Runs before nginx starts (/docker-entrypoint.d/ of the nginx image).
#
# nginx cannot start without a certificate, and Let's Encrypt cannot issue one
# before nginx answers the HTTP challenge. So:
#   1. install the certificate published by the certbot sidecar in /certs, or
#      a short-lived self-signed placeholder if there is none yet;
#   2. keep watching /certs in the background and reload nginx whenever the
#      certificate there changes (first issuance, then every renewal).
set -eu

# Baked into the image; only the TLS stacks (NGINX_TLS=on) need a certificate.
[ "${NGINX_TLS:-off}" = "on" ] || exit 0

SOURCE=/certs
TARGET=/etc/nginx/tls
umask 077

log() { echo "40-tls-certificates.sh: $*"; }

install_certificate() {
    cp "$SOURCE/privkey.pem" "$TARGET/privkey.pem"
    cp "$SOURCE/fullchain.pem" "$TARGET/fullchain.pem"
}

has_certificate() { [ -s "$SOURCE/fullchain.pem" ] && [ -s "$SOURCE/privkey.pem" ]; }

if has_certificate; then
    install_certificate
    log "using the certificate from $SOURCE"
else
    openssl req -x509 -nodes -newkey rsa:2048 -days 30 -subj "/CN=localhost" \
        -keyout "$TARGET/privkey.pem" -out "$TARGET/fullchain.pem" 2>/dev/null
    log "no certificate in $SOURCE yet: serving a self-signed placeholder"
fi

(
    while sleep 30; do
        if has_certificate && ! cmp -s "$SOURCE/fullchain.pem" "$TARGET/fullchain.pem"; then
            install_certificate
            log "certificate changed, reloading nginx"
            nginx -s reload || true
        fi
    done
) &
