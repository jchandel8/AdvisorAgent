import { expect, test, type Page } from '@playwright/test';

// Real sign-in through Cognito's hosted page. Run by the owner after creating the demo logins:
//   E2E_AUTH=cognito E2E_ADVISOR_USERNAME=anthony.gonzalez E2E_CLIENT_USERNAME=kevin.keith \
//   docker compose --profile e2e run --rm e2e
// DEMO_PASSWORD comes from .env (never committed).
test.skip(process.env['E2E_AUTH'] !== 'cognito', 'cognito-mode suite');

async function signIn(page: Page, username: string) {
  await page.goto('/login');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.waitForURL(/amazoncognito\.com/);
  // Classic hosted UI renders the form twice (desktop and mobile); use the visible one.
  await page.locator('input[name="username"]:visible').fill(username);
  await page.locator('input[name="password"]:visible').fill(process.env['DEMO_PASSWORD'] ?? '');
  await page.locator('input[type="submit"]:visible, button[type="submit"]:visible').first().click();
  await page.waitForURL((url) => !url.hostname.includes('amazoncognito.com'));
}

test('advisor signs in with Cognito and sees their clients', async ({ page }) => {
  await signIn(page, process.env['E2E_ADVISOR_USERNAME'] ?? 'anthony.gonzalez');
  await expect(page).toHaveURL(/\/advisor\//);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('you look after');
});

test('client signs in with Cognito and sees only their portal', async ({ page }) => {
  await signIn(page, process.env['E2E_CLIENT_USERNAME'] ?? 'kevin.keith');
  await expect(page).toHaveURL(/\/client\//);
  await page.goto('/advisor/dashboard');
  await expect(page).toHaveURL(/\/client\//);
});

test('the demo picker does not exist in cognito mode', async ({ page }) => {
  await page.goto('/demo');
  await expect(page).toHaveURL(/\/login/);
  const res = await page.request.get('/api/demo/users');
  expect(res.status()).toBe(404);
});
