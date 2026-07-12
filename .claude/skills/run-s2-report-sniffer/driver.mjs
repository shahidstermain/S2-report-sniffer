#!/usr/bin/env node
/**
 * S2 Report Sniffer — Playwright smoke driver
 *
 * Launches the already-running backend and takes screenshots to verify the UI.
 * Run AFTER the backend is up (see SKILL.md "Run" section).
 *
 * Usage:
 *   node .claude/skills/run-s2-report-sniffer/driver.mjs [base-url] [out-dir]
 *
 * Defaults:
 *   base-url = http://127.0.0.1:8000
 *   out-dir  = /tmp/s2rs-shots/
 */

import { chromium } from '/Users/shahidster-macmini/S2-report-sniffer/frontend/node_modules/playwright/index.mjs';
import { mkdirSync, writeFileSync } from 'fs';
import { createWriteStream } from 'fs';
import https from 'https';
import http from 'http';

const BASE = process.argv[2] || 'http://127.0.0.1:8000';
const OUT  = process.argv[3] || '/tmp/s2rs-shots';
mkdirSync(OUT, { recursive: true });

const CHROMIUM_PATH = process.env.CHROMIUM_PATH ||
  `${process.env.HOME}/Library/Caches/ms-playwright/chromium-1228/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`;

async function get(url) {
  return new Promise((resolve, reject) => {
    const client = url.startsWith('https') ? https : http;
    client.get(url, (res) => {
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(chunks).toString() }));
    }).on('error', reject);
  });
}

async function postMultipart(url, fieldName, filename, data) {
  return new Promise((resolve, reject) => {
    const boundary = '----S2RSBoundary' + Math.random().toString(36).slice(2);
    const header = `--${boundary}\r\nContent-Disposition: form-data; name="${fieldName}"; filename="${filename}"\r\nContent-Type: application/octet-stream\r\n\r\n`;
    const footer = `\r\n--${boundary}--\r\n`;
    const body = Buffer.concat([Buffer.from(header), data, Buffer.from(footer)]);

    const u = new URL(url);
    const req = http.request({
      hostname: u.hostname, port: u.port, path: u.pathname + u.search, method: 'POST',
      headers: { 'Content-Type': `multipart/form-data; boundary=${boundary}`, 'Content-Length': body.length },
    }, (res) => {
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(chunks).toString() }));
    }).on('error', reject);
    req.write(body);
    req.end();
  });
}

/** Build a minimal valid ZIP containing one file */
function minimalZip(innerFilename, innerContent) {
  const enc = new TextEncoder();
  const content = typeof innerContent === 'string' ? Buffer.from(innerContent) : innerContent;
  const nameBytes = Buffer.from(innerFilename);

  function crc32(buf) {
    const table = new Uint32Array(256);
    for (let i = 0; i < 256; i++) {
      let c = i;
      for (let k = 0; k < 8; k++) c = (c & 1) ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      table[i] = c;
    }
    let crc = 0xffffffff;
    for (const b of buf) crc = table[(crc ^ b) & 0xff] ^ (crc >>> 8);
    return (crc ^ 0xffffffff) >>> 0;
  }

  const crc = crc32(content);
  const localHeader = Buffer.alloc(30 + nameBytes.length);
  localHeader.writeUInt32LE(0x04034b50, 0);
  localHeader.writeUInt16LE(20, 4);   // version needed
  localHeader.writeUInt16LE(0, 6);    // flags
  localHeader.writeUInt16LE(0, 8);    // compression: stored
  localHeader.writeUInt16LE(0, 10);   // mod time
  localHeader.writeUInt16LE(0, 12);   // mod date
  localHeader.writeUInt32LE(crc, 14);
  localHeader.writeUInt32LE(content.length, 18);
  localHeader.writeUInt32LE(content.length, 22);
  localHeader.writeUInt16LE(nameBytes.length, 26);
  localHeader.writeUInt16LE(0, 28);
  nameBytes.copy(localHeader, 30);

  const centralDir = Buffer.alloc(46 + nameBytes.length);
  centralDir.writeUInt32LE(0x02014b50, 0);
  centralDir.writeUInt16LE(20, 4);
  centralDir.writeUInt16LE(20, 6);
  centralDir.writeUInt16LE(0, 8);
  centralDir.writeUInt16LE(0, 10);
  centralDir.writeUInt16LE(0, 12);
  centralDir.writeUInt16LE(0, 14);
  centralDir.writeUInt32LE(crc, 16);
  centralDir.writeUInt32LE(content.length, 20);
  centralDir.writeUInt32LE(content.length, 24);
  centralDir.writeUInt16LE(nameBytes.length, 28);
  centralDir.writeUInt16LE(0, 30);
  centralDir.writeUInt16LE(0, 32);
  centralDir.writeUInt16LE(0, 34);
  centralDir.writeUInt16LE(0, 36);
  centralDir.writeUInt32LE(0, 38);
  centralDir.writeUInt32LE(0, 42); // local header offset
  nameBytes.copy(centralDir, 46);

  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(0, 4);
  eocd.writeUInt16LE(0, 6);
  eocd.writeUInt16LE(1, 8);
  eocd.writeUInt16LE(1, 10);
  eocd.writeUInt32LE(centralDir.length, 12);
  eocd.writeUInt32LE(localHeader.length + content.length, 16);
  eocd.writeUInt16LE(0, 20);

  return Buffer.concat([localHeader, content, centralDir, eocd]);
}

