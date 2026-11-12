import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { Api } from '../../core/api';
import { dateMonth, dateShort, money, money0, moneyCompact, quantity } from '../../core/format';
import { TxnType } from '../../core/models';
import { Chart, ChartTable, ChartTokens } from '../../shared/chart';
import { AccountFilter, accountParam } from '../../shared/filters';
import { shortName } from '../../shared/holdings-chart';
import { Empty, ErrorState, Loading, Signed, Swatch, isNotFound } from '../../shared/ui';

const TYPES: { value: TxnType; label: string }[] = [
  { value: 'buy', label: 'Buys' },
  { value: 'sell', label: 'Sells' },
  { value: 'dividend', label: 'Dividends' },
  { value: 'deposit', label: 'Deposits' },
  { value: 'withdrawal', label: 'Withdrawals' },
];
const TYPE_LABEL: Record<TxnType, string> = {
  buy: 'Buy',
  sell: 'Sell',
  dividend: 'Dividend',
  deposit: 'Deposit',
  withdrawal: 'Withdrawal',
};
const PAGE_SIZE = 25;

@Component({
  selector: 'app-client-transactions',
  imports: [AccountFilter, Chart, Signed, Swatch, Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="space-y-4">
      <h1 class="text-[1.75rem] font-semibold">Transactions and gains</h1>
      @if (accounts.value(); as a) {
        <app-account-filter [accounts]="a.accounts" [selected]="accountId()" />
      }
    </header>

    <!-- Gains -->
    @if (gains.isLoading()) {
      <div class="mt-8"><app-loading what="gains" [rows]="4" /></div>
    } @else if (notYours()) {
      <div class="mt-8">
        <app-empty message="That account isn't one of yours. Choose one of your accounts above." />
      </div>
    } @else if (gains.error()) {
      <div class="mt-8"><app-error (retry)="gains.reload()" /></div>
    } @else if (gains.value(); as g) {
      <section class="mt-8 max-w-[70ch]" aria-label="Gains summary">
        <p class="text-xl">
          Sales over the last two years realized <app-signed [value]="g.realized_total" />.
          Positions you still hold are at <app-signed [value]="g.unrealized_total" /> against what
          you paid.
        </p>
        <p class="mt-2 text-sm text-ink-muted">
          Realized gain uses the average cost of the shares sold. Unrealized gain compares today's
          value with cost.
        </p>
      </section>
      <div class="mt-8 grid gap-6 xl:grid-cols-2">
        <section class="rounded-[var(--radius-panel)] border border-rule bg-surface p-5 sm:p-6">
          @if (g.realized_by_month.length) {
            <app-chart
              title="Realized gain or loss by month"
              [summary]="realizedSummary()"
              [build]="buildRealized"
              [table]="realizedTable()"
              [height]="300"
            />
          } @else {
            <app-empty message="No sales yet, so nothing has been realized." />
          }
        </section>
        <section class="rounded-[var(--radius-panel)] border border-rule bg-surface p-5 sm:p-6">
          @if (g.unrealized_by_symbol.length) {
            <app-chart
              title="Unrealized gain or loss, largest 10"
              [summary]="unrealizedSummary()"
              [build]="buildUnrealized"
              [table]="unrealizedTable()"
              [height]="300"
            />
          } @else {
            <app-empty message="No positions held, so there is no unrealized gain or loss." />
          }
        </section>
      </div>
    }

    <!-- Transactions -->
    @if (!notYours()) {
      <section class="mt-12" aria-labelledby="txn-title">
        <div class="mb-4 flex flex-wrap items-end justify-between gap-4">
          <h2 id="txn-title" class="text-xl font-semibold">Transactions</h2>
          <div role="group" aria-label="Transaction types" class="flex flex-wrap gap-2">
            @for (t of typeOptions; track t.value) {
              <button
                type="button"
                class="inline-flex min-h-11 items-center rounded-full border px-4 text-sm transition-colors duration-150"
                [class]="
                  types().includes(t.value)
                    ? 'border-ink bg-ink font-medium text-paper'
                    : 'border-rule-strong bg-surface hover:bg-surface-sunk'
                "
                [attr.aria-pressed]="types().includes(t.value)"
                (click)="toggleType(t.value)"
              >
                {{ t.label }}
              </button>
            }
          </div>
        </div>

        @if (txns.isLoading() && !txns.value()) {
          <app-loading what="transactions" [rows]="8" />
        } @else if (txns.error()) {
          <app-error (retry)="txns.reload()" />
        } @else if (txns.value(); as page) {
          @if (page.total_rows === 0) {
            <app-empty message="No transactions match these filters. Clear a filter to see more." />
          } @else {
            <div
              class="overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface"
              [attr.aria-busy]="txns.isLoading()"
            >
              <table class="ledger w-full min-w-[54rem] text-[0.9375rem]">
                <caption class="sr-only">
                  Transactions, newest first
                </caption>
                <thead class="text-left text-sm text-ink-muted">
                  <tr>
                    <th scope="col" class="px-4 py-3 font-medium">Date</th>
                    <th scope="col" class="px-4 py-3 font-medium">Account</th>
                    <th scope="col" class="px-4 py-3 font-medium">Type</th>
                    <th scope="col" class="px-4 py-3 font-medium">Security</th>
                    <th scope="col" class="px-4 py-3 text-right font-medium">Quantity</th>
                    <th scope="col" class="px-4 py-3 text-right font-medium">Price</th>
                    <th scope="col" class="px-4 py-3 text-right font-medium">Amount</th>
                    <th scope="col" class="px-4 py-3 text-right font-medium">Realized</th>
                  </tr>
                </thead>
                <tbody>
                  @for (t of page.transactions; track t.id) {
                    <tr class="border-t border-rule">
                      <td class="num px-4 py-3 whitespace-nowrap">{{ dateShort(t.trade_date) }}</td>
                      <td class="max-w-56 px-4 py-3">
                        <app-swatch [accountId]="t.account_id" [label]="t.account_name" />
                      </td>
                      <td class="px-4 py-3">{{ typeLabel[t.type] }}</td>
                      <td class="px-4 py-3">
                        @if (t.symbol) {
                          {{ t.description }}
                          <span class="text-sm text-ink-muted">{{ t.symbol }}</span>
                        } @else {
                          <span class="text-ink-muted">Cash</span>
                        }
                      </td>
                      <td class="num px-4 py-3 text-right">
                        {{ t.quantity == null ? '' : quantity(t.quantity) }}
                      </td>
                      <td class="num px-4 py-3 text-right">
                        {{ t.price == null ? '' : money(t.price) }}
                      </td>
                      <td class="num px-4 py-3 text-right font-medium">{{ money(t.amount) }}</td>
                      <td class="px-4 py-3 text-right">
                        @if (t.realized_gain != null) {
                          <app-signed [value]="t.realized_gain" />
                        }
                      </td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
            <nav class="mt-4 flex flex-wrap items-center justify-between gap-3" aria-label="Pages">
              <p class="num text-sm text-ink-muted">
                Showing {{ (page.page - 1) * page.page_size + 1 }}–{{
                  (page.page - 1) * page.page_size + page.transactions.length
                }}
                of {{ page.total_rows }}
              </p>
              <div class="flex gap-2">
                <button
                  type="button"
                  class="min-h-11 rounded-[var(--radius-control)] border border-rule-strong px-4 text-sm hover:bg-surface-sunk disabled:cursor-not-allowed disabled:opacity-50"
                  [disabled]="page.page <= 1"
                  (click)="goTo(page.page - 1)"
                >
                  Previous
                </button>
                <button
                  type="button"
                  class="min-h-11 rounded-[var(--radius-control)] border border-rule-strong px-4 text-sm hover:bg-surface-sunk disabled:cursor-not-allowed disabled:opacity-50"
                  [disabled]="page.page * page.page_size >= page.total_rows"
                  (click)="goTo(page.page + 1)"
                >
                  Next
                </button>
              </div>
            </nav>
          }
        }
      </section>
    }
  `,
})
export class ClientTransactions {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  readonly account = input<string>();
  readonly page = input<string>();
  protected readonly accountId = computed(() => accountParam(this.account()));
  private readonly pageNo = computed(() => accountParam(this.page()) ?? 1);
  protected readonly types = signal<TxnType[]>([]);

  protected readonly typeOptions = TYPES;
  protected readonly typeLabel = TYPE_LABEL;
  protected readonly money = money;
  protected readonly quantity = quantity;
  protected readonly dateShort = dateShort;

  protected readonly accounts = rxResource({ stream: () => this.api.clientAccounts() });
  protected readonly notYours = computed(() => isNotFound(this.gains.error()));
  protected readonly gains = rxResource({
    params: () => ({ id: this.accountId() }),
    stream: ({ params }) => this.api.clientGains(params.id),
  });
  protected readonly txns = rxResource({
    params: () => ({
      accountId: this.accountId(),
      types: this.types(),
      page: this.pageNo(),
      pageSize: PAGE_SIZE,
    }),
    stream: ({ params }) => this.api.clientTransactions(params),
  });

  protected toggleType(t: TxnType): void {
    this.types.update((cur) => (cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t]));
    this.goTo(1);
  }

  protected goTo(page: number): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { page: page > 1 ? page : null },
      queryParamsHandling: 'merge',
    });
  }

  // ---- Realized by month (signed bars, validated blue/red pair, never color alone) --------------------
  private readonly realized = computed(() => this.gains.value()?.realized_by_month ?? []);

  protected readonly realizedSummary = computed(() => {
    const rows = this.realized();
    if (!rows.length) return '';
    const best = rows.reduce((a, b) => (b.realized_gain > a.realized_gain ? b : a));
    const worst = rows.reduce((a, b) => (b.realized_gain < a.realized_gain ? b : a));
    return `Sales happened in ${rows.length} months. Best month: ${dateMonth(best.month)} (${signedMoney(best.realized_gain)}). Weakest: ${dateMonth(worst.month)} (${signedMoney(worst.realized_gain)}).`;
  });

  protected readonly realizedTable = computed<ChartTable>(() => ({
    columns: ['Month', 'Sales', 'Realized gain or loss'],
    numeric: [1, 2],
    rows: this.realized().map((r) => [
      dateMonth(r.month),
      String(r.sells),
      signedMoney(r.realized_gain),
    ]),
  }));

  protected readonly buildRealized = (t: ChartTokens) => {
    const rows = this.realized();
    return {
      grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: t.surface,
        borderColor: t.rule,
        textStyle: { color: t.ink },
        formatter: (ps: { dataIndex: number }[]) => {
          const r = rows[ps[0].dataIndex];
          return `<strong>${dateMonth(r.month)}</strong><br/>${signedMoney(r.realized_gain)} from ${r.sells} ${r.sells === 1 ? 'sale' : 'sales'}`;
        },
      },
      xAxis: {
        type: 'category',
        data: rows.map((r) => dateMonth(r.month)),
        axisLabel: { color: t.muted },
        axisLine: { lineStyle: { color: t.rule } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: t.muted, formatter: (v: number) => moneyCompact(v) },
        splitLine: { lineStyle: { color: t.grid } },
      },
      series: [
        {
          type: 'bar',
          barMaxWidth: 22,
          data: rows.map((r) => ({
            value: r.realized_gain,
            itemStyle: {
              color: r.realized_gain >= 0 ? t.pos : t.neg,
              borderRadius: r.realized_gain >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4],
            },
          })),
        },
      ],
    };
  };

  // ---- Unrealized by holding (diverging horizontal bars) ------------------------------------------------
  private readonly unrealized = computed(() =>
    (this.gains.value()?.unrealized_by_symbol ?? []).slice(0, 10),
  );

  protected readonly unrealizedSummary = computed(() => {
    const rows = this.unrealized();
    if (!rows.length) return '';
    const up = rows.filter((r) => r.unrealized_gain > 0).length;
    return `Of the 10 positions with the biggest gains or losses, ${up} are up and ${rows.length - up} are down. The largest is ${rows[0].description} at ${signedMoney(rows[0].unrealized_gain)}.`;
  });

  protected readonly unrealizedTable = computed<ChartTable>(() => ({
    columns: ['Holding', 'Market value', 'Cost basis', 'Unrealized gain or loss'],
    numeric: [1, 2, 3],
    rows: this.unrealized().map((r) => [
      `${r.description} (${r.symbol})`,
      money(r.market_value),
      money(r.cost_basis),
      signedMoney(r.unrealized_gain),
    ]),
  }));

  protected readonly buildUnrealized = (t: ChartTokens) => {
    const rows = this.unrealized();
    return {
      grid: { left: 8, right: 80, top: 8, bottom: 8, containLabel: true },
      tooltip: {
        trigger: 'item',
        backgroundColor: t.surface,
        borderColor: t.rule,
        textStyle: { color: t.ink },
        formatter: (p: { dataIndex: number }) => {
          const r = rows[p.dataIndex];
          return `<strong>${r.description}</strong><br/>${signedMoney(r.unrealized_gain)} (value ${money0(r.market_value)}, cost ${money0(r.cost_basis)})`;
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
        data: rows.map((r) => r.symbol),
        axisTick: { show: false },
        axisLine: { lineStyle: { color: t.rule } },
        axisLabel: {
          formatter: (_: string, i: number) => `{n|${shortName(rows[i].description)}}`,
          rich: { n: { color: t.ink } },
        },
      },
      series: [
        {
          type: 'bar',
          barMaxWidth: 16,
          data: rows.map((r) => ({
            value: r.unrealized_gain,
            itemStyle: {
              color: r.unrealized_gain >= 0 ? t.pos : t.neg,
              borderRadius: r.unrealized_gain >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4],
            },
          })),
          label: {
            show: true,
            position: 'right',
            color: t.ink,
            formatter: (p: { value: number }) => signedMoney(p.value, true),
          },
        },
      ],
    };
  };
}

/** "+$1,234.56" / "−$1,234.56": sign and amount together, so meaning never depends on color. */
function signedMoney(v: number, whole = false): string {
  const sign = v > 0 ? '+' : v < 0 ? '−' : '';
  return sign + (whole ? money0(Math.abs(v)) : money(Math.abs(v)));
}
