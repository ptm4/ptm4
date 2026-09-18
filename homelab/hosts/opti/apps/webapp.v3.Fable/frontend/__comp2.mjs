import { compile } from 'svelte/compiler';
import fs from 'node:fs';
const src = fs.readFileSync(process.argv[2], 'utf8');
const r = compile(src, { filename: 'x.svelte', generate: 'client', runes: true, dev: false });
const js = r.js.code;
const lines = js.split('\n');
lines.forEach((l, n) => { if (/showEvent|matchRow|eventGroup/.test(l)) console.log(n+1, l.trim().slice(0,200)); });
