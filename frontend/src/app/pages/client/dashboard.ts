import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { Api } from '../../core/api';
import { accountTypeLabel, dateLong, money, money0, moneyCompact, percent } from '../../core/format';
import { Holding } from '../../core/models';
import { Session } from '../../core/session';
import { Chart, ChartTable, ChartTokens } from '../../shared/chart';
import { Empty, ErrorState, Loading, Swatch } from '../../shared/ui';

@Component({
  selector: 'app-client-dashboard',
  imports: [Swatch, Chart, Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (accounts.isLoading()) {
      <app-loading what="your accounts" [rows]="4" />
    } @else if (accounts.error()) {
      <app-error (retry)="accounts.reload()" />
    } @else if (accounts.value(); as a) {
      <header class="max-w-[62ch] space-y-2">
        <h1 class="text-[1.75rem] font-semibold">
          {{ firstName() }}, your {{ a.account_count }} {{ a.account_count === 1 ? 'account is' : 'accounts are' }} worth
          <span class="num">{{ money(a.total_market_value) }}</span>.
        </h1>
        <p class="text-ink-muted">Values as of {{ asOf() }}.</p>
      </header>

      <section class="mt-10" aria-labelledby="accounts-title">
        <h2 id="accounts-title" class="mb-3 text-xl font-semibold">Accounts</h2>
        <div class="overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface">
          <table class="ledger w-full min-w-[28rem] text-[0.9375rem]">
            <caption class="sr-only">Your accounts and their market values</caption>
            <thead class="text-left text-sm text-ink-muted">
              <tr>
                <th scope="col" class="px-5 py-3 font-medium">Account</th>
                <th scope="col" class="px-5 py-3 font-medium">Type</th>
                <th scope="col" class="hidden px-5 py-3 font-medium md:table-cell">Owners</th>
                <th scope="col" class="px-5 py-3 text-right font-medium">Market value</th>
                <th scope="col" class="px-5 py-3 text-right font-medium">Share</th>
              </tr>
            </thead>
            <tbody>
              @for (acct of a.accounts; track acct.account_id) {
                <tr class="border-t border-rule">
                  <th scope="row" class="max-w-64 px-5 py-3 text-left font-medium">
                    <app-swatch [accountId]="acct.account_id" [label]="acct.account_name" />
                    <span class="mt-0.5 block pl-3.5 text-sm font-normal text-ink-muted md:hidden">{{ acct.owners }}</span>
                  </th>
                  <td class="px-5 py-3">{{ typeLabel[acct.account_type] }}</td>
                  <td class="hidden px-5 py-3 text-ink-muted md:table-cell">{{ acct.owners }}</td>
                  <td class="num px-5 py-3 text-right">{{ money(acct.market_value) }}</td>
                  <td class="num px-5 py-3 text-right text-ink-muted">
                    {{ percent((100 * acct.market_value) / (a.total_market_value || 1)) }}
                  </td>
                </tr>
              }
            </tbody>
            <tfoot>
              <tr class="border-t border-rule-strong font-semibold">
                <th scope="row" colspan="2" class="px-5 py-3 text-left">Total</th>
                <td class="hidden md:table-cell"></td>
                <td class="num px-5 py-3 text-right">{{ money(a.total_market_value) }}</td>
                <td class="num px-5 py-3 text-right">100.0%</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      <section class="mt-12" aria-label="Largest holdings">
        @if (holdings.isLoading()) {
          <app-loading what="holdings" [rows]="6" />
        } @else if (holdings.error()) {
          <app-error (retry)="holdings.reload()" />
        } @else if (top10().length === 0) {
          <app-empty message="No holdings yet. Positions appear here after the first trade settles." />
        } @else {
          <div class="rounded-[var(--radius-panel)] border border-rule bg-surface p-5 sm:p-6">
            <app-chart
              title="Your 10 largest holdings"
              [summary]="topSummary()"
              [build]="buildTop10"
              [table]="topTable()"
              [height]="380"
            />
          </div>
        }
      </section>
    }
  `,
})
export class ClientDashboard {
  private readonly api = inject(Api);
  private readonly session = inject(Session);

  protected readonly money = money;
  protected readonly percent = percent;
  protected readonly typeLabel = accountTypeLabel;

  protected readonly accounts = rxResource({ stream: () => this.api.clientAccounts() });
  protected readonly holdings = rxResource({ stream: () => this.api.clientHoldings(null) });

  protected readonly firstName = computed(() => this.session.user()?.name.split(' ')[0] ?? 'Hello');
  protected readonly asOf = computed(() => {
    const dates = (this.accounts.value()?.accounts ?? []).map((a) => a.as_of_date).filter((d): d is string => !!d);
    return dates.length ? dateLong(dates.sort().at(-1)) : 'today';
  });

  // Cash is the uninvested balance, not a holding, so it is left out of the top 10.
  protected readonly top10 = computed<Holding[]>(() =>
    (this.holdings.value()?.holdings ?? []).filter((h) => h.asset_class !== 'cash').slice(0, 10),
  );

  protected readonly topSummary = computed(() => {
    const top = this.top10();
    if (!top.length) return '';
    const share = top.reduce((s, h) => s + h.pct_of_portfolio, 0);
    return `${top[0].description} is your largest holding at ${money0(top[0].market_value)}. Together these ten make up ${percent(share)} of your portfolio.`;
  });

  protected readonly topTable = computed<ChartTable>(() => ({
    columns: ['Holding', 'Symbol', 'Market value', 'Share of portfolio'],
    numeric: [2, 3],
    rows: this.top10().map((h) => [h.description, h.symbol, money(h.market_value), percent(h.pct_of_portfolio)]),
  }));

  protected readonly buildTop10 = (t: ChartTokens) => {
    const top = this.top10();
    return {
      grid: { left: 8, right: 120, top: 8, bottom: 8, containLabel: true },
      tooltip: {
        trigger: 'item',
        backgroundColor: t.surface,
        borderColor: t.rule,
        textStyle: { color: t.ink },
        formatter: (p: { dataIndex: number }) => {
          const h = top[p.dataIndex];
          return `<strong>${h.description}</strong><br/>${money(h.market_value)} · ${percent(h.pct_of_portfolio)} of portfolio`;
        },
      },
      xAxis: {
        type: 'value',
        axisLabel: { color: t.muted, formatter: (v: number) => moneyCompact(v) },
        splitLine: { lineStyle: { color: t.grid } },
      },
      yAxis: {
        type: 'category',
        inverse: true,
        data: top.map((h) => h.symbol),
        axisTick: { show: false },
        axisLine: { lineStyle: { color: t.rule } },
        axisLabel: {
          color: t.ink,
          formatter: (_: string, i: number) => `{name|${shortName(top[i].description)}} {sym|${top[i].symbol}}`,
          rich: { name: { color: t.ink, fontWeight: 500 }, sym: { color: t.muted } },
        },
      },
      series: [
        {
          type: 'bar',
          data: top.map((h) => h.market_value),
          barMaxWidth: 18,
          itemStyle: { color: t.pos, borderRadius: [0, 4, 4, 0] },
          label: {
            show: true,
            position: 'right',
            color: t.ink,
            formatter: (p: { dataIndex: number }) =>
              `${money0(top[p.dataIndex].market_value)}  ${percent(top[p.dataIndex].pct_of_portfolio)}`,
          },
        },
      ],
    };
  };
}

/** "Microsoft Corp." -> "Microsoft"; keeps axis labels short. The full name is in the tooltip and table. */
function shortName(description: string): string {
  const cut = description.replace(/,? (& Co\.|Inc\.|Corp\.|Co\.|plc|Corporation|Company|Class [A-Z]).*$/, '');
  return cut.length > 22 ? cut.slice(0, 21) + '…' : cut;
}
