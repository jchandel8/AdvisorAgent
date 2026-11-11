import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import type { EChartsCoreOption } from 'echarts/core';
import { NgxEchartsDirective } from 'ngx-echarts';
import { Theme } from '../core/theme';
import { Icon } from './ui';

/** Concrete colors for ECharts, read from the CSS tokens of the current theme. */
export interface ChartTokens {
  ink: string;
  muted: string;
  rule: string;
  grid: string;
  surface: string;
  pos: string;
  neg: string;
  font: string;
  swatch: (accountId: number) => string;
}

export interface ChartTable {
  columns: string[];
  rows: string[][];
  /** Column indexes that hold numbers (right-aligned). */
  numeric?: number[];
}

/**
 * A chart with a text summary and a "Show as table" alternative (dataviz + ui-ux-pro-max accessibility rules).
 * Pages pass a builder that turns theme tokens into ECharts options, so charts re-color on theme change.
 */
@Component({
  selector: 'app-chart',
  imports: [NgxEchartsDirective, Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <figure class="space-y-3">
      <figcaption class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span class="font-semibold">{{ title() }}</span>
        <button
          type="button"
          class="inline-flex min-h-11 items-center gap-1.5 text-sm text-ink-muted underline-offset-4 hover:text-ink hover:underline"
          [attr.aria-pressed]="showTable()"
          (click)="showTable.set(!showTable())"
        >
          <app-icon [name]="showTable() ? 'chart' : 'table'" [size]="16" />
          {{ showTable() ? 'Show as chart' : 'Show as table' }}
        </button>
      </figcaption>
      <p class="text-sm text-ink-muted">{{ summary() }}</p>
      @if (showTable()) {
        <div class="max-h-96 overflow-auto rounded-[var(--radius-control)] border border-rule">
          <table class="ledger w-full text-sm">
            <thead class="sticky top-0 bg-surface-sunk text-left text-ink-muted">
              <tr>
                @for (c of table().columns; track $index) {
                  <th scope="col" class="px-3 py-2 font-medium" [class.text-right]="isNumeric($index)">{{ c }}</th>
                }
              </tr>
            </thead>
            <tbody>
              @for (row of table().rows; track $index) {
                <tr class="border-t border-rule">
                  @for (cell of row; track $index) {
                    <td class="px-3 py-2" [class.num]="isNumeric($index)" [class.text-right]="isNumeric($index)">{{ cell }}</td>
                  }
                </tr>
              }
            </tbody>
          </table>
        </div>
      } @else {
        <div echarts [options]="options()" [initOpts]="initOpts" [style.height.px]="height()" role="img" [attr.aria-label]="summary()"></div>
      }
    </figure>
  `,
})
export class Chart {
  private readonly theme = inject(Theme);

  readonly title = input.required<string>();
  readonly summary = input.required<string>();
  readonly build = input.required<(t: ChartTokens) => EChartsCoreOption>();
  readonly table = input.required<ChartTable>();
  readonly height = input(320);

  protected readonly showTable = signal(false);
  protected readonly initOpts = { renderer: 'svg' as const };

  protected readonly options = computed(() => {
    this.theme.current(); // re-read the tokens whenever the theme changes
    const tok = (n: string) => this.theme.token(n);
    const tokens: ChartTokens = {
      ink: tok('--ink'),
      muted: tok('--ink-muted'),
      rule: tok('--rule-strong'),
      grid: tok('--chart-grid'),
      surface: tok('--surface'),
      pos: tok('--chart-pos'),
      neg: tok('--chart-neg'),
      font: getComputedStyle(document.documentElement).fontFamily,
      swatch: (id: number) => tok(`--swatch-${id % 8}`),
    };
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    return {
      animation: !reduceMotion,
      textStyle: { fontFamily: tokens.font, color: tokens.muted },
      aria: { enabled: true },
      ...this.build()(tokens),
    } as EChartsCoreOption;
  });

  protected isNumeric(i: number): boolean {
    return (this.table().numeric ?? []).includes(i);
  }
}
