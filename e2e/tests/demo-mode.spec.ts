import { expect, test, type Page } from '@playwright/test';

// What each person can see, checked in a real browser with the local demo sign-in.
// Advisor: Anthony Gonzalez (advisor 2). Client: Kevin Keith (client 10) has 3 accounts, 2 shared with Anthony.
test.skip(process.env['E2E_AUTH'] === 'cognito', 'demo-mode suite');

async function pick(page: Page, name: string) {
  await page.goto('/demo');
  await page.getByRole('button', { name: new RegExp(`^${name}`) }).click(); // name first, not inside a note
}

test('advisor sees their book and only the accounts they share with a client', async ({ page }) => {
  await pick(page, 'Anthony Gonzalez');
  await expect(page).toHaveURL(/\/advisor\/dashboard/);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('you look after 38 clients');
  await expect(page.getByRole('row', { name: /Kevin Keith/ })).toBeVisible();

  await page.goto('/advisor/accounts?client=10');
  await expect(page.getByText('You manage 2 accounts for Kevin Keith')).toBeVisible();
  await expect(page.getByRole('row', { name: /Kevin Keith Individual 2/ })).toHaveCount(0);
});

test('advisor cannot open a client they share no account with', async ({ page }) => {
  await pick(page, 'Anthony Gonzalez');
  await page.goto('/advisor/accounts?client=1');
  await expect(page.getByText("That client isn't one of yours")).toBeVisible();
});

test('client sees all of their own accounts', async ({ page }) => {
  await pick(page, 'Kevin Keith');
  await expect(page).toHaveURL(/\/client\/dashboard/);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('your 3 accounts are worth');
  await expect(page.getByRole('row', { name: /Kevin Keith Individual 2/ })).toBeVisible();
});

test("client cannot open the advisor portal or someone else's account", async ({ page }) => {
  await pick(page, 'Kevin Keith');
  await page.goto('/advisor/dashboard');
  await expect(page).toHaveURL(/\/client\//); // sent back to their own portal

  await page.goto('/client/holdings?account=118'); // Shelby Moody's IRA
  await expect(page.getByText("That account isn't one of yours")).toBeVisible();

  // The API refuses too: the frontend hiding a screen is not the security.
  const res = await page.request.get('/api/advisor/clients', { headers: { 'X-Demo-User': 'client:10' } });
  expect(res.status()).toBe(403);
});

test('advisor and client see the same shared account with the same value', async ({ browser }) => {
  const advisor = await (await browser.newContext()).newPage();
  const client = await (await browser.newContext()).newPage(); // separate storage, like a private window
  await pick(advisor, 'Anthony Gonzalez');
  await pick(client, 'Kevin Keith');

  await advisor.goto('/advisor/accounts?client=10');
  await client.goto('/client/dashboard');
  const row = (p: Page) => p.getByRole('row', { name: /Kevin Keith Roth IRA/ });
  const value = async (p: Page) => (await row(p).textContent())?.match(/\$[\d,]+\.\d\d/)?.[0];
  await expect(row(advisor)).toBeVisible();
  await expect(row(client)).toBeVisible();
  expect(await value(advisor)).toBe(await value(client));
});

test('admin grants an account, the advisor sees it, then the admin revokes it (demo script)', async ({ browser }) => {
  // Account 19 is Kevin Keith's "Individual 2", handled by a different advisor than Anthony.
  const admin = await (await browser.newContext()).newPage();
  const advisor = await (await browser.newContext()).newPage();
  await pick(admin, 'Morgan Lee');
  await expect(admin).toHaveURL(/\/admin\/users/);
  await pick(advisor, 'Anthony Gonzalez');

  await advisor.goto('/advisor/accounts?client=10');
  await expect(advisor.getByText('You manage 2 accounts for Kevin Keith')).toBeVisible();

  // Grant
  await admin.goto('/admin/permissions?account=19');
  await admin.getByLabel('Grant access to').fill('anthony');
  await admin.getByRole('button', { name: /Anthony Gonzalez/ }).click();
  await admin.getByRole('button', { name: 'Grant access' }).click();
  await expect(admin.getByRole('status')).toContainText('Granted Anthony Gonzalez');

  await advisor.reload();
  await expect(advisor.getByText('You manage 3 accounts for Kevin Keith')).toBeVisible();

  // Revoke (restores the starting state)
  const row = admin.getByRole('row', { name: /Anthony Gonzalez/ });
  await row.getByRole('button', { name: 'Revoke' }).click();
  await row.getByRole('button', { name: 'Confirm revoke' }).click();
  await expect(admin.getByRole('status')).toContainText("Revoked Anthony Gonzalez's access");

  await advisor.reload();
  await expect(advisor.getByText('You manage 2 accounts for Kevin Keith')).toBeVisible();

  // Both changes are the newest two audit entries (earlier runs may have left older ones).
  await admin.goto('/admin/audit');
  const rows = admin.getByRole('table').getByRole('row');
  await expect(rows.nth(1)).toContainText('Revoked Anthony Gonzalez');
  await expect(rows.nth(2)).toContainText('Granted Anthony Gonzalez');
});

test('admin drills down from a client to an account to a document and downloads it', async ({ page }) => {
  await pick(page, 'Morgan Lee');
  await page.goto('/admin/users');
  await page.getByRole('button', { name: 'Clients' }).click();
  await page.getByPlaceholder('Name or username').fill('kevin keith');
  await page.getByRole('link', { name: /Kevin Keith/ }).click();

  // Client page: profile plus all 3 of Kevin's accounts (admins see every account).
  await expect(page).toHaveURL(/\/admin\/users\/client\/10$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Kevin Keith');
  const accounts = page.getByRole('table', { name: /Accounts for Kevin Keith/ });
  await expect(accounts.getByRole('row')).toHaveCount(4); // header + 3

  // Account page: who can see it, and its documents.
  await accounts.getByRole('link', { name: /Roth IRA/ }).click();
  await expect(page).toHaveURL(/\/admin\/accounts\/\d+$/);
  await expect(page.getByRole('table', { name: /People with access/ })).toContainText('Kevin Keith');
  await expect(page.getByRole('table', { name: /People with access/ })).toContainText('Anthony Gonzalez');
  await page.getByRole('link', { name: /^View details of / }).first().click();

  // Document page: download a .txt, which is recorded and shown under "Who has opened it".
  await expect(page).toHaveURL(/\/admin\/documents\/\d+$/);
  await expect(page.getByText('Uploaded by')).toBeVisible();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download .txt' }).click();
  expect((await download).suggestedFilename()).toMatch(/^[a-z0-9-]+-\d+\.txt$/);
  await expect(page.getByRole('table', { name: /Previews and downloads/ })).toContainText('Downloaded');
});
