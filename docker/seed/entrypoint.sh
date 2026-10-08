#!/usr/bin/env bash
# Runs once inside the wordpress:cli container: install WordPress + WooCommerce, then seed demo data.
# Idempotent - safe to `docker compose up` repeatedly.
set -euo pipefail
cd /var/www/html

SITE_URL="http://localhost:8080"

echo "[seed] waiting for wp-config.php and the database..."
until [ -f wp-config.php ] && wp db check >/dev/null 2>&1; do sleep 2; done

if ! wp core is-installed >/dev/null 2>&1; then
  echo "[seed] installing WordPress"
  wp core install \
    --url="$SITE_URL" \
    --title="Chai & Co. (demo store)" \
    --admin_user=admin --admin_password=admin --admin_email=admin@example.com \
    --skip-email
fi

if ! wp plugin is-installed woocommerce >/dev/null 2>&1; then
  echo "[seed] installing WooCommerce (downloads from wordpress.org)"
  wp plugin install woocommerce --activate
fi
wp plugin is-active woocommerce >/dev/null 2>&1 || wp plugin activate woocommerce

echo "[seed] configuring store"
wp rewrite structure '/%postname%/'   # pretty permalinks => /wp-json/ routes (image ships .htaccess)
wp option update timezone_string 'Asia/Kolkata' >/dev/null || true
wp option update woocommerce_currency INR >/dev/null || true
wp option update woocommerce_default_country 'IN:KA' >/dev/null || true
wp option update woocommerce_store_city 'Bengaluru' >/dev/null || true
wp option update woocommerce_store_postcode '560001' >/dev/null || true
wp option update woocommerce_coming_soon no >/dev/null          # WC 9.1+ "coming soon" mode
wp option update woocommerce_manage_stock yes >/dev/null || true
wp option update woocommerce_notify_low_stock_amount 5 >/dev/null || true

echo "[seed] installing dev-only helpers for the wc-auth consent flow (see docker/seed/mu-plugins)"
mkdir -p wp-content/mu-plugins && cp /seed/mu-plugins/*.php wp-content/mu-plugins/

echo "[seed] seeding products, orders and the demo API key"
wp eval-file /seed/seed.php

echo "[seed] done. Store: $SITE_URL  REST: $SITE_URL/wp-json/wc/v3/"
