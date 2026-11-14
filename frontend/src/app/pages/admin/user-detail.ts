import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { of } from 'rxjs';
import { Api } from '../../core/api';
import { accountTypeLabel, dateLong, dateShort, roleLabel } from '../../core/format';
import { UserDetail, UserKind } from '../../core/models';
import { Fields } from '../../shared/filters';
import { httpStatus } from '../../shared/person-picker';
import { Empty, ErrorState, Icon, Loading, Swatch } from '../../shared/ui';
import { ACTION_LABEL, fmt } from './logs';

const KINDS: readonly UserKind[] = ['advisor', 'client', 'admin'];
const KIND_LABEL: Record<UserKind, string> = { advisor: 'Advisor', client: 'Client', admin: 'Admin' };

/** One user: their profile, then the accounts they can see (advisors, clients) or what they did (admins). */
@Component({
  selector: 'app-admin-user-detail',
  imports: [RouterLink, Fields, Swatch, Icon, Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <a
      routerLink="/admin/users"
      [queryParams]="{ kind: userKind() }"
      class="inline-flex min-h-11 items-center gap-2 text-sm text-admin hover:underline"
      ><app-icon name="back" [size]="16" /> All users</a
    >

    @if (userKind() === null || userId() === null) {
      <app-empty class="mt-6 block" message="That isn't a user page. Go back to all users." />
    } @else if (user.isLoading() && !user.value()) {
      <app-loading what="this user" [rows]="6" />
    } @else if (user.error()) {
      @if (notFound()) {
        <app-empty class="mt-6 block" message="There's no user with that ID." />
      } @else {
        <app-error (retry)="user.reload()" />
      }
    } @else if (user.value(); as u) {
      <header class="mt-2 space-y-1">
        <h1 class="text-[1.75rem] font-semibold">
          {{ u.profile.first_name }} {{ u.profile.last_name }}
        </h1>
        <p class="text-ink-muted">
          {{ kindLabel[u.kind] }} #{{ u.profile.id }}, added {{ dateLong(u.profile.created_at) }}
        </p>
      </header>

      <section class="mt-8 max-w-3xl" aria-labelledby="profile-title">
        <h2 id="profile-title" class="mb-3 text-xl font-semibold">Profile</h2>
        <app-fields [fields]="fields()" />
      </section>

      @if (u.kind !== 'admin') {
        <section class="mt-10" aria-labelledby="accounts-title">
          <h2 id="accounts-title" class="text-xl font-semibold">Accounts</h2>
          <p class="mt-1 mb-4 max-w-[66ch] text-ink-muted">
            @if (u.kind === 'advisor') {
              Every account this advisor can see, and the clients on it. They see nothing else.
            } @else {
              Every account this client is on, and the advisors who can see it.
            }
          </p>
          @if (!u.accounts.length) {
            <app-empty
              message="No accounts yet. Grant access on the Permissions page to give them some."
            />
          } @else {
            <div class="overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface">
              <table class="ledger w-full min-w-[52rem] text-[0.9375rem]">
                <caption class="sr-only">
                  Accounts for {{ u.profile.first_name }} {{ u.profile.last_name }}
                </caption>
                <thead class="text-left text-sm text-ink-muted">
                  <tr>
                    <th scope="col" class="px-4 py-3 font-medium">Account</th>
                    <th scope="col" class="px-4 py-3 font-medium">Type</th>
                    <th scope="col" class="px-4 py-3 font-medium">Their role</th>
                    <th scope="col" class="px-4 py-3 font-medium">
                      {{ u.kind === 'advisor' ? 'Clients' : 'Owners' }}
                    </th>
                    <th scope="col" class="px-4 py-3 font-medium">Advisors</th>
                    <th scope="col" class="px-4 py-3 font-medium">Access since</th>
                  </tr>
                </thead>
                <tbody>
                  @for (a of u.accounts; track a.account_id) {
                    <tr class="border-t border-rule">
                      <th scope="row" class="max-w-64 px-4 py-3 text-left font-medium">
                        <a
                          class="inline-flex min-h-11 max-w-full items-center hover:underline"
                          [routerLink]="['/admin/accounts', a.account_id]"
                          ><app-swatch
                            [accountId]="a.account_id"
                            [label]="a.account_name + ' #' + a.account_id"
                        /></a>
                      </th>
                      <td class="px-4 py-3">
                        {{ typeLabel[a.account_type] }}{{ a.close_date ? ' (closed)' : '' }}
                      </td>
                      <td class="px-4 py-3">{{ roleLabel[a.role] ?? a.role }}</td>
                      <td class="px-4 py-3 text-ink-muted">{{ a.clients || '—' }}</td>
                      <td class="px-4 py-3 text-ink-muted">{{ a.advisors || '—' }}</td>
                      <td class="num px-4 py-3 whitespace-nowrap">{{ dateShort(a.granted_at) }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          }
        </section>
      } @else {
        <section class="mt-10" aria-labelledby="activity-title">
          <h2 id="activity-title" class="text-xl font-semibold">Activity</h2>
          <p class="mt-1 mb-4 max-w-[66ch] text-ink-muted">
            Every change this admin made and every document they opened, newest first.
          </p>
          @if (activity.isLoading() && !activity.value()) {
            <app-loading what="activity" [rows]="4" />
          } @else if (activity.error()) {
            <app-error (retry)="activity.reload()" />
          } @else if (activity.value(); as l) {
            @if (!l.events.length) {
              <app-empty message="Nothing yet. Changes and document views will show up here." />
            } @else {
              <div
                class="overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface"
              >
                <table class="ledger w-full min-w-[40rem] text-[0.9375rem]">
                  <caption class="sr-only">
                    Activity, newest first
                  </caption>
                  <thead class="text-left text-sm text-ink-muted">
                    <tr>
                      <th scope="col" class="px-4 py-3 font-medium">When</th>
                      <th scope="col" class="px-4 py-3 font-medium">Action</th>
                      <th scope="col" class="px-4 py-3 font-medium">Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    @for (e of l.events; track e.id) {
                      <tr class="border-t border-rule">
                        <td class="num px-4 py-3 whitespace-nowrap">{{ fmt(e.created_at) }}</td>
                        <td class="px-4 py-3">{{ actionLabel[e.action] ?? e.action }}</td>
                        <td class="px-4 py-3">
                          @if (e.document_id) {
                            <a
                              class="hover:underline"
                              [routerLink]="['/admin/documents', e.document_id]"
                              >{{ e.summary }}</a
                            >
                          } @else if (e.account_id) {
                            <a class="hover:underline" [routerLink]="['/admin/accounts', e.account_id]">{{
                              e.summary
                            }}</a>
                          } @else {
                            {{ e.summary }}
                          }
                        </td>
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
              @if (l.total_rows > l.page_size) {
                <nav class="mt-4 flex items-center justify-between gap-3" aria-label="Pages">
                  <p class="num text-sm text-ink-muted">
                    Page {{ l.page }} of {{ pages(l.total_rows, l.page_size) }}
                  </p>
                  <div class="flex gap-2">
                    <button
                      type="button"
                      class="min-h-11 rounded-[var(--radius-control)] border border-rule-strong px-4 text-sm disabled:opacity-50"
                      [disabled]="page() <= 1"
                      (click)="page.set(page() - 1)"
                    >
                      Previous
                    </button>
                    <button
                      type="button"
                      class="min-h-11 rounded-[var(--radius-control)] border border-rule-strong px-4 text-sm disabled:opacity-50"
                      [disabled]="page() >= pages(l.total_rows, l.page_size)"
                      (click)="page.set(page() + 1)"
                    >
                      Next
                    </button>
                  </div>
                </nav>
              }
            }
          }
        </section>
      }
    }
  `,
})
export class AdminUserDetail {
  private readonly api = inject(Api);
  /** Route parameters (:kind/:id). */
  readonly kind = input<string>();
  readonly id = input<string>();

  protected readonly userKind = computed<UserKind | null>(() => {
    const k = this.kind() as UserKind;
    return KINDS.includes(k) ? k : null;
  });
  protected readonly userId = computed<number | null>(() => {
    const n = Number(this.id());
    return Number.isInteger(n) && n > 0 ? n : null;
  });

  protected readonly user = rxResource<UserDetail | undefined, { kind: UserKind | null; id: number | null }>({
    params: () => ({ kind: this.userKind(), id: this.userId() }),
    stream: ({ params }) =>
      params.kind && params.id ? this.api.adminUser(params.kind, params.id) : of(undefined),
  });
  protected readonly notFound = computed(
    () => httpStatus(this.user.error()) === 404,
  );

  protected readonly page = signal(1);
  protected readonly activity = rxResource({
    params: () => ({ id: this.userKind() === 'admin' ? this.userId() : null, page: this.page() }),
    stream: ({ params }) =>
      params.id ? this.api.auditLog(params.page, params.id) : of(undefined),
  });

  protected readonly fields = computed(() => {
    const u = this.user.value();
    if (!u) return [];
    const p = u.profile;
    const common = [
      { label: 'Username', value: p.username },
      { label: 'First name', value: p.first_name },
      { label: 'Last name', value: p.last_name },
      { label: 'Email', value: p.email },
    ];
    if (u.kind === 'advisor') {
      return [
        ...common,
        { label: 'Phone', value: p.phone },
        { label: 'Certifications', value: (p.certifications ?? []).join(', ') },
        { label: 'City', value: p.city },
        { label: 'State', value: p.state },
      ];
    }
    if (u.kind === 'client') {
      return [
        ...common,
        { label: 'Phone', value: p.phone },
        { label: 'Address', value: [p.address, p.city, p.state].filter(Boolean).join(', ') },
        { label: 'Risk profile', value: capitalize(p.risk_profile) },
        { label: 'Target allocation', value: allocation(p.target_allocation) },
        { label: 'Next review', value: p.next_review_date ? dateLong(p.next_review_date) : null },
      ];
    }
    return common;
  });

  protected readonly kindLabel = KIND_LABEL;
  protected readonly typeLabel = accountTypeLabel;
  protected readonly roleLabel = roleLabel;
  protected readonly actionLabel = ACTION_LABEL;
  protected readonly dateLong = dateLong;
  protected readonly dateShort = dateShort;
  protected readonly fmt = fmt;
  protected pages(total: number, size: number): number {
    return Math.max(1, Math.ceil(total / size));
  }
}

const capitalize = (s: string | undefined) => (s ? s[0].toUpperCase() + s.slice(1) : null);

const ALLOCATION_LABEL: Record<string, string> = {
  equity: 'stocks',
  fixed_income: 'bonds',
  cash: 'cash',
};

function allocation(a: Record<string, number> | undefined): string | null {
  if (!a) return null;
  return Object.entries(a)
    .map(([k, v]) => `${Math.round(v * 100)}% ${ALLOCATION_LABEL[k] ?? k}`)
    .join(', ');
}
