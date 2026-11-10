#!/bin/bash
exec > /var/log/ip-rollback.log 2>&1
echo "=== ip-rollback starting $(date -Is) ==="
set -x
cp /etc/network/interfaces.pre-cutover.bak /etc/network/interfaces
nmcli con mod 'ethernet-eno1' ipv4.addresses '192.168.1.251/24'
nmcli con mod 'ethernet-eno1' ipv4.gateway '192.168.1.1'
nmcli con mod 'ethernet-eno1' ipv4.dns '192.168.1.10,1.1.1.1'
nmcli device reapply eno1
logger -t ip-rollback "ROLLED BACK to 192.168.1.251"
echo "=== ip-rollback done $(date -Is) ==="
