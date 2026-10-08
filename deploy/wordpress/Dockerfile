# Demo WooCommerce store that seeds itself on first boot - for hosts (Railway, Fly, Render) where the
# compose stack's shared volume + one-shot seed container are not available.
#
# Build context is the repo root:  docker build -f deploy/wordpress/Dockerfile .
# Required env: WORDPRESS_DB_HOST, WORDPRESS_DB_USER, WORDPRESS_DB_PASSWORD, WORDPRESS_DB_NAME, SITE_URL (public https URL)

FROM wordpress:php8.3-apache

# wp-cli (the official cli image ships it as a phar; same approach here)
RUN curl -fsSL -o /usr/local/bin/wp https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar \
    && chmod +x /usr/local/bin/wp

COPY docker/seed/ /seed/
COPY deploy/wordpress/entrypoint.sh /usr/local/bin/seed-and-serve
RUN chmod +x /usr/local/bin/seed-and-serve /seed/entrypoint.sh

# Railway and friends inject PORT; Apache must listen on it.
ENV PORT=80
ENTRYPOINT ["seed-and-serve"]
