"""Verify the shipped JS, not just the installed package version."""
import gzip
from pathlib import Path

OLD = 'a=a.map(l=>l.replaceAll(" ","\\\\ ")).join(" ")'
FIXED = 'a=a.map(l=>"\'"+l.replaceAll("\'","\'\\"\'\\"\'")+"\'").join(" ")'

def verify(body):
    if OLD in body or FIXED not in body:
        raise ValueError('Debian CVE-2026-4802 shipped-JavaScript patch missing')

if __name__ == '__main__':
    files = list(Path('/usr/share/cockpit/systemd').glob('logs*.js.gz'))
    if not files:
        raise SystemExit('missing Cockpit systemd logs bundle')
    for file in files:
        verify(gzip.open(file, 'rt').read())
        print('Installed security-fixed bundle verified:', file)
