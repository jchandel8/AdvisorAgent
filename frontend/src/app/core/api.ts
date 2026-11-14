import { HttpClient, HttpParams, HttpResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import {
  AccountAccess,
  AccountList,
  AccountDetail,
  AdminAccount,
  AdminUser,
  DocumentDetail,
  DocumentPage,
  SharedDocuments,
  UploadAccount,
  UserDetail,
  UserKind,
  AgentRunDetail,
  AgentRunFilters,
  AgentRunPage,
  AssistantEvent,
  AuditEvent,
  NewAccount,
  NewUser,
  Paged,
  Person,
  AdvisorProfile,
  AssistantReply,
  Book,
  ClientAccounts,
  ClientProfile,
  DemoUser,
  Gains,
  Holdings,
  Me,
  Performance,
  TransactionPage,
  TxnType,
} from './models';

/** Thin typed wrapper over the backend. Identity is added by the session interceptor, never by callers. */
@Injectable({ providedIn: 'root' })
export class Api {
  private readonly http = inject(HttpClient);

  private params(
    values: Record<string, string | number | readonly string[] | null | undefined>,
  ): HttpParams {
    let p = new HttpParams();
    for (const [key, value] of Object.entries(values)) {
      if (value === null || value === undefined) continue;
      if (Array.isArray(value)) value.forEach((v) => (p = p.append(key, v)));
      else p = p.set(key, String(value));
    }
    return p;
  }

  // Shared
  me(): Observable<Me> {
    return this.http.get<Me>('/api/me');
  }
  demoUsers(): Observable<{ users: DemoUser[] }> {
    return this.http.get<{ users: DemoUser[] }>('/api/demo/users');
  }

  // Client portal
  clientProfile(): Observable<ClientProfile> {
    return this.http.get<ClientProfile>('/api/client/profile');
  }
  clientAccounts(): Observable<AccountList> {
    return this.http.get<AccountList>('/api/client/accounts');
  }
  clientHoldings(accountId: number | null): Observable<Holdings> {
    return this.http.get<Holdings>('/api/client/holdings', {
      params: this.params({ account_id: accountId }),
    });
  }
  clientTransactions(q: {
    accountId: number | null;
    types: TxnType[];
    page: number;
    pageSize: number;
  }): Observable<TransactionPage> {
    return this.http.get<TransactionPage>('/api/client/transactions', {
      params: this.params({
        account_id: q.accountId,
        types: q.types.length ? q.types : null,
        page: q.page,
        page_size: q.pageSize,
      }),
    });
  }
  clientGains(accountId: number | null): Observable<Gains> {
    return this.http.get<Gains>('/api/client/gains', {
      params: this.params({ account_id: accountId }),
    });
  }
  clientPerformance(accountId: number | null): Observable<Performance> {
    return this.http.get<Performance>('/api/client/performance', {
      params: this.params({ account_id: accountId }),
    });
  }

  // Advisor portal
  advisorProfile(): Observable<AdvisorProfile> {
    return this.http.get<AdvisorProfile>('/api/advisor/profile');
  }
  advisorBook(): Observable<Book> {
    return this.http.get<Book>('/api/advisor/clients');
  }
  advisorClientAccounts(clientId: number): Observable<ClientAccounts> {
    return this.http.get<ClientAccounts>(`/api/advisor/clients/${clientId}/accounts`);
  }
  ask(body: {
    message: string;
    conversation_id: string | null;
    client_id: number | null;
  }): Observable<AssistantReply> {
    return this.http.post<AssistantReply>('/api/advisor/assistant/messages', body);
  }

  // Documents (advisor and client portals)
  documents(): Observable<SharedDocuments> {
    return this.http.get<SharedDocuments>('/api/documents');
  }
  documentsNewCount(): Observable<{ new_count: number }> {
    return this.http.get<{ new_count: number }>('/api/documents/new-count');
  }
  uploadAccounts(): Observable<{ accounts: UploadAccount[] }> {
    return this.http.get<{ accounts: UploadAccount[] }>('/api/documents/accounts');
  }
  uploadDocument(form: FormData): Observable<{ document_id: number; title: string }> {
    return this.http.post<{ document_id: number; title: string }>('/api/documents', form);
  }
  /** The file, through HttpClient so the sign-in token is sent. Opening is recorded by the server. */
  documentFile(id: number, inline: boolean): Observable<HttpResponse<Blob>> {
    return this.http.get(`/api/documents/${id}/file`, {
      params: this.params({ disposition: inline ? 'inline' : 'attachment' }),
      observe: 'response',
      responseType: 'blob',
    });
  }
  deleteDocument(id: number): Observable<{ deleted: number }> {
    return this.http.delete<{ deleted: number }>(`/api/documents/${id}`);
  }

  // Admin portal
  adminUsers(kind: 'advisor' | 'client' | 'admin', q: string): Observable<{ users: AdminUser[] }> {
    return this.http.get<{ users: AdminUser[] }>('/api/admin/users', {
      params: this.params({ kind, q }),
    });
  }
  createUser(
    body: NewUser,
  ): Observable<{ id: number; username: string; name: string; kind: string }> {
    return this.http.post<{ id: number; username: string; name: string; kind: string }>(
      '/api/admin/users',
      body,
    );
  }
  adminAccounts(q: string): Observable<{ accounts: AdminAccount[] }> {
    return this.http.get<{ accounts: AdminAccount[] }>('/api/admin/accounts', {
      params: this.params({ q }),
    });
  }
  createAccount(body: NewAccount): Observable<{ account_id: number; account_name: string }> {
    return this.http.post<{ account_id: number; account_name: string }>(
      '/api/admin/accounts',
      body,
    );
  }
  accountAccess(accountId: number): Observable<AccountAccess> {
    return this.http.get<AccountAccess>(`/api/admin/accounts/${accountId}/access`);
  }
  findPeople(
    q: string,
    kind: 'advisor' | 'client' | null = null,
  ): Observable<{ people: Person[] }> {
    return this.http.get<{ people: Person[] }>('/api/admin/people', {
      params: this.params({ q, kind }),
    });
  }
  grant(body: {
    account_id: number;
    person_type: string;
    person_id: number;
    role: string;
  }): Observable<unknown> {
    return this.http.post('/api/admin/access', body);
  }
  revoke(accessId: number): Observable<unknown> {
    return this.http.delete(`/api/admin/access/${accessId}`);
  }
  /** The audit log, newest first; with adminId, only that admin's entries. */
  auditLog(page: number, adminId: number | null = null): Observable<Paged<AuditEvent>> {
    return this.http.get<Paged<AuditEvent>>('/api/admin/audit', {
      params: this.params({ page, admin_id: adminId }),
    });
  }
  adminUser(kind: UserKind, id: number): Observable<UserDetail> {
    return this.http.get<UserDetail>(`/api/admin/users/${kind}/${id}`);
  }
  adminAccount(id: number): Observable<AccountDetail> {
    return this.http.get<AccountDetail>(`/api/admin/accounts/${id}`);
  }
  adminDocuments(q: string, docType: string | null, page: number): Observable<DocumentPage> {
    return this.http.get<DocumentPage>('/api/admin/documents', {
      params: this.params({ q: q || null, doc_type: docType, page }),
    });
  }
  adminDocument(id: number): Observable<DocumentDetail> {
    return this.http.get<DocumentDetail>(`/api/admin/documents/${id}`);
  }
  /** The text for the preview. The server records the view in the audit log. */
  documentContent(id: number): Observable<{ document_id: number; text: string }> {
    return this.http.get<{ document_id: number; text: string }>(
      `/api/admin/documents/${id}/content`,
    );
  }
  /** The .txt file. Fetched through HttpClient (not a plain link) so the sign-in token is sent.
   *  The server records the download in the audit log. */
  downloadDocument(id: number): Observable<HttpResponse<Blob>> {
    return this.http.get(`/api/admin/documents/${id}/download`, {
      observe: 'response',
      responseType: 'blob',
    });
  }
  assistantLog(page: number, blockedOnly: boolean): Observable<Paged<AssistantEvent>> {
    return this.http.get<Paged<AssistantEvent>>('/api/admin/assistant-events', {
      params: this.params({ page, blocked_only: String(blockedOnly) }),
    });
  }
  agentRuns(page: number, f: AgentRunFilters = {}): Observable<AgentRunPage> {
    return this.http.get<AgentRunPage>('/api/admin/agent-runs', {
      params: this.params({
        page,
        advisor_id: f.advisorId,
        client_id: f.clientId,
        feature: f.feature,
        outcome: f.outcome,
      }),
    });
  }
  /** Opening a run is recorded in the audit log (it shows client data). */
  agentRun(id: number): Observable<AgentRunDetail> {
    return this.http.get<AgentRunDetail>(`/api/admin/agent-runs/${id}`);
  }
}
