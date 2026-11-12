import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { Api } from '../../core/api';
import { assetClassLabel, money, money0, percent, quantity } from '../../core/format';
import { Holding } from '../../core/models';
import { Chart, ChartTable, ChartTokens } from '../../shared/chart';
import { topHoldingsOption } from '../../shared/holdings-chart';
import { AccountFilter, AllocationBar, accountParam } from '../../shared/filters';
import { Empty, ErrorState, Loading, Signed, isNotFound } from '../../shared/ui';

@Component({
  selector: 'app-client-holdings',
  imports: [AccountFilter, AllocationBar, Chart, Signed, Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="space-y-4">
      <h1 class="text-[1.75rem] font-semibold">Holdings</h1>
      @if (accounts.value(); as a) {
        <app-account-filter [accounts]="a.accounts" [selected]="accountId()" />
      }
    </header>

    @if (holdings.isLoading()) {
      <div class="mt-8"><app-loading what="holdings" [rows]="6" /></div>
    } @else if (notYours()) {
      <div class="mt-8">
        <app-empty message="That account isn't one of yours. Choose one of your accounts above." />
      </div>
    } @else if (holdings.error()) {
      <div class="mt-8"><app-error (retry)="holdings.reload()" /></div>
    } @else if (holdings.value(); as h) {
      @if (h.holdings.length === 0) {
        <div class="mt-8"><app-empty message="No holdings in this account yet." /></div>
      } @else {
        <section class="mt-8 max-w-[70ch] space-y-4" aria-label="Summary">
          <p class="text-xl">
            {{ scopeLabel() }} {{ h.holdings.length }} positions worth
            <span class="num font-semibold">{{ money(h.portfolio_market_value) }}</span>, with
            <app-signed [value]="h.selection.unrealized_gain" /> unrealized gain or loss.
          </p>
          <app-allocation-bar [items]="h.asset_class_summary" />
        </section>

        <section
          class="mt-10 rounded-[var(--radius-panel)] border border-rule bg-surface p-5 sm:p-6"
        >
          <app-chart
            title="10 largest holdings"
            [summary]="topSummary()"
            [build]="buildTop10"
            [table]="topTable()"
            [height]="360"
          />
        </section>

        <section class="mt-10" aria-labelledby="all-holdings">
          <h2 id="all-holdings" class="mb-3 text-xl font-semibold">All positions</h2>
          <div class="overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface">
            <table class="ledger w-full min-w-[56rem] text-[0.9375rem]">
              <caption class="sr-only">
                All positions, largest first
              </caption>
              <thead class="text-left text-sm text-ink-muted">
                <tr>
                  <th scope="col" class="px-4 py-3 font-medium">Holding</th>
                  <th scope="col" class="px-4 py-3 font-medium">Sector</th>
                  <th scope="col" class="px-4 py-3 text-right font-medium">Quantity</th>
                  <th scope="col" class="px-4 py-3 text-right font-medium">Price</th>
                  <th scope="col" class="px-4 py-3 text-right font-medium">Market value</th>
                  <th scope="col" class="px-4 py-3 text-right font-medium">Cost basis</th>
                  <th scope="col" class="px-4 py-3 text-right font-medium">Unrealized</th>
                  <th scope="col" class="px-4 py-3 text-right font-medium">Share</th>
                </tr>
              </thead>
              <tbody>
                @for (row of h.holdings; track row.symbol) {
                  <tr class="border-t border-rule">
                    <th scope="row" class="px-4 py-3 text-left font-normal">
                      <span class="font-medium">{{ row.description }}</span>
                      <span class="ml-2 text-sm text-ink-muted">{{ row.symbol }}</span>
                    </th>
                    <td class="px-4 py-3 text-ink-muted">
                      {{ row.asset_class === 'cash' ? 'Cash' : row.sector }}
                    </td>
                    <td class="num px-4 py-3 text-right">{{ quantity(row.quantity) }}</td>
                    <td class="num px-4 py-3 text-right">{{ money(row.price) }}</td>
                    <td class="num px-4 py-3 text-right font-medium">
                      {{ money(row.market_value) }}
                    </td>
                    <td class="num px-4 py-3 text-right text-ink-muted">
                      {{ money(row.cost_basis) }}
                    </td>
                    <td class="px-4 py-3 text-right">
                      @if (row.asset_class === 'cash') {
                        <span class="text-ink-muted">—</span>
                      } @else {
                        <app-signed [value]="row.unrealized_gain" />
                      }
                    </td>
                    <td class="num px-4 py-3 text-right text-ink-muted">
                      {{ percent(row.pct_of_portfolio) }}
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </section>
      }
    }
  `,
})
export class ClientHoldings {
  private readonly api = inject(Api);

  /** ?account= from the URL (component input binding). */
  readonly account = input<string>();
  protected readonly accountId = computed(() => accountParam(this.account()));

  protected readonly money = money;
  protected readonly percent = percent;
  protected readonly quantity = quantity;

  protected readonly accounts = rxResource({ stream: () => this.api.clientAccounts() });
  protected readonly notYours = computed(() => isNotFound(this.holdings.error()));
  protected readonly holdings = rxResource({
    params: () => ({ id: this.accountId() }),
    stream: ({ params }) => this.api.clientHoldings(params.id),
  });

  protected readonly scopeLabel = computed(() => {
    const id = this.accountId();
    const acct = this.accounts.value()?.accounts.find((a) => a.account_id === id);
    return acct ? `${acct.account_name} holds` : 'Across all your accounts you hold';
  });

  private readonly top10 = computed<Holding[]>(() =>
    (this.holdings.value()?.holdings ?? []).filter((h) => h.asset_class !== 'cash').slice(0, 10),
  );

  protected readonly topSummary = computed(() => {
    const top = this.top10();
    if (!top.length) return 'Only cash is held here.';
    const share = top.reduce((s, h) => s + h.pct_of_portfolio, 0);
    return `${top[0].description} is the largest holding at ${money0(top[0].market_value)}. These ten make up ${percent(share)} of the value shown.`;
  });

  protected readonly topTable = computed<ChartTable>(() => ({
    columns: ['Holding', 'Symbol', 'Asset class', 'Market value', 'Share'],
    numeric: [3, 4],
    rows: this.top10().map((h) => [
      h.description,
      h.symbol,
      assetClassLabel[h.asset_class],
      money(h.market_value),
      percent(h.pct_of_portfolio),
    ]),
  }));

  protected readonly buildTop10 = (t: ChartTokens) => topHoldingsOption(this.top10(), t);
}
