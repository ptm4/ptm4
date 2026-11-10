#!/bin/bash
# apply-zfs-properties.sh — make ZFS dataset properties match a declarative list.
#
# Usage: sudo bash apply-zfs-properties.sh red-properties.tsv [--dry-run]
#
# Idempotent: compares each listed property with the live value and runs `zfs set`
# (or `zfs inherit` for the value `inherit`) only where they differ, logging every
# change. Never creates, destroys or renames anything. Exits 1 if a listed dataset is
# missing, a set fails, or a quota would land below what the dataset already uses
# (ZFS allows that, but every write into the dataset would then fail).
set -uo pipefail

list=${1:?usage: apply-zfs-properties.sh <properties.tsv> [--dry-run]}
dry=${2:-}
ZFS=${ZFS:-zfs}
rc=0; changed=0

# Sizes compare as bytes: `zfs get -p` prints bytes, the list uses 1.5T / 20G / none.
to_bytes() {
    case "$1" in
        none) echo 0 ;;
        *) numfmt --from=iec "${1%B}" 2>/dev/null ;;
    esac
}
is_size_prop() {
    case "$1" in quota|refquota|reservation|refreservation) return 0 ;; esac
    return 1
}

while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}
    line=${line%%#*}
    read -r ds prop want _ <<<"$line"
    [ -z "${ds:-}" ] && continue
    if [ -z "${prop:-}" ] || [ -z "${want:-}" ]; then
        echo "::error::malformed line in $list: '$line'"; rc=1; continue
    fi
    if ! $ZFS list -H -o name "$ds" >/dev/null 2>&1; then
        echo "::error::dataset $ds not found (listed in $list)"; rc=1; continue
    fi

    if [ "$want" = "inherit" ]; then
        src=$($ZFS get -H -o source "$prop" "$ds")
        [ "$src" != "local" ] && continue
        echo "zfs inherit $prop $ds   (was local: $($ZFS get -H -o value "$prop" "$ds"))"
        [ "$dry" = "--dry-run" ] || $ZFS inherit "$prop" "$ds" || { echo "::error::zfs inherit $prop $ds failed"; rc=1; }
        changed=$((changed + 1)); continue
    fi

    if is_size_prop "$prop"; then
        want_b=$(to_bytes "$want")
        if [ -z "$want_b" ]; then echo "::error::$ds $prop: '$want' is not a size"; rc=1; continue; fi
        have_b=$($ZFS get -Hp -o value "$prop" "$ds")
        [ "$have_b" = "-" ] && have_b=0
        [ "$have_b" = "$want_b" ] && continue
        if [ "$want_b" -gt 0 ] && { [ "$prop" = quota ] || [ "$prop" = refquota ]; }; then
            if [ "$prop" = quota ]; then usedprop=used; else usedprop=referenced; fi
            used_b=$($ZFS get -Hp -o value "$usedprop" "$ds")
            if [ "$used_b" -ge "$want_b" ]; then
                echo "::error::$ds $prop=$want is below its current $usedprop ($($ZFS get -H -o value "$usedprop" "$ds")) - not set"
                rc=1; continue
            fi
        fi
        have=$($ZFS get -H -o value "$prop" "$ds")
    else
        have=$($ZFS get -H -o value "$prop" "$ds")
        [ "$have" = "$want" ] && continue
    fi

    echo "zfs set $prop=$want $ds   (was: $have)"
    [ "$dry" = "--dry-run" ] || $ZFS set "$prop=$want" "$ds" || { echo "::error::zfs set $prop=$want $ds failed"; rc=1; }
    changed=$((changed + 1))
done < "$list"

echo "$changed property change(s)${dry:+ (dry run, nothing applied)}"
exit $rc
