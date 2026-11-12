import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { of } from 'rxjs';
import { Api } from '../../core/api';
import { accountTypeLabel, dateShort, money, percent } from '../../core/format';
import { accountParam } from '../../shared/filters';
import { Empty, ErrorState, Icon, Loading, Swatch, isNotFound } from '../../shared/ui';

@Component({
  selector: 'app-advisor-accounts',
  imports: [RouterLink, Swatch, Icon, Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="space-y-4">
      <h1 class="text-[1.75rem] font-semibold">Accounts</h1>
      <label class="flex max-w-md flex-col gap-1 text-sm">
        <span class="text-ink-muted">Client</span>
        <select
          class="min-h-11 rounded-[var(--radius-control)] border border-rule-strong bg-surface px-3 text-base"
          (change)="choose($any($event.target).value)"
        >
          <!-- [selected] per option, not [value] on the select: the options arrive after the URL is read. -->
          <option value="" [selected]="!knownClient()">Choose a client</option>
          @for (c of clients(); track c.client_id) {
            <option [value]="c.client_id" [selected]="c.client_id === clientId()">
              {{ c.name }} (#{{ c.client_id }})
            </option>
          }
        </select>
      </label>
    </header>

    <div class="mt-8">
      @if (clientId() === null) {
        <app-empty message="Choose a client to see the accounts you manage for them." />
      } @else if (detail.isLoading()) {
        <app-loading what="accounts" [rows]="4" />
      } @else if (notFound()) {
        <app-empty message="That client isn't one of yours. Choose a client from the list." />
      } @else if (detail.error()) {
        <app-error (retry)="detail.reload()" />
      } @else if (detail.value(); as d) {
        <section class="max-w-[66ch] space-y-2" aria-label="Summary">
          <p class="text-xl">
            You manage {{ d.account_count }}
            {{ d.account_count === 1 ? 'account' : 'accounts' }} for {{ d.name }}, worth
            <span class="num font-semibold">{{ money(d.total_market_value) }}</span>.
          </p>
          <p class="text-sm text-ink-muted">
            Only accounts you have access to are listed. If {{ d.name }} holds accounts with another
            advisor, they don't appear here and aren't included in any total.
          </p>
        </section>

        <div
          class="mt-6 overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface"
        >
          <table class="ledger w-full min-w-[44rem] text-[0.9375rem]">
            <caption class="sr-only">
              Accounts you manage for
              {{
                d.name
              }}
            </caption>
            <thead class="text-left text-sm text-ink-muted">
              <tr>
                <th scope="col" class="px-5 py-3 font-medium">Account</th>
                <th scope="col" class="px-5 py-3 font-medium">Type</th>
                <th scope="col" class="px-5 py-3 font-medium">Owners</th>
                <th scope="col" class="px-5 py-3 font-medium">Opened</th>
                <th scope="col" class="px-5 py-3 text-right font-medium">Market value</th>
                <th scope="col" class="px-5 py-3 text-right font-medium">Share</th>
              </tr>
            </thead>
            <tbody>
              @for (a of d.accounts; track a.account_id) {
                <tr class="border-t border-rule">
                  <th scope="row" class="max-w-64 px-5 py-3 text-left font-medium">
                    <app-swatch [accountId]="a.account_id" [label]="a.account_name" />
                  </th>
                  <td class="px-5 py-3">{{ typeLabel[a.account_type] }}</td>
                  <td class="px-5 py-3 text-ink-muted">{{ a.owners }}</td>
                  <td class="num px-5 py-3 whitespace-nowrap">{{ dateShort(a.open_date) }}</td>
                  <td class="num px-5 py-3 text-right">{{ money(a.market_value) }}</td>
                  <td class="num px-5 py-3 text-right text-ink-muted">
                    {{ percent((100 * a.market_value) / (d.total_market_value || 1)) }}
                  </td>
                </tr>
              }
            </tbody>
            <tfoot>
              <tr class="border-t border-rule-strong font-semibold">
                <th scope="row" colspan="4" class="px-5 py-3 text-left">Total you manage</th>
                <td class="num px-5 py-3 text-right">{{ money(d.total_market_value) }}</td>
                <td class="num px-5 py-3 text-right">100.0%</td>
              </tr>
            </tfoot>
          </table>
        </div>

        <a
          class="mt-6 inline-flex min-h-11 items-center gap-2 rounded-[var(--radius-control)] bg-advisor px-4 font-medium text-paper hover:opacity-90"
          [routerLink]="['/advisor/assistant']"
          [queryParams]="{ client: d.client_id }"
        >
          <app-icon name="chat" /> Ask the assistant about {{ d.name }}
        </a>
      }
    </div>
  `,
})
export class AdvisorAccounts {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  /** ?client= from the URL. It is only a selection: the API returns 404 for a client you don't share. */
  readonly client = input<string>();
  protected readonly clientId = computed(() => accountParam(this.client()));

  protected readonly money = money;
  protected readonly percent = percent;
  protected readonly dateShort = dateShort;
  protected readonly typeLabel = accountTypeLabel;

  private readonly book = rxResource({ stream: () => this.api.advisorBook() });
  protected readonly clients = computed(() =>
    [...(this.book.value()?.clients ?? [])].sort((a, b) => a.name.localeCompare(b.name)),
  );
  protected readonly knownClient = computed(() =>
    this.clients().some((c) => c.client_id === this.clientId()),
  );
  protected readonly detail = rxResource({
    params: () => ({ id: this.clientId() }),
    stream: ({ params }) =>
      params.id === null ? of(null) : this.api.advisorClientAccounts(params.id),
  });
  protected readonly notFound = computed(() => isNotFound(this.detail.error()));

  protected choose(value: string): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { client: value || null },
    });
  }
}
