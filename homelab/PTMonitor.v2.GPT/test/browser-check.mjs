// Optional visual/layout integration check. Usage: node test/browser-check.mjs <playwright module path>
// Screenshots are build artifacts under test/artifacts; no browser dependency ships with PTMonitor.
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { startPreview } from './preview-server.mjs';
const { chromium } = process.argv[2] ? await import(pathToFileURL(process.argv[2]).href) : await import('playwright');
const { server, url } = await startPreview();
const artifacts = fileURLToPath(new URL('./artifacts/', import.meta.url)); await mkdir(artifacts, { recursive: true });
const browser = await chromium.launch({ channel: process.env.PTMONITOR_BROWSER || 'msedge', headless: true });
try {
  for (const scale of [1, 1.25, 1.5]) {
    const page = await browser.newPage({ viewport: { width: 760, height: 840 }, deviceScaleFactor: scale });
    const errors = []; page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(`${url}/?demo&scenario=long`); await page.waitForFunction(() => document.querySelector('#core-metrics strong')?.textContent !== '—');
    assert.equal(await page.locator('#widget').evaluate((node) => node.getBoundingClientRect().width), 312);
    assert.equal(await page.locator('#widget').evaluate((node) => node.getBoundingClientRect().height), 452);
    assert.equal(await page.locator('#disk-list .disk-row').count(), 3);
    assert.deepEqual(await page.locator('#disk-list .disk-row > strong').allTextContents(),['C:','V:','E:']);
    assert.match(await page.locator('#disk-list .disk-subline').first().textContent(),/free/);
    assert.equal(await page.locator('#preview-label').isVisible(), true);
    assert.equal(await page.locator('#compact').evaluate((node) => node.scrollHeight > node.clientHeight + 1), false, 'compact layout must fit');
    assert.equal(await page.locator('#widget').evaluate((node) => node.scrollWidth > node.clientWidth + 1), false, 'no horizontal crop');
    await page.locator('#core-metrics').click(); assert.equal(await page.locator('html').getAttribute('data-expanded'), 'false', 'clicks on readings must not change layout');
    const metricHandle = await page.locator('.metric-row.cpu').elementHandle();
    await page.waitForTimeout(1200); assert.equal(await metricHandle.evaluate((node) => node.isConnected), true, 'metric DOM must survive live update');
    await page.screenshot({ path: `${artifacts}/compact-${scale}.png` });
    await page.locator('#btn-expand').click(); await page.waitForFunction(() => document.documentElement.dataset.expanded === 'true');
    assert.equal(await page.locator('#widget').evaluate((node) => node.getBoundingClientRect().width), 580);
    assert.equal(await page.locator('#chart-grid canvas').count(), 4);
    assert.equal(await page.locator('#all-disks .volume').count(), 4);
    await page.screenshot({ path: `${artifacts}/overview-${scale}.png` });
    await page.locator('[data-tab=sensors]').click(); await page.locator('#sensor-search').fill('<script>');
    assert.equal(await page.locator('#sensor-list .sensor').count(), 1); assert.equal(await page.locator('#sensor-list script').count(), 0, 'sensor strings are never HTML');
    await page.locator('#sensor-search').fill(''); await page.screenshot({ path: `${artifacts}/sensors-${scale}.png` });
    await page.locator('[data-tab=activity]').click(); assert.equal(await page.locator('#alert-list .alert-row').count(), 2); await page.screenshot({ path: `${artifacts}/activity-${scale}.png` });
    await page.locator('#btn-settings').click(); await page.locator('#set-adapter').selectOption('Wi-Fi'); await page.locator('#set-adapter').selectOption(''); assert.equal(await page.locator('#set-adapter').inputValue(), '', 'Auto resets selected adapter');
    assert.equal(await page.locator('#threshold-controls input').count(), 14); await page.screenshot({ path: `${artifacts}/settings-${scale}.png` });
    assert.deepEqual(errors, []); await page.close();
  }
  const page = await browser.newPage({ viewport: { width: 760, height: 840 } });
  await page.goto(`${url}/?demo&scenario=unavailable&paused`); await page.waitForFunction(() => document.querySelector('.metric-row.gpu strong')?.textContent === '—');
  assert.equal(await page.locator('#net-down').textContent(), '—');
  await page.screenshot({ path: `${artifacts}/unavailable.png` });
  await page.waitForFunction(() => document.querySelector('#widget').dataset.stale === 'true', { timeout: 6000 });
  assert.match(await page.locator('#health-copy').textContent(), /Updates paused/);
  await page.screenshot({ path: `${artifacts}/stale.png` });
  console.log('Browser QA passed: compact/expanded layout at 100/125/150%, stable live DOM, safe sensor text, adapter reset, thresholds, missing sensors and stale updates.');
} finally { await browser.close(); server.close(); }
