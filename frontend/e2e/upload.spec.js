import { test, expect } from "@playwright/test";

test("should load app and show UI", async ({ page }) => {
  await page.goto("/ui/");
  await expect(page).toHaveTitle(/Report Sniffer/i);
  await expect(page.getByText(/Report Sniffer/i).first()).toBeVisible();

  // Wait for the dropzone or upload UI to appear
  await expect(page.getByText(/Click to browse/i)).toBeVisible({ timeout: 10000 });
});
