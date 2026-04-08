const { test, expect } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

test.beforeAll(() => {
  const fixtureDir = path.join(__dirname, 'fixtures');
  if (!fs.existsSync(fixtureDir)) fs.mkdirSync(fixtureDir, { recursive: true });
  const dummyReport = path.join(fixtureDir, 'dummy-report.zip');
  if (!fs.existsSync(dummyReport)) {
    fs.writeFileSync(dummyReport, 'PK\x05\x06' + Buffer.alloc(18).toString('binary'));
  }
});

test('should load app and show UI', async ({ page }) => {
  await page.goto('/ui/');
  await expect(page).toHaveTitle(/Report Sniffer/i);
  await expect(page.locator('text=Report Sniffer').first()).toBeVisible();
  
  // Wait for the dropzone or upload UI to appear
  await expect(page.locator('text=Click to browse')).toBeVisible({ timeout: 10000 });
});
