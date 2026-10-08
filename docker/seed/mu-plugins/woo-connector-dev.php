<?php
/**
 * Plugin Name: woo-connector dev helpers (demo store only)
 * Description: Lets WooCommerce's wc-auth consent flow deliver API keys to the developer's laptop. WooCommerce
 *              requires an HTTPS callback and WordPress refuses "safe" requests to local hosts and unusual ports,
 *              so this relaxes exactly those three checks for host.docker.internal. NEVER install on a real store:
 *              a production connector exposes a public HTTPS callback and needs none of this.
 */

const WOO_CONNECTOR_DEV_HOST = 'host.docker.internal';

// wp_safe_remote_post() rejects hosts that are not "external"; the laptop is reached via Docker's gateway alias.
add_filter(
	'http_request_host_is_external',
	function ( $external, $host ) {
		return WOO_CONNECTOR_DEV_HOST === $host ? true : $external;
	},
	10,
	2
);

// Safe requests only allow ports 80/443/8080; the connector's callback listener uses 8788.
add_filter(
	'http_allowed_safe_ports',
	function ( $ports ) {
		return array_merge( $ports, array( 8787, 8788 ) );
	}
);

// The listener uses a self-signed certificate (callback_url must be https://).
add_filter(
	'http_request_args',
	function ( $args, $url ) {
		if ( false !== strpos( $url, WOO_CONNECTOR_DEV_HOST ) ) {
			$args['sslverify'] = false;
		}
		return $args;
	},
	10,
	2
);
