import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import {
  AccountList,
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

  private params(values: Record<string, string | number | readonly string[] | null | undefined>): HttpParams {
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
    return this.http.get<Holdings>('/api/client/holdings', { params: this.params({ account_id: accountId }) });
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
    return this.http.get<Gains>('/api/client/gains', { params: this.params({ account_id: accountId }) });
  }
  clientPerformance(accountId: number | null): Observable<Performance> {
    return this.http.get<Performance>('/api/client/performance', { params: this.params({ account_id: accountId }) });
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
  ask(body: { message: string; conversation_id: string | null; client_id: number | null }): Observable<AssistantReply> {
    return this.http.post<AssistantReply>('/api/advisor/assistant/messages', body);
  }
}
