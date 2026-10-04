"""A live bridge must return manifests, never a login document or redirect."""
import json
import os
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def healthy(root=None):
    root = root or os.environ['URL_ROOT']
    url = f'http://127.0.0.1:9090{root}/cockpit/@localhost/manifests.json'
    try:
        with urllib.request.build_opener(NoRedirect).open(url, timeout=5) as response:
            if response.status != 200:
                return False
            body = response.read(1024 * 1024 + 1)
            if len(body) > 1024 * 1024:
                return False
            manifests = json.loads(body)
            return isinstance(manifests, dict) and isinstance(manifests.get('shell'), dict) and any(
                isinstance(manifests.get(key), dict) for key in ('system', 'systemd'))
    except (OSError, ValueError):
        return False

if __name__ == '__main__':
    raise SystemExit(0 if healthy() else 1)
