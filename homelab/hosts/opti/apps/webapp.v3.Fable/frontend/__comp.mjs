import { compile } from 'svelte/compiler';
import fs from 'node:fs';
const src = fs.readFileSync(process.argv[2], 'utf8');
try {
  const r = compile(src, { filename: 'x.svelte', generate: 'client', runes: true, dev: true });
  console.log('COMPILED OK. warnings:');
  for (const w of r.warnings) console.log('  -', w.code, w.message, w.start && w.start.line);
  const js = r.js.code;
  const i = js.indexOf('function matchRow');
  console.log('--- matchRow excerpt ---');
  console.log(js.slice(Math.max(0,i-100), i+700));
} catch (e) {
  console.log('COMPILE ERROR:', e.code, '|', e.message, '| line', e.start && e.start.line);
}
