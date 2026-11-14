import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { money, percent, swatchVar } from '../core/format';

// ---- Icons ------------------------------------------------------------------------------------------
// Shapes from Lucide (ISC license), rendered as Angular SVG elements (no innerHTML).
type Shape =
  | { t: 'path'; d: string }
  | { t: 'circle'; cx: number; cy: number; r: number }
  | { t: 'rect'; x: number; y: number; w: number; h: number; rx: number }
  | { t: 'ellipse'; cx: number; cy: number; rx: number; ry: number };

const p = (d: string): Shape => ({ t: 'path', d });

const ICONS = {
  home: [
    p('M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8'),
    p(
      'M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
    ),
  ],
  layers: [
    p(
      'M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z',
    ),
    p('M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12'),
    p('M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17'),
  ],
  transfer: [p('M8 3 4 7l4 4'), p('M4 7h16'), p('m16 21 4-4-4-4'), p('M20 17H4')],
  trend: [p('M16 7h6v6'), p('m22 7-8.5 8.5-5-5L2 17')],
  user: [p('M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2'), { t: 'circle', cx: 12, cy: 7, r: 4 }],
  file: [
    p('M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z'),
    p('M14 2v4a2 2 0 0 0 2 2h4'),
    p('M10 13h4'),
    p('M10 17h4'),
  ],
  download: [p('M12 15V3'), p('M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'), p('m7 10 5 5 5-5')],
  eye: [
    p(
      'M2.06 12.35a1 1 0 0 1 0-.7 10.75 10.75 0 0 1 19.88 0 1 1 0 0 1 0 .7 10.75 10.75 0 0 1-19.88 0',
    ),
    { t: 'circle', cx: 12, cy: 12, r: 3 },
  ],
  back: [p('m12 19-7-7 7-7'), p('M19 12H5')],
  users: [
    p('M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2'),
    { t: 'circle', cx: 9, cy: 7, r: 4 },
    p('M22 21v-2a4 4 0 0 0-3-3.87'),
    p('M16 3.13a4 4 0 0 1 0 7.75'),
  ],
  briefcase: [
    p('M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16'),
    { t: 'rect', x: 2, y: 6, w: 20, h: 14, rx: 2 },
  ],
  chat: [p('M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z')],
  sun: [
    { t: 'circle', cx: 12, cy: 12, r: 4 },
    p('M12 2v2'),
    p('M12 20v2'),
    p('m4.93 4.93 1.41 1.41'),
    p('m17.66 17.66 1.41 1.41'),
    p('M2 12h2'),
    p('M20 12h2'),
    p('m6.34 17.66-1.41 1.41'),
    p('m19.07 4.93-1.41 1.41'),
  ],
  moon: [p('M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z')],
  switch: [p('M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4'), p('m16 17 5-5-5-5'), p('M21 12H9')],
  send: [p('m22 2-7 20-4-9-9-4Z'), p('M22 2 11 13')],
  table: [
    p('M12 3v18'),
    { t: 'rect', x: 3, y: 3, w: 18, h: 18, rx: 2 },
    p('M3 9h18'),
    p('M3 15h18'),
  ],
  chart: [p('M3 3v16a2 2 0 0 0 2 2h16'), p('M18 17V9'), p('M13 17V5'), p('M8 17v-3')],
  database: [
    { t: 'ellipse', cx: 12, cy: 5, rx: 9, ry: 3 },
    p('M3 5V19A9 3 0 0 0 21 19V5'),
    p('M3 12A9 3 0 0 0 21 12'),
  ],
  shield: [
    p(
      'M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z',
    ),
    p('m9 12 2 2 4-4'),
  ],
  alert: [{ t: 'circle', cx: 12, cy: 12, r: 10 }, p('M12 8v4'), p('M12 16h.01')],
  activity: [
    p(
      'M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2',
    ),
  ],
  refresh: [
    p('M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8'),
    p('M21 3v5h-5'),
    p('M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16'),
    p('M8 16H3v5'),
  ],
} satisfies Record<string, Shape[]>;

export type IconName = keyof typeof ICONS;

