// Shapes returned by the FastAPI backend (backend/src/wealth/api). Money is in US dollars.

export type PersonKind = 'advisor' | 'client' | 'admin';

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
  username: string;
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
  accounts: {
    account_id: number;
    account_name: string;
    as_of_date: string | null;
    market_value: number;
  }[];
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
  accounts: (Returns & {
    account_id: number;
    account_name: string;
    as_of_date: string;
    market_value: number;
  })[];
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
  /** A guardrail stopped the question (off-topic, manipulation) or an unsupported answer. */
  blocked: boolean;
  tool_calls: ToolCall[];
}

// ---- Admin portal --------------------------------------------------------------------------------------

export interface AdminUser {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  email: string;
  risk_profile?: string;
  account_count?: number;
  client_count?: number;
}

export interface NewUser {
  kind: 'advisor' | 'client';
  first_name: string;
  last_name: string;
  email: string;
  username?: string | null;
  phone?: string | null;
  city?: string | null;
  state?: string | null;
  risk_profile?: string;
}

export interface AdminAccount {
  account_id: number;
  account_name: string;
  account_type: string;
  open_date: string;
  close_date: string | null;
  clients: string | null;
  advisors: string | null;
}

export interface NewAccount {
  account_name: string;
  account_type: 'individual' | 'joint' | 'ira' | 'trust';
  description?: string | null;
  owner_client_ids: number[];
  advisor_ids: number[];
}

export interface AccessRow {
  access_id: number;
  person_type: 'advisor' | 'client';
  person_id: number;
  name: string;
  username: string;
  role: string;
  granted_at: string;
  granted_by: string | null;
}

export interface AccountAccess {
  account_id: number;
  account_name: string;
  account_type: string;
  open_date: string;
  close_date: string | null;
  access: AccessRow[];
}

export interface Person {
  person_type: 'advisor' | 'client';
  person_id: number;
  name: string;
  username: string;
}

export interface AuditEvent {
  id: number;
  created_at: string;
  admin_id: number | null;
  admin_name: string;
  action: string;
  account_id: number | null;
  document_id: number | null;
  summary: string;
}

export type UserKind = 'advisor' | 'client' | 'admin';

export interface UserProfile {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  email: string;
  created_at: string;
  phone?: string | null;
  certifications?: string[] | null;
  address?: string | null;
  city?: string | null;
  state?: string | null;
  risk_profile?: string;
  target_allocation?: Record<string, number>;
  next_review_date?: string | null;
}

export interface UserAccount {
  account_id: number;
  account_name: string;
  account_type: string;
  open_date: string;
  close_date: string | null;
  role: string;
  granted_at: string;
  clients: string | null;
  advisors: string | null;
}

export interface UserDetail {
  kind: UserKind;
  profile: UserProfile;
  accounts: UserAccount[];
}

export interface AdminDocument {
  document_id: number;
  title: string;
  doc_type: string;
  size_kb: number;
  created_date: string;
  uploaded_at: string | null;
  deleted_at: string | null;
  note: string | null;
  content_type: string | null;
  original_filename: string | null;
  account_id: number;
  account_name: string;
  uploaded_by_type: 'advisor' | 'client' | null;
  uploaded_by_id: number | null;
  uploaded_by: string | null;
  previewable: boolean;
}

export interface DocumentPage {
  page: number;
  page_size: number;
  total_rows: number;
  documents: AdminDocument[];
}

/** One open of a document, from the admin portal or the advisor/client portals. */
export interface DocumentOpen {
  key: string;
  created_at: string;
  person_type: 'admin' | 'advisor' | 'client';
  person_id: number | null;
  name: string;
  action: 'view' | 'download';
}

export interface DocumentDetail extends AdminDocument {
  access_log: DocumentOpen[];
}

export interface AccountDetail extends AccountAccess {
  description: string | null;
  documents: AdminDocument[];
}

export interface AssistantEvent {
  id: number;
  created_at: string;
  advisor_name: string;
  outcome: string;
  question: string;
  reason: string | null;
  run_id: number | null; // its full trace, when one was recorded
}

// ---- Agent runs (full traces, admin portal) --------------------------------------------------------------

export interface AgentRun {
  id: number;
  feature: 'assistant' | 'finalyst';
  started_at: string;
  finished_at: string;
  duration_ms: number;
  advisor_id: number;
  advisor_name: string;
  focus_client_id: number | null;
  focus_client_name: string | null;
  question: string;
  outcome: string;
  model: string | null;
  model_calls: number;
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost_usd: string | number | null;
  cache_hit_pct: string | number | null;
}

export interface AgentStep {
  seq: number;
  kind: 'scope_check' | 'model' | 'tool' | 'cache' | 'note';
  name: string;
  started_at: string;
  duration_ms: number;
  request: unknown;
  response: unknown;
  truncated: boolean;
  is_error: boolean;
  stop_reason: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cache_read_tokens: number | null;
  cache_write_tokens: number | null;
}

export interface AgentRunDetail extends AgentRun {
  answer: string | null;
  conversation_id: string | null;
  assistant_event_id: number | null;
  prompt_hash: string | null;
  prompt_role: string | null;
  system_prompt: string | null;
  tool_definitions: { name: string; description: string; input_schema: unknown }[] | null;
  steps: AgentStep[];
}

export interface AgentRunPage {
  page: number;
  page_size: number;
  total_rows: number;
  runs: AgentRun[];
}

export interface AgentRunFilters {
  advisorId?: number | null;
  clientId?: number | null;
  feature?: 'assistant' | 'finalyst' | null;
  outcome?: string | null;
}

export interface Paged<T> {
  page: number;
  page_size: number;
  total_rows: number;
  events: T[];
}

// ---- Shared documents (advisor and client portals) ------------------------------------------------------

export interface SharedDocument {
  document_id: number;
  title: string;
  doc_type: string;
  note: string | null;
  created_date: string;
  uploaded_at: string | null;
  size_kb: number;
  content_type: string | null;
  original_filename: string | null;
  account_id: number;
  account_name: string;
  uploaded_by_type: 'advisor' | 'client' | null;
  uploaded_by: string | null;
  mine: boolean;
  is_new: boolean;
  opened_by: string | null;
}

export interface SharedDocuments {
  new_count: number;
  documents: SharedDocument[];
}

export interface UploadAccount {
  account_id: number;
  account_name: string;
  account_type: string;
  role: string;
  clients: string | null;
}
