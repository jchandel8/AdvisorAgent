import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { Api } from '../../core/api';
import { dateShort, money } from '../../core/format';
import { BookClient } from '../../core/models';
import { Session } from '../../core/session';
import { Empty, ErrorState, Icon, Loading } from '../../shared/ui';

type SortKey = 'value' | 'review' | 'name';

@Component({
  selector: 'app-advisor-dashboard',
  imports: [RouterLink, Icon, Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (book.isLoading()) {
      <app-loading what="your clients" [rows]="8" />
    } @else if (book.error()) {
      <app-error (retry)="book.reload()" />
    } @else if (book.value(); as b) {
      <header class="max-w-[66ch] space-y-2">
        <h1 class="text-[1.75rem] font-semibold">
          {{ firstName() }}, you look after {{ b.client_count }} clients with
          <span class="num">{{ money(b.total_market_value) }}</span> across
          {{ b.account_count }} accounts.
        </h1>
        <p class="text-ink-muted">
          {{ dueSoon() }} {{ dueSoon() === 1 ? 'review is' : 'reviews are' }} due in the next 30
          days{{ overdue() ? ', and ' + overdue() + ' overdue' : '' }}. Totals count only the
          accounts you have access to; a joint account counts once.
        </p>
      </header>

      <section class="mt-10" aria-labelledby="clients-title">
        <div class="mb-4 flex flex-wrap items-end justify-between gap-4">
          <h2 id="clients-title" class="text-xl font-semibold">Clients</h2>
          <div class="flex flex-wrap items-end gap-3">
            <label class="flex flex-col gap-1 text-sm">
              <span class="text-ink-muted">Find a client</span>
              <input
                type="search"
                class="min-h-11 w-60 rounded-[var(--radius-control)] border border-rule-strong bg-surface px-3"
                placeholder="Name"
                [value]="query()"
                (input)="query.set($any($event.target).value)"
              />
            </label>
            <label class="flex flex-col gap-1 text-sm">
              <span class="text-ink-muted">Sort by</span>
              <select
                class="min-h-11 rounded-[var(--radius-control)] border border-rule-strong bg-surface px-3"
                [value]="sort()"
                (change)="sort.set($any($event.target).value)"
              >
                <option value="value">Value, highest first</option>
                <option value="review">Next review, soonest first</option>
                <option value="name">Name</option>
              </select>
            </label>
          </div>
        </div>

        @if (rows().length === 0) {
          <app-empty
            [message]="
              b.client_count
                ? 'No clients match that name.'
                : 'You don’t have access to any accounts yet. An administrator can grant access.'
            "
          />
        } @else {
          <div class="overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface">
            <table class="ledger w-full min-w-[52rem] text-[0.9375rem]">
              <caption class="sr-only">
                Your clients
              </caption>
              <thead class="text-left text-sm text-ink-muted">
                <tr>
                  <th scope="col" class="px-4 py-3 font-medium">Client</th>
                  <th scope="col" class="px-4 py-3 font-medium">Risk profile</th>
                  <th scope="col" class="px-4 py-3 text-right font-medium">Accounts</th>
                  <th scope="col" class="px-4 py-3 text-right font-medium">Value you manage</th>
                  <th scope="col" class="px-4 py-3 font-medium">Next review</th>
                  <th scope="col" class="px-4 py-3 font-medium">
                    <span class="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                @for (c of rows(); track c.client_id) {
                  <tr class="border-t border-rule">
                    <th scope="row" class="px-4 py-3 text-left font-medium">
                      {{ c.name }}
                      <span class="num ml-1 text-sm font-normal text-ink-muted"
                        >#{{ c.client_id }}</span
                      >
                    </th>
                    <td class="px-4 py-3 capitalize">{{ c.risk_profile }}</td>
                    <td class="num px-4 py-3 text-right">{{ c.accessible_account_count }}</td>
                    <td class="num px-4 py-3 text-right font-medium">
                      {{ money(c.accessible_market_value) }}
                    </td>
                    <td class="px-4 py-3 whitespace-nowrap">
                      <span class="num">{{ dateShort(c.next_review_date) }}</span>
                      @if (c.days_until_review !== null && c.days_until_review < 0) {
                        <span
                          class="ml-2 rounded-full border border-loss px-2 py-0.5 text-xs font-medium text-loss"
                          >Overdue</span
                        >
                      } @else if (c.days_until_review !== null && c.days_until_review <= 30) {
                        <span
                          class="ml-2 rounded-full border border-rule-strong px-2 py-0.5 text-xs"
                          >In {{ c.days_until_review }} days</span
                        >
                      }
                    </td>
                    <td class="px-4 py-2 text-right whitespace-nowrap">
                      <a
                        class="inline-flex min-h-11 items-center gap-1.5 rounded-[var(--radius-control)] px-3 text-sm text-advisor hover:bg-advisor-soft"
                        [routerLink]="['/advisor/accounts']"
                        [queryParams]="{ client: c.client_id }"
                        [attr.aria-label]="'Accounts for ' + c.name"
                      >
                        <app-icon name="briefcase" [size]="16" /> Accounts
                      </a>
                      <a
                        class="inline-flex min-h-11 items-center gap-1.5 rounded-[var(--radius-control)] px-3 text-sm text-advisor hover:bg-advisor-soft"
                        [routerLink]="['/advisor/assistant']"
                        [queryParams]="{ client: c.client_id }"
                        [attr.aria-label]="'Ask the assistant about ' + c.name"
                      >
                        <app-icon name="chat" [size]="16" /> Ask
                      </a>
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      </section>
    }
  `,
})
export class AdvisorDashboard {
  private readonly api = inject(Api);
  private readonly session = inject(Session);

  protected readonly money = money;
  protected readonly dateShort = dateShort;

  protected readonly book = rxResource({ stream: () => this.api.advisorBook() });
  protected readonly query = signal('');
  protected readonly sort = signal<SortKey>('value');

  protected readonly firstName = computed(() => this.session.user()?.name.split(' ')[0] ?? 'Hello');
  private readonly clients = computed(() => this.book.value()?.clients ?? []);
  protected readonly overdue = computed(
    () => this.clients().filter((c) => (c.days_until_review ?? 1) < 0).length,
  );
  protected readonly dueSoon = computed(
    () =>
      this.clients().filter(
        (c) =>
          c.days_until_review !== null && c.days_until_review >= 0 && c.days_until_review <= 30,
      ).length,
  );

  protected readonly rows = computed<BookClient[]>(() => {
    const q = this.query().trim().toLowerCase();
    const filtered = this.clients().filter((c) => !q || c.name.toLowerCase().includes(q));
    const byReview = (c: BookClient) => c.days_until_review ?? Number.MAX_SAFE_INTEGER;
    return [...filtered].sort((a, b) => {
      switch (this.sort()) {
        case 'review':
          return byReview(a) - byReview(b);
        case 'name':
          return a.name.localeCompare(b.name);
        default:
          return b.accessible_market_value - a.accessible_market_value;
      }
    });
  });
}
