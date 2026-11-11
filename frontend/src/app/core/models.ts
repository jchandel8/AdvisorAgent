// Shapes returned by the FastAPI backend (backend/src/wealth/api). Money is in US dollars.

export type PersonKind = 'advisor' | 'client';

export interface Me {
  kind: PersonKind;
  id: number;
  name: string;
  portal: string;
}

export interface DemoUser {
  kind: PersonKind;
  id: number;
  name: string;
  email: string;
  note: string;
  account_count: number;
  client_count: number | null;
}

export interface Account {
  account_id: number;
  account_name: string;
  account_type: 'individual' | 'joint' | 'ira' | 'trust';
  open_date: string;
  owners: string;
  market_value: number;
  as_of_date: string | null;
}

export interface AccountList {
  account_count: number;
  total_market_value: number;
  accounts: Account[];
}

export interface Holding {
  symbol: string;
  description: string;
  sector: string;
  asset_class: 'equity' | 'fixed_income' | 'cash';
  currency: string;
  quantity: number;
  price: number;
  market_value: number;
  cost_basis: number;
  unrealized_gain: number;
  pct_of_selection: number;
  pct_of_portfolio: number;
}

export interface Breakdown {
  positions: number;
  market_value: number;
  cost_basis: number;
  unrealized_gain: number;
  pct_of_selection: number;
  pct_of_portfolio: number;
}

export interface Holdings {
  accounts: { account_id: number; account_name: string; as_of_date: string | null; market_value: number }[];
  portfolio_market_value: number;
  selection: Breakdown;
  sector_summary: (Breakdown & { sector: string })[];
  asset_class_summary: (Breakdown & { asset_class: string })[];
  holdings: Holding[];
}

export type TxnType = 'buy' | 'sell' | 'dividend' | 'deposit' | 'withdrawal';

export interface Transaction {
  id: number;
  account_id: number;
  account_name: string;
  trade_date: string;
  type: TxnType;
  symbol: string | null;
  description: string | null;
  sector: string | null;
  quantity: number | null;
  price: number | null;
  amount: number;
  realized_gain: number | null;
}

export interface TransactionPage {
  page: number;
  page_size: number;
  total_rows: number;
  transactions: Transaction[];
}

export interface Gains {
  realized_total: number;
  unrealized_total: number;
  realized_by_month: { month: string; realized_gain: number; sells: number }[];
  unrealized_by_symbol: {
    symbol: string;
    description: string;
    sector: string;
    market_value: number;
    cost_basis: number;
    unrealized_gain: number;
  }[];
}

export const PERIODS = ['1d', '1m', '3m', '6m', 'ytd', '1y', '2y', '3y', '5y'] as const;
export type Period = (typeof PERIODS)[number];
export type Returns = { [K in `return_${Period}_pct`]: number | null };

export interface Performance {
  combined_market_value_weighted: Returns & { market_value: number };
  partial_periods: Period[];
  accounts: (Returns & { account_id: number; account_name: string; as_of_date: string; market_value: number })[];
  growth: { as_of_date: string; market_value: number; growth_index: number }[];
  note?: string;
}

export interface ClientProfile {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  email: string;
  phone: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
}

export interface AdvisorProfile {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  email: string;
  phone: string | null;
  certifications: string[];
  city: string | null;
  state: string | null;
}

export interface BookClient {
  client_id: number;
  name: string;
  risk_profile: string;
  next_review_date: string | null;
  days_until_review: number | null;
  accessible_account_count: number;
  accessible_market_value: number;
}

export interface Book {
  client_count: number;
  clients: BookClient[];
  account_count: number;
  total_market_value: number;
}

export interface ClientAccounts extends AccountList {
  client_id: number;
  name: string;
}

export interface ToolCall {
  name: string;
  input: Record<string, unknown>;
  is_error: boolean;
}

export interface AssistantReply {
  conversation_id: string;
  answer: string;
  stop_reason: string;
  from_cache: boolean;
  tool_calls: ToolCall[];
}