@Component({
  selector: 'app-icon',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg
      [attr.width]="size()"
      [attr.height]="size()"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.75"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      @for (s of shapes(); track $index) {
        @switch (s.t) {
          @case ('path') {
            <svg:path [attr.d]="$any(s).d" />
          }
          @case ('circle') {
            <svg:circle [attr.cx]="$any(s).cx" [attr.cy]="$any(s).cy" [attr.r]="$any(s).r" />
          }
          @case ('rect') {
            <svg:rect
              [attr.x]="$any(s).x"
              [attr.y]="$any(s).y"
              [attr.width]="$any(s).w"
              [attr.height]="$any(s).h"
              [attr.rx]="$any(s).rx"
            />
          }
          @case ('ellipse') {
            <svg:ellipse
              [attr.cx]="$any(s).cx"
              [attr.cy]="$any(s).cy"
              [attr.rx]="$any(s).rx"
              [attr.ry]="$any(s).ry"
            />
          }
        }
      }
    </svg>
  `,
  host: { class: 'inline-flex shrink-0' },
})
export class Icon {
  readonly name = input.required<IconName>();
  readonly size = input(18);
  protected readonly shapes = computed<Shape[]>(() => ICONS[this.name()]);
}

// ---- Account swatch -------------------------------------------------------------------------------
/** The account's stable identity: a colored ledger tab plus its name. Never color alone. */
@Component({
  selector: 'app-swatch',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span
      class="inline-block h-4 w-1.5 shrink-0 rounded-[2px]"
      [style.background]="color()"
      aria-hidden="true"
    ></span>
    @if (label()) {
      <span class="truncate">{{ label() }}</span>
    }
  `,
  host: { class: 'inline-flex min-w-0 items-center gap-2' },
})
export class Swatch {
  readonly accountId = input.required<number>();
  readonly label = input<string>('');
  protected readonly color = computed(() => swatchVar(this.accountId()));
}

// ---- Signed values ----------------------------------------------------------------------------------
/** A gain or loss: sign, arrow and color together, so meaning never depends on color alone. */
@Component({
  selector: 'app-signed',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (value() == null) {
      <span class="text-ink-muted">—</span>
    } @else {
      <span
        class="num whitespace-nowrap"
        [class.text-gain]="value()! > 0"
        [class.text-loss]="value()! < 0"
        ><span aria-hidden="true">{{ arrow() }}&nbsp;</span
        ><span class="sr-only">{{
          value()! > 0 ? 'Up ' : value()! < 0 ? 'Down ' : 'Unchanged '
        }}</span
        >{{ text() }}</span
      >
    }
  `,
})
export class Signed {
  readonly value = input<number | null>(null);
  readonly kind = input<'money' | 'percent'>('money');
  protected readonly arrow = computed(() => {
    const v = this.value() ?? 0;
    return v > 0 ? '▲' : v < 0 ? '▼' : '';
  });
  protected readonly text = computed(() => {
    const v = this.value();
    if (v == null) return '';
    const sign = v > 0 ? '+' : v < 0 ? '−' : '';
    const abs = Math.abs(v);
    return sign + (this.kind() === 'percent' ? percent(abs, 2) : money(abs));
  });
}

// ---- Loading / error / empty states -------------------------------------------------------------------
@Component({
  selector: 'app-loading',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="space-y-3" role="status" aria-live="polite">
      <span class="sr-only">Loading {{ what() }}</span>
      @for (row of rowsArray(); track $index) {
        <div
          class="h-4 animate-pulse rounded bg-surface-sunk"
          [style.width.%]="90 - $index * 12"
        ></div>
      }
    </div>
  `,
})
export class Loading {
  readonly what = input('data');
  readonly rows = input(3);
  protected readonly rowsArray = computed(() => Array.from({ length: this.rows() }));
}

@Component({
  selector: 'app-error',
  imports: [Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="flex items-start gap-3 rounded-[var(--radius-control)] border border-rule bg-surface p-4"
      role="alert"
    >
      <app-icon name="alert" class="mt-0.5 text-loss" />
      <div class="space-y-2">
        <p>{{ message() }}</p>
        <button
          type="button"
          class="inline-flex min-h-11 items-center gap-2 rounded-[var(--radius-control)] border border-rule-strong px-3 text-sm font-medium hover:bg-surface-sunk"
          (click)="retry.emit()"
        >
          <app-icon name="refresh" [size]="16" /> Try again
        </button>
      </div>
    </div>
  `,
})
export class ErrorState {
  readonly message = input(
    'This section didn’t load. Check that the API is running, then try again.',
  );
  readonly retry = output<void>();
}

@Component({
  selector: 'app-empty',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<p
    class="rounded-[var(--radius-control)] border border-dashed border-rule-strong p-6 text-ink-muted"
  >
    {{ message() }}
  </p>`,
})
export class Empty {
  readonly message = input.required<string>();
}

/** True when a resource failed with HTTP 404 (Angular may wrap non-Error values in `cause`). */
export function isNotFound(err: unknown): boolean {
  const e =
    err && typeof err === 'object' && 'cause' in err ? (err as { cause: unknown }).cause : err;
  return !!e && typeof e === 'object' && 'status' in e && (e as { status: number }).status === 404;
}
