#!/bin/bash
exec > /var/log/ip-cutover.log 2>&1
echo "=== ip-cutover starting $(date -Is) ==="
set -x
sed -i 's/address 192.168.1.251/address 192.168.1.11/' /etc/network/interfaces
nmcli con mod 'ethernet-eno1' ipv4.addresses '192.168.1.11/24'
nmcli con mod 'ethernet-eno1' ipv4.gateway '192.168.1.1'
nmcli con mod 'ethernet-eno1' ipv4.dns '192.168.1.10,1.1.1.1'
nmcli con mod 'ethernet-eno1' ipv4.dns-search 'lan'
nmcli con mod 'ethernet-eno1' ipv4.ignore-auto-dns yes
nmcli device reapply eno1
logger -t ip-cutover "Applied 192.168.1.11"
echo "=== ip-cutover done $(date -Is) ==="
