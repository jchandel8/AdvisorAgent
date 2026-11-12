import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, inject, input, output, signal } from '@angular/core';
import { Api } from '../core/api';
import { Person } from '../core/models';

/** The API's own message for a failed request (FastAPI `detail`), or a plain fallback. */
export function apiError(err: unknown, fallback = 'That didn’t work. Try again.'): string {
  if (err instanceof HttpErrorResponse) {
    const detail = (err.error as { detail?: unknown } | null)?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0] as { msg?: string; loc?: unknown[] };
      const field = Array.isArray(first.loc) ? String(first.loc.at(-1)) : '';
      return `${field ? field.replace('_', ' ') + ': ' : ''}${(first.msg ?? '').replace(/^Value error, /, '')}`;
    }
  }
  return fallback;
}

export const FIELD =
  'min-h-11 w-full rounded-[var(--radius-control)] border border-rule-strong bg-surface px-3 text-base';

/** Search box that finds advisors or clients by name, username or ID and emits the one picked. */
@Component({
  selector: 'app-person-picker',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <label class="flex flex-col gap-1 text-sm">
      <span class="text-ink-muted">{{ label() }}</span>
      <input
        type="search"
        [class]="field"
        [attr.aria-label]="label()"
        placeholder="Name, username or ID"
        [value]="query()"
        (input)="search($any($event.target).value)"
        autocomplete="off"
      />
    </label>
    @if (results().length) {
      <ul
        class="mt-1 max-h-56 overflow-auto rounded-[var(--radius-control)] border border-rule bg-surface"
        role="listbox"
        [attr.aria-label]="label() + ' results'"
      >
        @for (p of results(); track p.person_type + p.person_id) {
          <li role="option" [attr.aria-selected]="false">
            <button
              type="button"
              class="flex w-full items-baseline justify-between gap-3 px-3 py-2 text-left hover:bg-surface-sunk"
              (click)="choose(p)"
            >
              <span
                >{{ p.name }} <span class="text-sm text-ink-muted">{{ p.username }}</span></span
              >
              <span class="num text-xs text-ink-muted">{{ p.person_type }} #{{ p.person_id }}</span>
            </button>
          </li>
        }
      </ul>
    } @else if (query().trim().length >= 2 && !loading()) {
      <p class="mt-1 text-sm text-ink-muted">No matches.</p>
    }
  `,
})
export class PersonPicker {
  private readonly api = inject(Api);
  readonly label = input('Find a person');
  readonly kind = input<'advisor' | 'client' | null>(null);
  readonly picked = output<Person>();

  protected readonly field = FIELD;
  protected readonly query = signal('');
  protected readonly results = signal<Person[]>([]);
  protected readonly loading = signal(false);
  private timer: ReturnType<typeof setTimeout> | undefined;

  protected search(q: string): void {
    this.query.set(q);
    clearTimeout(this.timer);
    if (q.trim().length < 2 && !/^\d+$/.test(q.trim())) {
      this.results.set([]);
      return;
    }
    this.loading.set(true);
    this.timer = setTimeout(() => {
      this.api.findPeople(q.trim(), this.kind()).subscribe({
        next: (r) => {
          this.results.set(r.people);
          this.loading.set(false);
        },
        error: () => {
          this.results.set([]);
          this.loading.set(false);
        },
      });
    }, 250);
  }

  protected choose(p: Person): void {
    this.picked.emit(p);
    this.query.set('');
    this.results.set([]);
  }
}
