import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { of } from 'rxjs';
import { Api } from '../../core/api';
import { renderMarkdown } from '../../core/markdown';
import { AgentRunDetail, AgentStep } from '../../core/models';
import { accountParam } from '../../shared/filters';
import { httpStatus } from '../../shared/person-picker';
import { Empty, ErrorState, Icon, IconName, Loading } from '../../shared/ui';
import { OUTCOME_LABEL, fmt } from './logs';

const KIND: Record<AgentStep['kind'], { label: string; icon: IconName }> = {
  scope_check: { label: 'Scope check', icon: 'shield' },
  model: { label: 'Claude', icon: 'chat' },
  tool: { label: 'Tool', icon: 'database' },
  cache: { label: 'Cache', icon: 'refresh' },
  note: { label: 'Check', icon: 'alert' },
};

const int = new Intl.NumberFormat('en-US');
const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

function tokens(n: number | null | undefined): string {
  return n == null ? '—' : int.format(n);
}

function seconds(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function cost(v: string | number | null): string {
  return v == null ? 'Not priced' : usd.format(Number(v));
}

function args(input: unknown): string {
  if (!input || typeof input !== 'object') return '';
  return Object.entries(input as Record<string, unknown>)
    .map(([k, v]) => `${k}=${typeof v === 'string' ? JSON.stringify(v) : JSON.stringify(v)}`)
    .join(', ');
}

/** One readable line per step; the exact request and response are one click away. */
export function summary(step: AgentStep): string {
  const req = (step.request ?? {}) as Record<string, any>;
  const res = (step.response ?? {}) as Record<string, any>;
  switch (step.kind) {
    case 'scope_check':
      return `${res['category'] ?? 'unknown'}: ${res['reason'] ?? ''}`;
    case 'model': {
      const blocks: any[] = Array.isArray(res['content']) ? res['content'] : [];
      const calls = blocks.filter((b) => b?.type === 'tool_use');
      if (calls.length) {
        return `Asked for ${calls.length === 1 ? 'a tool' : `${calls.length} tools`}: ${calls
          .map((c) => `${c.name}(${args(c.input)})`)
          .join('; ')}`;
      }
      const textOut = blocks
        .filter((b) => b?.type === 'text')
        .map((b) => b.text)
        .join(' ')
        .trim();
      return textOut
        ? `Wrote: ${textOut.slice(0, 220)}${textOut.length > 220 ? '…' : ''}`
        : '(no text)';
    }
    case 'tool':
      return `${step.name}(${args(req['input'])}) ${res['error'] ? `→ error: ${res['error']}` : '→ ok'}`;
    case 'cache':
      return 'Answered from the answer cache (no model call).';
    default:
      return String(res['reason'] ?? step.name);
  }
}

function stepMeta(s: AgentStep): string {
  const parts = [seconds(s.duration_ms)];
  if (s.input_tokens != null)
    parts.push(`${tokens(s.input_tokens)} in`, `${tokens(s.output_tokens)} out`);
  if (s.cache_read_tokens) parts.push(`${tokens(s.cache_read_tokens)} from cache`);
  return parts.join(', ');
}

function pretty(value: unknown): string {
  return value == null ? '—' : JSON.stringify(value, null, 2);
}

@Component({
  selector: 'app-admin-agent-runs',
  imports: [RouterLink, Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="flex flex-wrap items-end justify-between gap-4">
      <div class="max-w-[66ch] space-y-1">
        <h1 class="text-[1.75rem] font-semibold">Agent runs</h1>
        <p class="text-ink-muted">
          Everything the AI did for each question: the scope check, every Claude call, and every
          tool call with its exact inputs and results. Opening a run shows client data and is
          recorded in the audit log. Runs are kept for 30 days.
        </p>
      </div>
      <div class="flex flex-wrap items-end gap-3">
        <label class="grid gap-1 text-sm">
          <span class="text-ink-muted">Outcome</span>
          <select
            class="min-h-11 rounded-[var(--radius-control)] border border-rule-strong bg-surface px-3"
            [value]="outcome() ?? ''"
            (change)="outcome.set($any($event.target).value || null); page.set(1)"
          >
            <option value="">All outcomes</option>
            @for (o of outcomes; track o[0]) {
              <option [value]="o[0]">{{ o[1] }}</option>
            }
          </select>
        </label>
        <label class="grid gap-1 text-sm">
          <span class="text-ink-muted">Advisor ID</span>
          <input
            type="number"
            min="1"
            inputmode="numeric"
            class="num min-h-11 w-32 rounded-[var(--radius-control)] border border-rule-strong bg-surface px-3"
            [value]="advisorId() ?? ''"
            (change)="advisorId.set(toId($any($event.target).value)); page.set(1)"
          />
        </label>
      </div>
    </header>

    <div class="mt-8">
      @if (runs.isLoading() && !runs.value()) {
        <app-loading what="agent runs" [rows]="6" />
      } @else if (runs.error()) {
        <app-error (retry)="runs.reload()" />
      } @else if (runs.value(); as r) {
        @if (!r.runs.length) {
          <app-empty
            message="No runs match. Every question asked in the advisor assistant adds one here."
          />
        } @else {
          <div class="overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface">
            <table class="ledger w-full min-w-[60rem] text-[0.9375rem]">
              <caption class="sr-only">
                Agent runs, newest first
              </caption>
              <thead class="text-left text-sm text-ink-muted">
                <tr>
                  <th scope="col" class="px-4 py-3 font-medium">When</th>
                  <th scope="col" class="px-4 py-3 font-medium">Advisor</th>
                  <th scope="col" class="px-4 py-3 font-medium">Question</th>
                  <th scope="col" class="px-4 py-3 font-medium">Outcome</th>
                  <th scope="col" class="px-4 py-3 text-right font-medium">Calls</th>
                  <th scope="col" class="px-4 py-3 text-right font-medium">Cache hit</th>
                  <th scope="col" class="px-4 py-3 text-right font-medium">Time</th>
                  <th scope="col" class="px-4 py-3"><span class="sr-only">Open</span></th>
                </tr>
              </thead>
              <tbody>
                @for (run of r.runs; track run.id) {
                  <tr class="border-t border-rule">
                    <td class="num px-4 py-3 whitespace-nowrap">{{ fmt(run.started_at) }}</td>
                    <td class="px-4 py-3 whitespace-nowrap">{{ run.advisor_name }}</td>
                    <td class="max-w-md px-4 py-3">
                      {{ run.question }}
                      @if (run.focus_client_name) {
                        <span class="block text-sm text-ink-muted"
                          >About {{ run.focus_client_name }}</span
                        >
                      }
                    </td>
                    <td class="px-4 py-3 whitespace-nowrap">
                      {{ outcomeLabel[run.outcome] ?? run.outcome }}
                    </td>
                    <td class="num px-4 py-3 text-right whitespace-nowrap">
                      {{ run.model_calls }} model, {{ run.tool_calls }} tool
                    </td>
                    <td class="num px-4 py-3 text-right">
                      {{ run.cache_hit_pct == null ? '—' : run.cache_hit_pct + '%' }}
                    </td>
                    <td class="num px-4 py-3 text-right whitespace-nowrap">
                      {{ seconds(run.duration_ms) }}
                    </td>
                    <td class="px-4 py-2 text-right">
                      <a
                        class="inline-flex min-h-11 items-center rounded-[var(--radius-control)] px-3 text-sm whitespace-nowrap text-admin hover:bg-admin-soft"
                        [routerLink]="['/admin/agent-runs', run.id]"
                        [attr.aria-label]="'Open run ' + run.id"
                        >Open trace</a
                      >
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
          <nav class="mt-4 flex items-center justify-between gap-3" aria-label="Pages">
            <p class="num text-sm text-ink-muted">{{ r.total_rows }} runs</p>
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
                [disabled]="page() * r.page_size >= r.total_rows"
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
export class AdminAgentRuns {
  private readonly api = inject(Api);
  protected readonly page = signal(1);
  protected readonly outcome = signal<string | null>(null);
  protected readonly advisorId = signal<number | null>(null);
  protected readonly runs = rxResource({
    params: () => ({ page: this.page(), outcome: this.outcome(), advisorId: this.advisorId() }),
    stream: ({ params }) =>
      this.api.agentRuns(params.page, { outcome: params.outcome, advisorId: params.advisorId }),
  });
  protected readonly outcomes = Object.entries(OUTCOME_LABEL);
  protected readonly outcomeLabel = OUTCOME_LABEL;
  protected readonly fmt = fmt;
  protected readonly seconds = seconds;
  protected toId(value: string): number | null {
    const n = Number(value);
    return Number.isInteger(n) && n > 0 ? n : null;
  }
}

@Component({
  selector: 'app-admin-agent-run-detail',
  imports: [RouterLink, Icon, Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <a
      routerLink="/admin/agent-runs"
      class="inline-flex min-h-11 items-center gap-2 text-sm text-admin hover:underline"
      ><app-icon name="back" [size]="16" /> All agent runs</a
    >

    @if (runId() === null) {
      <app-empty class="mt-6 block" message="That isn't a run page. Go back to all agent runs." />
    } @else if (run.isLoading() && !run.value()) {
      <app-loading what="this run" [rows]="8" />
    } @else if (run.error()) {
      @if (notFound()) {
        <app-empty
          class="mt-6 block"
          message="There's no run with that ID. Runs are kept for 30 days."
        />
      } @else {
        <app-error (retry)="run.reload()" />
      }
    } @else if (run.value(); as r) {
      <header class="mt-2 max-w-[75ch] space-y-2">
        <p class="text-sm text-ink-muted">
          Run #{{ r.id }}, {{ fmt(r.started_at) }}, asked by {{ r.advisor_name }}
          @if (r.focus_client_name) {
            about {{ r.focus_client_name }}
          }
        </p>
        <h1 class="text-[1.5rem] leading-snug font-semibold">“{{ r.question }}”</h1>
        <p role="note" class="text-sm text-ink-muted">
          <app-icon name="shield" [size]="14" /> Opening this run was recorded in the audit log.
        </p>
      </header>

      <dl
        class="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius-panel)] border border-rule bg-rule sm:grid-cols-3 lg:grid-cols-6"
      >
        @for (f of facts(r); track f[0]) {
          <div class="bg-surface px-4 py-3">
            <dt class="text-sm text-ink-muted">{{ f[0] }}</dt>
            <dd class="num mt-1 font-medium">{{ f[1] }}</dd>
          </div>
        }
      </dl>

      @if (r.answer) {
        <section class="mt-8 max-w-[75ch]" aria-labelledby="answer-title">
          <h2 id="answer-title" class="text-xl font-semibold">Answer shown to the advisor</h2>
          <div class="answer mt-3" [innerHTML]="answerHtml(r.answer)"></div>
        </section>
      }

      <section class="mt-10" aria-labelledby="steps-title">
        <h2 id="steps-title" class="text-xl font-semibold">What happened, step by step</h2>
        <p class="mt-1 mb-4 max-w-[66ch] text-ink-muted">
          Open a step to see the exact request and response. Model requests show only what was new
          in that call; earlier messages were sent too.
        </p>
        <ol class="grid gap-3">
          @for (s of r.steps; track s.seq) {
            <li
              class="rounded-[var(--radius-panel)] border bg-surface"
              [class.border-loss]="s.is_error"
              [class.border-rule]="!s.is_error"
            >
              <details>
                <summary
                  class="grid cursor-pointer grid-cols-[2rem_1fr] gap-x-3 gap-y-1 px-4 py-3 sm:grid-cols-[2rem_9rem_1fr_auto]"
                >
                  <span class="num pt-0.5 text-sm text-ink-muted">{{ s.seq }}</span>
                  <span class="inline-flex items-center gap-2 font-medium">
                    <app-icon [name]="kind[s.kind].icon" [size]="16" />
                    {{ kind[s.kind].label }}
                  </span>
                  <span class="col-start-2 min-w-0 break-words sm:col-start-auto">
                    @if (s.kind === 'model' || s.kind === 'scope_check') {
                      <span class="text-sm text-ink-muted">{{ s.name }}: </span>
                    }
                    {{ summary(s) }}
                    @if (s.is_error) {
                      <span class="ml-1 text-sm font-medium text-loss">Error</span>
                    }
                  </span>
                  <span
                    class="num col-start-2 text-sm text-ink-muted sm:col-start-auto sm:text-right"
                  >
                    {{ stepMeta(s) }}
                  </span>
                </summary>
                <div class="grid gap-4 border-t border-rule px-4 py-4 lg:grid-cols-2">
                  <div class="min-w-0">
                    <h3 class="mb-2 text-sm font-medium text-ink-muted">Request</h3>
                    <pre
                      class="max-h-[28rem] overflow-auto rounded-[var(--radius-control)] bg-surface-sunk p-3 text-[0.8125rem] leading-relaxed"
                      >{{ pretty(s.request) }}</pre>
                  </div>
                  <div class="min-w-0">
                    <h3 class="mb-2 text-sm font-medium text-ink-muted">
                      Response
                      @if (s.stop_reason) {
                        <span class="font-normal">(stop reason: {{ s.stop_reason }})</span>
                      }
                    </h3>
                    <pre
                      class="max-h-[28rem] overflow-auto rounded-[var(--radius-control)] bg-surface-sunk p-3 text-[0.8125rem] leading-relaxed"
                      >{{ pretty(s.response) }}</pre>
                  </div>
                  @if (s.truncated) {
                    <p class="text-sm text-ink-muted lg:col-span-2">
                      This payload was over 64 KB, so only its first 64 KB were stored.
                    </p>
                  }
                </div>
              </details>
            </li>
          }
        </ol>
      </section>

      @if (r.system_prompt) {
        <section class="mt-10" aria-labelledby="prompt-title">
          <h2 id="prompt-title" class="text-xl font-semibold">
            Instructions and tools the model had
          </h2>
          <details class="mt-3 rounded-[var(--radius-panel)] border border-rule bg-surface">
            <summary class="cursor-pointer px-4 py-3">
              System prompt and {{ r.tool_definitions?.length ?? 0 }} tool definitions
              <span class="num text-sm text-ink-muted"
                >(version {{ r.prompt_hash?.slice(0, 12) }})</span
              >
            </summary>
            <div class="grid gap-4 border-t border-rule px-4 py-4">
              <pre
                class="max-h-[28rem] overflow-auto rounded-[var(--radius-control)] bg-surface-sunk p-3 text-[0.8125rem] leading-relaxed whitespace-pre-wrap"
                >{{ r.system_prompt }}</pre>
              <pre
                class="max-h-[28rem] overflow-auto rounded-[var(--radius-control)] bg-surface-sunk p-3 text-[0.8125rem] leading-relaxed"
                >{{ pretty(r.tool_definitions) }}</pre>
            </div>
          </details>
        </section>
      }
    }
  `,
})
export class AdminAgentRunDetail {
  private readonly api = inject(Api);
  /** Route parameter :id. */
  readonly id = input<string>();
  protected readonly runId = computed(() => accountParam(this.id()));
  protected readonly run = rxResource<AgentRunDetail | undefined, number | null>({
    params: () => this.runId(),
    stream: ({ params }) => (params ? this.api.agentRun(params) : of(undefined)),
  });
  protected readonly notFound = computed(() => httpStatus(this.run.error()) === 404);
  protected readonly kind = KIND;
  protected readonly fmt = fmt;
  protected readonly seconds = seconds;
  protected readonly tokens = tokens;
  protected readonly summary = summary;
  protected readonly pretty = pretty;
  protected readonly stepMeta = stepMeta;
  protected readonly answerHtml = renderMarkdown;

  protected facts(r: AgentRunDetail): [string, string][] {
    const totalIn = r.input_tokens + r.cache_read_tokens + r.cache_write_tokens;
    return [
      ['Outcome', OUTCOME_LABEL[r.outcome] ?? r.outcome],
      ['Time', seconds(r.duration_ms)],
      ['Calls', `${r.model_calls} model, ${r.tool_calls} tool`],
      ['Tokens', `${tokens(totalIn)} in, ${tokens(r.output_tokens)} out`],
      ['Cache hit', r.cache_hit_pct == null ? '—' : `${r.cache_hit_pct}%`],
      ['Cost', cost(r.cost_usd)],
    ];
  }
}
