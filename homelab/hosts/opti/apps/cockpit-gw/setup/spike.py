import base64, json, os, socket, struct, sys, urllib.request

host = sys.argv[1]
root = '/cp-' + host
port = 19090
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None
opener = urllib.request.build_opener(NoRedirect)
for path in ('/', '/system', '/cockpit/@localhost/manifests.json'):
    with opener.open(f'http://127.0.0.1:{port}{root}{path}', timeout=8) as response:
        body = response.read()
        assert response.status == 200
        if path.endswith('.json'):
            manifests = json.loads(body)
            assert 'shell' in manifests and ('system' in manifests or 'systemd' in manifests)
            print('packages:', ', '.join(manifests))
        else:
            assert b'<html' in body.lower() or b'<!doctype html' in body.lower()
        print(path, 'HTTP 200')

connection = socket.create_connection(('127.0.0.1', port), timeout=8)
connection.settimeout(8)
key = base64.b64encode(os.urandom(16)).decode()
connection.sendall((f'GET {root}/cockpit/socket HTTP/1.1\r\nHost: webapp.lan:8444\r\n'
    'Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\n'
    f'Sec-WebSocket-Key: {key}\r\nOrigin: https://webapp.lan:8444\r\nX-Forwarded-Proto: https\r\n\r\n').encode())
buffer = bytearray()
while b'\r\n\r\n' not in buffer:
    buffer.extend(connection.recv(4096))
headers, remaining = bytes(buffer).split(b'\r\n\r\n',1)
assert b'101 Switching Protocols' in headers, headers
buffer = bytearray(remaining)
def read_exact(count):
    while len(buffer) < count:
        data = connection.recv(65536)
        if not data: raise RuntimeError('websocket closed')
        buffer.extend(data)
    data = bytes(buffer[:count]); del buffer[:count]
    return data
def receive():
    first, size = read_exact(2)
    if size == 126: size = struct.unpack('!H', read_exact(2))[0]
    elif size == 127: size = struct.unpack('!Q', read_exact(8))[0]
    data = read_exact(size)
    if first & 15 == 8: raise RuntimeError('websocket close frame')
    return data.decode()
def send(data):
    data = data.encode(); mask = os.urandom(4)
    length = len(data)
    header = bytes([0x81, 0x80 | length]) if length < 126 else bytes([0x81, 0xfe]) + struct.pack('!H', length)
    connection.sendall(header + mask + bytes(c ^ mask[i % 4] for i,c in enumerate(data)))
def control(message):
    send('\n' + json.dumps(message))
init = json.loads(receive().split('\n', 1)[1])
assert init['command'] == 'init', init
print('session init:', json.dumps(init.get('user')))
control({'command': 'init', 'version': 1})
control({'command': 'open', 'channel': 'root-proof', 'payload': 'stream', 'spawn': ['/usr/bin/id', '-u']})
control({'command': 'done', 'channel': 'root-proof'})
output = ''
for _ in range(30):
    message = receive()
    channel, data = message.split('\n', 1)
    if channel == 'root-proof': output += data
    elif not channel:
        event = json.loads(data)
        if event.get('command') == 'close' and event.get('channel') == 'root-proof':
            assert event.get('exit-status') == 0, event
            break
assert output.strip() == '0', output
print('root identity verified: id -u = 0')
if len(sys.argv) > 2 and sys.argv[2] == 'logout':
    control({'command': 'logout', 'disconnect': True})
    print('logout sent')
connection.close()
