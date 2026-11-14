import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { Api } from '../../core/api';
import { Empty, ErrorState, Loading } from '../../shared/ui';

const when = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short' });
export const fmt = (iso: string) => when.format(new Date(iso));

export const ACTION_LABEL: Record<string, string> = {
  grant: 'Granted',
  revoke: 'Revoked',
  create_user: 'Created user',
  create_account: 'Created account',
  view_document: 'Viewed document',
  download_document: 'Downloaded document',
};

const OUTCOME_LABEL: Record<string, string> = {
  blocked_scope: 'Off topic',
  blocked_manipulation: 'Manipulation',
  blocked_unverified: 'Unsupported figures',
  guard_error: 'Check failed (blocked)',
  rate_limited: 'Over the limit',
  answered: 'Answered',
  cached: 'Answered (saved)',
  error: 'Error',
};

@Component({
  selector: 'app-admin-audit',
  imports: [Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="max-w-[66ch] space-y-1">
      <h1 class="text-[1.75rem] font-semibold">Audit log</h1>
      <p class="text-ink-muted">
        Every change made in this portal, and every document an admin opened: who, what and when.
        Entries can't be edited.
      </p>
    </header>
    <div class="mt-8">
      @if (log.isLoading() && !log.value()) {
        <app-loading what="the audit log" [rows]="6" />
      } @else if (log.error()) {
        <app-error (retry)="log.reload()" />
      } @else if (log.value(); as l) {
        @if (!l.events.length) {
          <app-empty
            message="No entries yet. Granting or revoking access, creating a user or account, or opening a document adds one here."
          />
        } @else {
          <div class="overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface">
            <table class="ledger w-full min-w-[48rem] text-[0.9375rem]">
              <caption class="sr-only">
                Changes, newest first
              </caption>
              <thead class="text-left text-sm text-ink-muted">
                <tr>
                  <th scope="col" class="px-4 py-3 font-medium">When</th>
                  <th scope="col" class="px-4 py-3 font-medium">Who</th>
                  <th scope="col" class="px-4 py-3 font-medium">Action</th>
                  <th scope="col" class="px-4 py-3 font-medium">What changed</th>
                </tr>
              </thead>
              <tbody>
                @for (e of l.events; track e.id) {
                  <tr class="border-t border-rule">
                    <td class="num px-4 py-3 whitespace-nowrap">{{ fmt(e.created_at) }}</td>
                    <td class="px-4 py-3">{{ e.admin_name }}</td>
                    <td class="px-4 py-3">{{ actionLabel[e.action] ?? e.action }}</td>
                    <td class="px-4 py-3">{{ e.summary }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
          <nav class="mt-4 flex items-center justify-between gap-3" aria-label="Pages">
            <p class="num text-sm text-ink-muted">
              Page {{ l.page }} of {{ pages(l.total_rows, l.page_size) }} ({{
                l.total_rows
              }}
              entries)
            </p>
            <div class="flex gap-2">
              <button
                type="button"
                class="min-h-11 rounded-[var(--radius-control)] border border-rule-strong px-4 text-sm disabled:opacity-50"
                [disabled]="page() <= 1"
                (click)="page.set(page() - 1)"
              >
                Previous
              </button>
              <button
                type="button"
                class="min-h-11 rounded-[var(--radius-control)] border border-rule-strong px-4 text-sm disabled:opacity-50"
                [disabled]="page() >= pages(l.total_rows, l.page_size)"
                (click)="page.set(page() + 1)"
              >
                Next
              </button>
            </div>
          </nav>
        }
      }
    </div>
  `,
})
export class AdminAudit {
  private readonly api = inject(Api);
  protected readonly page = signal(1);
  protected readonly log = rxResource({
    params: () => ({ page: this.page() }),
    stream: ({ params }) => this.api.auditLog(params.page),
  });
  protected readonly fmt = fmt;
  protected readonly actionLabel = ACTION_LABEL;
  protected pages(total: number, size: number): number {
    return Math.max(1, Math.ceil(total / size));
  }
}

@Component({
  selector: 'app-admin-assistant-log',
  imports: [Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="flex flex-wrap items-end justify-between gap-4">
      <div class="max-w-[66ch] space-y-1">
        <h1 class="text-[1.75rem] font-semibold">Assistant log</h1>
        <p class="text-ink-muted">
          Questions advisors asked the assistant. By default only those the guardrails stopped.
        </p>
      </div>
      <label class="inline-flex min-h-11 items-center gap-2 text-sm">
        <input
          type="checkbox"
          [checked]="blockedOnly()"
          (change)="blockedOnly.set($any($event.target).checked); page.set(1)"
        />
        Only stopped questions
      </label>
    </header>
    <div class="mt-8">
      @if (log.isLoading() && !log.value()) {
        <app-loading what="the assistant log" [rows]="6" />
      } @else if (log.error()) {
        <app-error (retry)="log.reload()" />
      } @else if (log.value(); as l) {
        @if (!l.events.length) {
          <app-empty
            [message]="blockedOnly() ? 'No questions have been stopped.' : 'No questions yet.'"
          />
        } @else {
          <div class="overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface">
            <table class="ledger w-full min-w-[52rem] text-[0.9375rem]">
              <caption class="sr-only">
                Assistant questions, newest first
              </caption>
              <thead class="text-left text-sm text-ink-muted">
                <tr>
                  <th scope="col" class="px-4 py-3 font-medium">When</th>
                  <th scope="col" class="px-4 py-3 font-medium">Advisor</th>
                  <th scope="col" class="px-4 py-3 font-medium">Outcome</th>
                  <th scope="col" class="px-4 py-3 font-medium">Question</th>
                  <th scope="col" class="px-4 py-3 font-medium">Reason</th>
                </tr>
              </thead>
              <tbody>
                @for (e of l.events; track e.id) {
                  <tr class="border-t border-rule">
                    <td class="num px-4 py-3 whitespace-nowrap">{{ fmt(e.created_at) }}</td>
                    <td class="px-4 py-3 whitespace-nowrap">{{ e.advisor_name }}</td>
                    <td class="px-4 py-3 whitespace-nowrap">
                      {{ outcomeLabel[e.outcome] ?? e.outcome }}
                    </td>
                    <td class="max-w-md px-4 py-3">{{ e.question }}</td>
                    <td class="max-w-xs px-4 py-3 text-sm text-ink-muted">{{ e.reason || '—' }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
          <nav class="mt-4 flex items-center justify-between gap-3" aria-label="Pages">
            <p class="num text-sm text-ink-muted">{{ l.total_rows }} questions</p>
            <div class="flex gap-2">
              <button
                type="button"
                class="min-h-11 rounded-[var(--radius-control)] border border-rule-strong px-4 text-sm disabled:opacity-50"
                [disabled]="page() <= 1"
                (click)="page.set(page() - 1)"
              >
                Previous
              </button>
              <button
                type="button"
                class="min-h-11 rounded-[var(--radius-control)] border border-rule-strong px-4 text-sm disabled:opacity-50"
                [disabled]="page() * l.page_size >= l.total_rows"
                (click)="page.set(page() + 1)"
              >
                Next
              </button>
            </div>
          </nav>
        }
      }
    </div>
  `,
})
export class AdminAssistantLog {
  private readonly api = inject(Api);
  protected readonly page = signal(1);
  protected readonly blockedOnly = signal(true);
  protected readonly log = rxResource({
    params: () => ({ page: this.page(), blocked: this.blockedOnly() }),
    stream: ({ params }) => this.api.assistantLog(params.page, params.blocked),
  });
  protected readonly fmt = fmt;
  protected readonly outcomeLabel = OUTCOME_LABEL;
}
