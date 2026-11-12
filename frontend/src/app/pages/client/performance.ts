import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { Api } from '../../core/api';
import { dateLong, dateMonth, dateShort, money, money0 } from '../../core/format';
import { PERIODS, Period, Returns } from '../../core/models';
import { Chart, ChartTable, ChartTokens } from '../../shared/chart';
import { AccountFilter, accountParam } from '../../shared/filters';
import { Empty, ErrorState, Loading, Signed, Swatch, isNotFound } from '../../shared/ui';

const PERIOD_LABEL: Record<Period, string> = {
  '1d': '1 day',
  '1m': '1 month',
  '3m': '3 months',
  '6m': '6 months',
  ytd: 'Year to date',
  '1y': '1 year',
  '2y': '2 years',
  '3y': '3 years',
  '5y': '5 years',
};

@Component({
  selector: 'app-client-performance',
  imports: [AccountFilter, Chart, Signed, Swatch, Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="space-y-4">
      <h1 class="text-[1.75rem] font-semibold">Performance</h1>
      @if (accounts.value(); as a) {
        <app-account-filter [accounts]="a.accounts" [selected]="accountId()" />
      }
    </header>

    @if (perf.isLoading()) {
      <div class="mt-8"><app-loading what="performance" [rows]="6" /></div>
    } @else if (notYours()) {
      <div class="mt-8">
        <app-empty message="That account isn't one of yours. Choose one of your accounts above." />
      </div>
    } @else if (perf.error()) {
      <div class="mt-8"><app-error (retry)="perf.reload()" /></div>
    } @else if (perf.value(); as p) {
      @if (!p.accounts.length) {
        <div class="mt-8">
          <app-empty message="No performance figures yet. They appear after the first month-end." />
        </div>
      } @else {
        <section class="mt-8 max-w-[70ch]" aria-label="Summary">
          <p class="text-xl">
            Over the last year {{ scopeLabel() }} returned
            <app-signed [value]="p.combined_market_value_weighted.return_1y_pct" kind="percent" />,
            and
            <app-signed [value]="p.combined_market_value_weighted.return_ytd_pct" kind="percent" />
            so far this year.
          </p>
          <p class="mt-2 text-sm text-ink-muted">
            Returns are time-weighted: deposits and withdrawals don't count as gains. Across several
            accounts, each account counts in proportion to its value.
          </p>
        </section>

        <section
          class="mt-8 rounded-[var(--radius-panel)] border border-rule bg-surface p-5 sm:p-6"
        >
          <app-chart
            title="Growth of $100"
            [summary]="growthSummary()"
            [build]="buildGrowth"
            [table]="growthTable()"
            [height]="320"
          />
        </section>

        <section class="mt-10" aria-labelledby="returns-title">
          <h2 id="returns-title" class="mb-3 text-xl font-semibold">Returns by period</h2>
          <div class="overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface">
            <table class="ledger w-full min-w-[52rem] text-[0.9375rem]">
              <caption class="sr-only">
                Returns by period, as of
                {{
                  asOf()
                }}
              </caption>
              <thead class="text-sm text-ink-muted">
                <tr>
                  <th scope="col" class="px-4 py-3 text-left font-medium">Account</th>
                  @for (per of periods; track per) {
                    <th
                      scope="col"
                      class="px-3 py-3 text-right font-medium whitespace-nowrap"
                      [attr.title]="periodLabel[per]"
                    >
                      <abbr class="no-underline" [attr.title]="periodLabel[per]">{{
                        shortLabel(per)
                      }}</abbr>
                    </th>
                  }
                </tr>
              </thead>
              <tbody>
                @if (p.accounts.length > 1) {
                  <tr class="border-t border-rule bg-surface-sunk font-medium">
                    <th scope="row" class="px-4 py-3 text-left">All shown accounts</th>
                    @for (per of periods; track per) {
                      <td class="px-3 py-3 text-right">
                        <app-signed
                          [value]="ret(p.combined_market_value_weighted, per)"
                          kind="percent"
                        />
                        @if (p.partial_periods.includes(per)) {
                          <span
                            class="text-ink-muted"
                            title="Some accounts are too new for this period"
                            >*</span
                          >
                        }
                      </td>
                    }
                  </tr>
                }
                @for (a of p.accounts; track a.account_id) {
                  <tr class="border-t border-rule">
                    <th scope="row" class="max-w-64 px-4 py-3 text-left font-normal">
                      <app-swatch [accountId]="a.account_id" [label]="a.account_name" />
                    </th>
                    @for (per of periods; track per) {
                      <td class="px-3 py-3 text-right">
                        <app-signed [value]="ret(a, per)" kind="percent" />
                      </td>
                    }
                  </tr>
                }
              </tbody>
            </table>
          </div>
          <p class="mt-3 text-sm text-ink-muted">
            As of {{ asOf() }}. A dash means the account is newer than the period.
            @if (p.partial_periods.length && p.accounts.length > 1) {
              * The combined figure covers only the accounts old enough for that period.
            }
          </p>
        </section>
      }
    }
  `,
})
export class ClientPerformance {
  private readonly api = inject(Api);

  readonly account = input<string>();
  protected readonly accountId = computed(() => accountParam(this.account()));
  protected readonly periods = PERIODS;

  protected readonly accounts = rxResource({ stream: () => this.api.clientAccounts() });
  protected readonly notYours = computed(() => isNotFound(this.perf.error()));
  protected readonly perf = rxResource({
    params: () => ({ id: this.accountId() }),
    stream: ({ params }) => this.api.clientPerformance(params.id),
  });

  protected readonly scopeLabel = computed(() => {
    const id = this.accountId();
    const acct = this.accounts.value()?.accounts.find((a) => a.account_id === id);
    return acct ? acct.account_name : 'your portfolio';
  });
  protected readonly asOf = computed(() => dateLong(this.perf.value()?.accounts[0]?.as_of_date));

  protected ret(r: Returns, p: Period): number | null {
    return r[`return_${p}_pct`];
  }
  protected shortLabel(p: Period): string {
    return p === 'ytd' ? 'YTD' : p.toUpperCase();
  }

  private readonly growth = computed(() => this.perf.value()?.growth ?? []);

  protected readonly growthSummary = computed(() => {
    const g = this.growth();
    if (g.length < 2) return 'Not enough history to draw growth yet.';
    const last = g[g.length - 1];
    return `$100 invested on ${dateLong(g[0].as_of_date)} would be worth ${money(last.growth_index)} on ${dateLong(last.as_of_date)}. Market value is now ${money0(last.market_value)}.`;
  });

  protected readonly growthTable = computed<ChartTable>(() => ({
    columns: ['Date', 'Growth of $100', 'Market value'],
    numeric: [1, 2],
    rows: this.growth().map((g) => [
      dateShort(g.as_of_date),
      money(g.growth_index),
      money(g.market_value),
    ]),
  }));

  protected readonly buildGrowth = (t: ChartTokens) => {
    const g = this.growth();
    return {
      grid: { left: 8, right: 24, top: 16, bottom: 8, containLabel: true },
      tooltip: {
        trigger: 'axis',
        backgroundColor: t.surface,
        borderColor: t.rule,
        textStyle: { color: t.ink },
        formatter: (ps: { dataIndex: number }[]) => {
          const r = g[ps[0].dataIndex];
          return `<strong>${dateLong(r.as_of_date)}</strong><br/>Growth of $100: ${money(r.growth_index)}<br/>Market value: ${money0(r.market_value)}`;
        },
      },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: g.map((r) => dateMonth(r.as_of_date)),
        axisLabel: { color: t.muted },
        axisLine: { lineStyle: { color: t.rule } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: { color: t.muted, formatter: (v: number) => `$${v}` },
        splitLine: { lineStyle: { color: t.grid } },
      },
      series: [
        {
          type: 'line',
          data: g.map((r) => r.growth_index),
          showSymbol: false,
          symbolSize: 8,
          lineStyle: { width: 2, color: t.pos },
          itemStyle: { color: t.pos },
          areaStyle: { color: t.pos, opacity: 0.12 },
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: { color: t.rule, type: 'dashed' },
            label: { color: t.muted, formatter: 'Start: $100', position: 'insideStartTop' },
            data: [{ yAxis: 100 }],
          },
        },
      ],
    };
  };

  protected readonly periodLabel = PERIOD_LABEL;
}
