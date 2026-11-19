#!/bin/sh
# Let's Encrypt sidecar of staging and production.
#
# Obtains one certificate for every name in DOMAINS through the HTTP challenge
# (nginx serves /var/www/certbot), renews it when due, and publishes a copy in
# /certs readable by the unprivileged nginx (uid 101), which reloads itself.
#
# Without LETSENCRYPT_EMAIL nothing is requested: nginx keeps its self-signed
# placeholder. That is the mode for a stack running on a private machine.
set -eu

CERT_NAME=partitario
LIVE=/etc/letsencrypt/live/$CERT_NAME
NGINX_UID=101

trap 'exit 0' TERM INT

publish() {
    [ -s "$LIVE/fullchain.pem" ] || return 0
    cmp -s "$LIVE/fullchain.pem" /certs/fullchain.pem && return 0
    # Key first, certificate last: nginx reloads when the certificate changes.
    for file in privkey.pem fullchain.pem; do
        cp -L "$LIVE/$file" "/certs/$file.tmp"
        chown "$NGINX_UID:$NGINX_UID" "/certs/$file.tmp"
        chmod 600 "/certs/$file.tmp"
        mv "/certs/$file.tmp" "/certs/$file"
    done
    echo "certbot: published the certificate to /certs"
}

if [ -z "${LETSENCRYPT_EMAIL:-}" ]; then
    echo "certbot: LETSENCRYPT_EMAIL is not set - no certificate will be requested."
    while :; do sleep 86400 & wait $!; done
fi

domain_args=""
for domain in $DOMAINS; do
    domain_args="$domain_args -d $domain"
done

staging_arg=""
if [ "${LETSENCRYPT_STAGING:-false}" = "true" ]; then
    staging_arg="--test-cert"
fi

while :; do
    if [ -d "$LIVE" ]; then
        certbot renew --non-interactive || echo "certbot: renewal failed, retrying in 12h"
    else
        # shellcheck disable=SC2086
        certbot certonly --non-interactive --agree-tos --no-eff-email \
            --email "$LETSENCRYPT_EMAIL" --cert-name "$CERT_NAME" \
            --webroot --webroot-path /var/www/certbot \
            $staging_arg $domain_args \
            || echo "certbot: issuance failed (DNS not pointing here yet?), retrying in 12h"
    fi
    publish
    sleep 43200 & wait $!
done
