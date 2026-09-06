import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';

const root = new URL('../', import.meta.url);

test('v2 renderer listens for native snapshots instead of polling', async () => {
  const source = await readFile(new URL('src/app.js', root), 'utf8');
  assert.match(source, /listen\('ptmonitor:\/\/snapshot'/);
  assert.doesNotMatch(source, /setInterval\(.*get_snapshot/s);
});

test('v2 surface retains a safe tray recovery path for click-through mode', async () => {
  const source = await readFile(new URL('src/index.html', root), 'utf8');
  assert.match(source, /Click-through can always be disabled from the PTMonitor v2 tray menu/);
});
