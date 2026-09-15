import { expect, test } from '@playwright/test';

test('application shell loads and can consume the backend contract', async ({ page }) => {
  await page.route('http://127.0.0.1:8000/api/v1/health', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"ok"}' });
  });

  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Application foundation' })).toBeVisible();
  await expect(page.getByText('Ready')).toBeVisible();
  await expect(page.getByText('Healthy')).toBeVisible();
});