(async () => {
  // 1. Verify health
  const health = await get(`${BASE}/api/health`);
  if (health.status !== 200) throw new Error(`Health check failed: HTTP ${health.status}`);
  console.log('✅ Health OK:', JSON.parse(health.body).status);

  // 2. Launch browser
  const browser = await chromium.launch({
    executablePath: CHROMIUM_PATH,
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();

  // 3. Screenshot report list
  await page.goto(`${BASE}/ui/`, { waitUntil: 'networkidle', timeout: 15000 });
  await page.screenshot({ path: `${OUT}/01-report-list.png` });
  console.log(`✅ Screenshot 01 → ${OUT}/01-report-list.png`);

  // 4. Upload a minimal dummy report
  const zipData = minimalZip('smoke-test/README.txt', 'S2RS smoke test fixture\n');
  const upload = await postMultipart(`${BASE}/api/reports/upload`, 'file', 'smoke-test.zip', zipData);
  if (upload.status !== 200) throw new Error(`Upload failed: HTTP ${upload.status} — ${upload.body}`);
  const { id: reportId } = JSON.parse(upload.body);
  console.log('✅ Upload accepted, report ID:', reportId);

  // 5. Poll for processing to complete
  let ready = false;
  for (let i = 0; i < 15; i++) {
    const s = await get(`${BASE}/api/reports/${reportId}/status`);
    const { status } = JSON.parse(s.body);
    if (status === 'ready' || status === 'error') { ready = true; break; }
    await new Promise(r => setTimeout(r, 500));
  }
  if (!ready) console.warn('⚠️ Report still processing after 7.5s — navigating anyway');

  // 6. Navigate to report overview
  await page.goto(`${BASE}/ui/report/${reportId}/overview`, { waitUntil: 'networkidle', timeout: 15000 });
  await page.screenshot({ path: `${OUT}/02-report-overview.png` });
  console.log(`✅ Screenshot 02 → ${OUT}/02-report-overview.png`);

  // 7. Navigate to Charts tab — tabs are client-side useState, not URL-based.
  //    Use data-testid selectors (see ReportDashboard.jsx TABS array).
  await page.locator('[data-testid="tab-charts"]').click();
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: `${OUT}/03-charts-dashboard.png` });
  console.log(`✅ Screenshot 03 → ${OUT}/03-charts-dashboard.png`);

  // 8. Check for JS errors
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  if (errors.length) console.warn('⚠️ JS errors:', errors.join('; '));
  else console.log('✅ No JS errors');

  await browser.close();
  console.log(`\nDone. Screenshots in ${OUT}/`);
})().catch(e => { console.error('FAIL:', e.message); process.exit(1); });
