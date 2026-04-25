FROM wordpress:php8.2-apache

COPY docker/opcache.ini /usr/local/etc/php/conf.d/opcache.ini

COPY wp-content/plugins/ /var/www/html/wp-content/plugins/
COPY wp-content/themes/  /var/www/html/wp-content/themes/

COPY docker/entrypoint.sh /usr/local/bin/shc-entrypoint.sh
RUN chmod +x /usr/local/bin/shc-entrypoint.sh \
 && chown -R www-data:www-data /var/www/html/wp-content

ENTRYPOINT ["/usr/local/bin/shc-entrypoint.sh"]
