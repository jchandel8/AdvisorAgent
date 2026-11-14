// Formatting helpers. Money is USD (the only currency in the data).

const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
const usd0 = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});
const usdCompact = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  notation: 'compact',
  maximumFractionDigits: 1,
});
const qty = new Intl.NumberFormat('en-US', { maximumFractionDigits: 4 });
const longDate = new Intl.DateTimeFormat('en-US', {
  month: 'long',
  day: 'numeric',
  year: 'numeric',
  timeZone: 'UTC',
});
const shortDate = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
  timeZone: 'UTC',
});
const monthYear = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
});

export const money = (v: number | null | undefined): string => (v == null ? '—' : usd.format(v));
export const money0 = (v: number | null | undefined): string => (v == null ? '—' : usd0.format(v));
export const moneyCompact = (v: number): string => usdCompact.format(v);
export const quantity = (v: number | null | undefined): string => (v == null ? '—' : qty.format(v));
export const percent = (v: number | null | undefined, digits = 1): string =>
  v == null ? '—' : `${v.toFixed(digits)}%`;

/** Dates arrive as YYYY-MM-DD; format in UTC so the day never shifts with the viewer's time zone. */
export const dateLong = (iso: string | null | undefined): string =>
  iso ? longDate.format(new Date(iso)) : '—';
export const dateShort = (iso: string | null | undefined): string =>
  iso ? shortDate.format(new Date(iso)) : '—';
export const dateMonth = (iso: string): string => monthYear.format(new Date(iso));

export const accountTypeLabel: Record<string, string> = {
  individual: 'Individual',
  joint: 'Joint',
  ira: 'IRA',
  trust: 'Trust',
};

export const docTypeLabel: Record<string, string> = {
  ips: 'Investment policy',
  review_notes: 'Review notes',
  statement: 'Statement',
  agreement: 'Agreement',
  other: 'Other',
};

export const roleLabel: Record<string, string> = {
  owner: 'Owner',
  joint_owner: 'Joint owner',
  advisor: 'Advisor',
  viewer: 'Viewer',
};

export const assetClassLabel: Record<string, string> = {
  equity: 'Stocks',
  fixed_income: 'Bonds',
  cash: 'Cash',
};

/** Stable color slot for an account: the same account has the same swatch in every portal. */
export const swatchSlot = (accountId: number): number => accountId % 8;
export const swatchVar = (accountId: number): string => `var(--swatch-${swatchSlot(accountId)})`;
