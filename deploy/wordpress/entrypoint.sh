#!/usr/bin/env bash
# Boot sequence for the hosted demo store:
#   1. let the official image lay down WordPress + wp-config.php (its entrypoint does this when apache starts)
#   2. seed in the background once the DB answers (same script the compose stack uses, idempotent)
#   3. keep apache in the foreground
set -euo pipefail

: "${SITE_URL:?SITE_URL must be the public https URL of this service, e.g. https://store.up.railway.app}"
: "${PORT:=80}"

# Apache listens on $PORT (Railway assigns one); the official image hard-codes 80.
sed -ri "s/^Listen 80$/Listen ${PORT}/" /etc/apache2/ports.conf
sed -ri "s/<VirtualHost \*:80>/<VirtualHost *:${PORT}>/" /etc/apache2/sites-available/000-default.conf

# Railway's runtime can leave both mpm_prefork and mpm_event enabled, and apache refuses to start with
# "AH00534: More than one MPM loaded" (station.railway.com/questions/more-than-one-mpm-loaded-error-on-php-8-9c836859).
# The image is innocent (locally only prefork is enabled); force exactly one MPM before starting.
rm -f /etc/apache2/mods-enabled/mpm_event.* /etc/apache2/mods-enabled/mpm_worker.*
a2enmod -q mpm_prefork >/dev/null 2>&1 || true
echo "ServerName ${SITE_URL#*://}" > /etc/apache2/conf-enabled/servername.conf

# Pin home/site URL and tell WordPress it is behind an https proxy, otherwise it redirects to http://.
export WORDPRESS_CONFIG_EXTRA="
define('WP_HOME', '${SITE_URL}');
define('WP_SITEURL', '${SITE_URL}');
if (isset(\$_SERVER['HTTP_X_FORWARDED_PROTO']) && \$_SERVER['HTTP_X_FORWARDED_PROTO'] === 'https') { \$_SERVER['HTTPS'] = 'on'; }
${WORDPRESS_CONFIG_EXTRA:-}
"

(
  cd /var/www/html
  echo "[seed-and-serve] waiting for wp-config.php and the database..."
  until [ -f wp-config.php ] && wp db check --allow-root >/dev/null 2>&1; do sleep 3; done
  # The compose seed runs as www-data; here apache's entrypoint created the files as www-data too.
  export SITE_URL WP_CLI_CACHE_DIR=/tmp/wp-cli-cache
  sed -i "s#^SITE_URL=.*#SITE_URL=\"${SITE_URL}\"#" /seed/entrypoint.sh
  su -s /bin/bash www-data -c "bash /seed/entrypoint.sh" || echo "[seed-and-serve] seed failed (see above); store is up but unseeded"
  # The seed's admin/admin is for laptops. On a public URL, take the password from the environment.
  if [ -n "${WP_ADMIN_PASSWORD:-}" ]; then
    su -s /bin/bash www-data -c "wp user update admin --user_pass='${WP_ADMIN_PASSWORD}' --skip-email" >/dev/null \
      && echo "[seed-and-serve] admin password set from WP_ADMIN_PASSWORD"
  else
    echo "[seed-and-serve] WARNING: WP_ADMIN_PASSWORD not set - wp-admin is admin/admin on a public host"
  fi
) &

exec docker-entrypoint.sh apache2-foreground
