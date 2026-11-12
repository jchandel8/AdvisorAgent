import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { assetClassLabel, money0, percent } from '../core/format';
import { Account } from '../core/models';
import { Swatch } from './ui';

/** Parses the ?account= query parameter into an account ID, or null for "all accounts". */
export function accountParam(value: string | undefined): number | null {
  const n = Number(value);
  return value && Number.isInteger(n) && n > 0 ? n : null;
}

/**
 * Account filter: "All accounts" plus one chip per account, each with its swatch. The choice lives in the
 * URL (?account=ID) so a filtered view can be linked to and the back button works.
 */
@Component({
  selector: 'app-account-filter',
  imports: [Swatch],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div role="group" aria-label="Show accounts" class="flex flex-wrap gap-2">
      <button
        type="button"
        class="inline-flex min-h-11 items-center rounded-full border px-4 text-sm transition-colors duration-150"
        [class]="selected() === null ? activeClass : idleClass"
        [attr.aria-pressed]="selected() === null"
        (click)="choose(null)"
      >
        All accounts
      </button>
      @for (a of accounts(); track a.account_id) {
        <button
          type="button"
          class="inline-flex min-h-11 max-w-72 items-center rounded-full border px-4 text-sm transition-colors duration-150"
          [class]="selected() === a.account_id ? activeClass : idleClass"
          [attr.aria-pressed]="selected() === a.account_id"
          (click)="choose(a.account_id)"
        >
          <app-swatch [accountId]="a.account_id" [label]="a.account_name" />
        </button>
      }
    </div>
  `,
})
export class AccountFilter {
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  readonly accounts = input.required<Account[]>();
  readonly selected = input.required<number | null>();

  protected readonly activeClass = 'border-ink bg-ink text-paper font-medium';
  protected readonly idleClass = 'border-rule-strong bg-surface text-ink hover:bg-surface-sunk';

  protected choose(accountId: number | null): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { account: accountId, page: null },
      queryParamsHandling: 'merge',
    });
  }
}

/** Stocks / bonds / cash as one labeled 100% bar (asset classes never borrow account swatch colors). */
@Component({
  selector: 'app-allocation-bar',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="space-y-3">
      <div class="flex h-3 gap-[2px] overflow-hidden rounded-full" aria-hidden="true">
        @for (s of segments(); track s.key) {
          <div
            class="h-full first:rounded-l-full last:rounded-r-full"
            [style.width.%]="s.pct"
            [style.background]="s.color"
          ></div>
        }
      </div>
      <ul class="flex flex-wrap gap-x-6 gap-y-1 text-sm">
        @for (s of segments(); track s.key) {
          <li class="flex items-center gap-2">
            <span
              class="inline-block h-2.5 w-2.5 rounded-full"
              [style.background]="s.color"
              aria-hidden="true"
            ></span>
            <span>{{ s.label }}</span>
            <span class="num text-ink-muted">{{ percent(s.pct) }} · {{ money0(s.value) }}</span>
          </li>
        }
      </ul>
    </div>
  `,
})
export class AllocationBar {
  readonly items =
    input.required<{ asset_class: string; market_value: number; pct_of_portfolio: number }[]>();
  protected readonly percent = percent;
  protected readonly money0 = money0;
  // One hue, three steps (sequential), so it never reads as an account identity.
  private readonly colors: Record<string, string> = {
    equity: 'var(--ink)',
    fixed_income: 'var(--ink-muted)',
    cash: 'var(--rule-strong)',
  };
  protected readonly segments = computed(() =>
    ['equity', 'fixed_income', 'cash']
      .map((key) => {
        const row = this.items().find((i) => i.asset_class === key);
        return {
          key,
          label: assetClassLabel[key],
          pct: row?.pct_of_portfolio ?? 0,
          value: row?.market_value ?? 0,
          color: this.colors[key],
        };
      })
      .filter((s) => s.pct > 0),
  );
}

/** Read-only profile fields. */
@Component({
  selector: 'app-fields',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <dl
      class="divide-y divide-rule overflow-hidden rounded-[var(--radius-panel)] border border-rule bg-surface"
    >
      @for (f of fields(); track f.label) {
        <div class="grid gap-1 px-5 py-4 sm:grid-cols-[12rem_1fr] sm:gap-4">
          <dt class="text-ink-muted">{{ f.label }}</dt>
          <dd class="break-words">{{ f.value || '—' }}</dd>
        </div>
      }
    </dl>
  `,
})
export class Fields {
  readonly fields = input.required<{ label: string; value: string | null | undefined }[]>();
}
