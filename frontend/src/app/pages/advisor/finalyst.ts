import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute, Router } from '@angular/router';
import { Api } from '../../core/api';
import { BriefType, FinalystBrief } from '../../core/models';
import { accountParam } from '../../shared/filters';
import { Empty, ErrorState, Icon, Loading } from '../../shared/ui';

const TYPES: { id: BriefType; label: string; hint: string }[] = [
  {
    id: 'portfolio_review',
    label: 'Portfolio review',
    hint: 'How the portfolio stands against the plan',
  },
  { id: 'market_impact', label: 'Market impact', hint: 'What recent news means for the holdings' },
  { id: 'rebalancing', label: 'Rebalancing ideas', hint: 'Drift from target and ways back' },
  { id: 'meeting_prep', label: 'Meeting prep', hint: 'What to raise, with questions to ask' },
];
const TYPE_LABEL = Object.fromEntries(TYPES.map((t) => [t.id, t.label])) as Record<
  BriefType,
  string
>;

const STAGES: { id: string; label: string }[] = [
  { id: 'checking', label: 'Checking the request' },
  { id: 'facts', label: 'Gathering the client’s facts' },
  { id: 'research', label: 'Researching the market and running the numbers' },
  { id: 'drafting', label: 'Writing the brief' },
  { id: 'reviewing', label: 'Reviewing every figure and suggestion' },
  { id: 'revising', label: 'Fixing what the review found' },
];

const SOURCE_LABEL: Record<string, string> = {
  facts: 'Client data',
  analytics: 'Analytics',
  news: 'News',
  documents: 'Documents',
};

const when = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short' });
const POLL_MS = 2000;

@Component({
  selector: 'app-finalyst',
  imports: [Icon, Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: `
    .stage {
      transition:
        color 200ms cubic-bezier(0.2, 0.8, 0.2, 1),
        opacity 200ms cubic-bezier(0.2, 0.8, 0.2, 1);
    }
    .reveal {
      animation: reveal 320ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
    }
    @keyframes reveal {
      from {
        opacity: 0;
        transform: translateY(6px);
      }
    }
    @media (prefers-reduced-motion: reduce) {
      .stage {
        transition: none;
      }
      .reveal {
        animation: none;
      }
    }
  `,
  template: `
    <header class="max-w-[70ch] space-y-1">
      <h1 class="text-[1.75rem] font-semibold">AI Finalyst</h1>
      <p class="text-ink-muted">
        A team of AI agents prepares a brief about one client for you: their facts, what the market
        is doing around their holdings, and suggestions with the evidence behind each. You decide
        what to do; nothing is sent to the client.
      </p>
    </header>

    <form
      class="mt-8 grid gap-6 rounded-[var(--radius-panel)] border border-rule bg-surface p-5 lg:grid-cols-[18rem_1fr]"
      (submit)="$event.preventDefault(); run(false)"
    >
      <div class="grid content-start gap-5">
        <label class="grid gap-1 text-sm">
          <span class="font-medium">Client</span>
          <select
            class="min-h-11 rounded-[var(--radius-control)] border border-rule-strong bg-surface px-3 text-base"
            [value]="clientId() ?? ''"
            (change)="clientId.set(toId($any($event.target).value))"
            required
          >
            <option value="" disabled>Choose a client</option>
            @for (c of clients(); track c.client_id) {
              <option [value]="c.client_id">{{ c.name }}</option>
            }
          </select>
        </label>
        <label class="grid gap-1 text-sm">
          <span class="font-medium"
            >Note for the team <span class="text-ink-muted">(optional)</span></span
          >
          <textarea
            rows="3"
            maxlength="500"
            class="rounded-[var(--radius-control)] border border-rule-strong bg-surface px-3 py-2 text-base"
            placeholder="e.g. They asked about retiring two years early."
            [value]="note()"
            (input)="note.set($any($event.target).value)"
          ></textarea>
        </label>
      </div>

      <fieldset class="grid content-start gap-3">
        <legend class="mb-1 text-sm font-medium">Kind of brief</legend>
        <div class="grid gap-3 sm:grid-cols-2">
          @for (t of types; track t.id) {
            <label
              class="flex min-h-11 cursor-pointer gap-3 rounded-[var(--radius-control)] border px-4 py-3"
              [class.border-advisor]="briefType() === t.id"
              [class.bg-advisor-soft]="briefType() === t.id"
              [class.border-rule-strong]="briefType() !== t.id"
            >
              <input
                type="radio"
                name="brief-type"
                class="mt-1"
                [value]="t.id"
                [checked]="briefType() === t.id"
                (change)="briefType.set(t.id)"
              />
              <span>
                <span class="block font-medium">{{ t.label }}</span>
                <span class="block text-sm text-ink-muted">{{ t.hint }}</span>
              </span>
            </label>
          }
        </div>
        <div class="mt-2 flex flex-wrap items-center gap-3">
          <button
            type="submit"
            class="inline-flex min-h-11 items-center gap-2 rounded-[var(--radius-control)] bg-advisor px-5 font-medium text-paper hover:opacity-90 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
            [disabled]="!clientId() || running()"
          >
            <app-icon name="lightbulb" [size]="18" /> Prepare brief
          </button>
          @if (startError()) {
            <p role="alert" class="text-sm text-loss">{{ startError() }}</p>
          }
        </div>
      </fieldset>
    </form>

    @if (briefId() !== null) {
      <section class="mt-10" aria-labelledby="brief-title" aria-live="polite">
        @if (brief.isLoading() && !brief.value()) {
          <app-loading what="the brief" [rows]="6" />
        } @else if (brief.error()) {
          <app-error (retry)="brief.reload()" />
        } @else if (brief.value(); as b) {
          <div class="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p class="text-sm text-ink-muted">
                {{ typeLabel[b.brief_type] }} for {{ b.client_name }}, started
                {{ fmt(b.created_at) }}
              </p>
              <h2 id="brief-title" class="text-xl font-semibold">
                @switch (b.status) {
                  @case ('running') {
                    Preparing the brief…
                  }
                  @case ('failed') {
                    The brief couldn’t be prepared
                  }
                  @default {
                    Brief
                  }
                }
              </h2>
            </div>
            @if (b.status === 'done' && reused()) {
              <button
                type="button"
                class="min-h-11 rounded-[var(--radius-control)] border border-rule-strong px-4 text-sm"
                (click)="run(true)"
              >
                Prepared earlier today. Run again
              </button>
            }
          </div>

          @if (b.status === 'running') {
            <ol class="mt-5 grid gap-2">
              @for (s of stages; track s.id; let i = $index) {
                <li
                  class="stage flex items-center gap-3"
                  [class.text-ink-muted]="stageIndex(b.stage) < i"
                  [class.font-medium]="stageIndex(b.stage) === i"
                >
                  <span
                    class="grid size-6 place-items-center rounded-full border text-xs"
                    [class.bg-advisor]="stageIndex(b.stage) > i"
                    [class.text-paper]="stageIndex(b.stage) > i"
                    [class.border-advisor]="stageIndex(b.stage) >= i"
                  >
                    @if (stageIndex(b.stage) > i) {
                      <app-icon name="check" [size]="14" />
                    } @else {
                      {{ i + 1 }}
                    }
                  </span>
                  {{ s.label }}
                </li>
              }
            </ol>
            <p class="mt-4 text-sm text-ink-muted">
              This usually takes about a minute. You can leave this page.
            </p>
          } @else if (b.status === 'failed') {
            <p class="mt-3 max-w-[66ch]">{{ b.error }}</p>
          } @else if (b.brief; as c) {
            <div class="reveal mt-5 grid gap-8">
              <div class="max-w-[75ch] space-y-3">
                <p class="text-lg leading-relaxed">{{ c.summary }}</p>
                <p class="text-ink-muted">{{ c.client_snapshot }}</p>
              </div>

              <div class="grid gap-4 lg:grid-cols-2">
                @for (s of c.suggestions; track $index) {
                  <article
                    class="grid content-start gap-3 rounded-[var(--radius-panel)] border border-rule bg-surface p-5"
                  >
                    <div class="flex items-start justify-between gap-3">
                      <h3 class="text-lg font-semibold">{{ s.title }}</h3>
                      <span
                        class="shrink-0 rounded-full border border-rule-strong px-2 py-0.5 text-xs"
                      >
                        {{ s.confidence }} confidence
                      </span>
                    </div>
                    <p>{{ s.rationale }}</p>
                    <ul class="grid gap-2 text-sm">
                      @for (e of s.evidence; track $index) {
                        <li class="rounded-[var(--radius-control)] bg-surface-sunk px-3 py-2">
                          <span class="font-medium">{{ sourceLabel[e.source] ?? e.source }}:</span>
                          {{ e.detail }}
                          @if (e.url) {
                            <a
                              class="ml-1 text-advisor underline"
                              [href]="e.url"
                              target="_blank"
                              rel="noopener noreferrer"
                              >Source</a
                            >
                          }
                        </li>
                      }
                    </ul>
                    <p class="text-sm"><span class="font-medium">Risks:</span> {{ s.risks }}</p>
                  </article>
                }
              </div>

              <div class="grid gap-6 lg:grid-cols-3">
                @if (c.questions_for_meeting.length) {
                  <div>
                    <h3 class="font-semibold">Questions for the meeting</h3>
                    <ul class="mt-2 list-disc space-y-1 pl-5">
                      @for (q of c.questions_for_meeting; track $index) {
                        <li>{{ q }}</li>
                      }
                    </ul>
                  </div>
                }
                @if (c.watch_list.length) {
                  <div>
                    <h3 class="font-semibold">Watch list</h3>
                    <p class="mt-2">{{ c.watch_list.join(', ') }}</p>
                  </div>
                }
                @if (c.sources.length) {
                  <div>
                    <h3 class="font-semibold">News sources</h3>
                    <ul class="mt-2 space-y-1 text-sm">
                      @for (src of c.sources; track src.url) {
                        <li>
                          <a
                            class="text-advisor underline"
                            [href]="src.url"
                            target="_blank"
                            rel="noopener noreferrer"
                            >{{ src.title }}</a
                          >
                          <span class="text-ink-muted"> ({{ src.source }})</span>
                        </li>
                      }
                    </ul>
                  </div>
                }
              </div>

              @if (b.review; as r) {
                <div
                  class="max-w-[75ch] rounded-[var(--radius-panel)] border border-rule p-4 text-sm"
                >
                  <p class="font-medium">
                    @if (r.approved) {
                      Reviewed: every figure is backed by the data and the suggestions fit the
                      client’s profile.
                    } @else {
                      Reviewer’s notes to weigh:
                    }
                    @if (r.revised) {
                      <span class="font-normal text-ink-muted">(revised once after review)</span>
                    }
                  </p>
                  @if (!r.approved && r.issues.length) {
                    <ul class="mt-2 list-disc space-y-1 pl-5">
                      @for (i of r.issues; track $index) {
                        <li>{{ i }}</li>
                      }
                    </ul>
                  }
                </div>
              }
              <p class="text-sm text-ink-muted">{{ c.disclaimer }}</p>
            </div>
          }
        }
      </section>
    }

    <section class="mt-12" aria-labelledby="history-title">
      <h2 id="history-title" class="text-xl font-semibold">Earlier briefs</h2>
      @if (history.value(); as h) {
        @if (!h.briefs.length) {
          <app-empty
            class="mt-4 block"
            message="No briefs yet. Choose a client and a kind of brief above."
          />
        } @else {
          <ul
            class="mt-4 divide-y divide-rule rounded-[var(--radius-panel)] border border-rule bg-surface"
          >
            @for (item of h.briefs; track item.id) {
              <li>
                <button
                  type="button"
                  class="grid w-full gap-1 px-4 py-3 text-left hover:bg-surface-sunk sm:grid-cols-[14rem_10rem_1fr]"
                  (click)="open(item.id)"
                >
                  <span class="font-medium">{{ item.client_name }}</span>
                  <span class="text-sm text-ink-muted"
                    >{{ typeLabel[item.brief_type] }}, {{ fmt(item.created_at) }}</span
                  >
                  <span class="truncate text-sm">{{
                    item.status === 'done'
                      ? item.summary
                      : item.status === 'running'
                        ? 'Preparing…'
                        : 'Failed'
                  }}</span>
                </button>
              </li>
            }
          </ul>
        }
      }
    </section>
  `,
})
export class Finalyst {
  private readonly api = inject(Api);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  protected readonly types = TYPES;
  protected readonly typeLabel = TYPE_LABEL;
  protected readonly stages = STAGES;
  protected readonly sourceLabel = SOURCE_LABEL;

  protected readonly clientId = signal<number | null>(null);
  protected readonly briefType = signal<BriefType>('portfolio_review');
  protected readonly note = signal('');
  protected readonly startError = signal<string | null>(null);
  protected readonly reused = signal(false);
  protected readonly briefId = signal<number | null>(null);

  private readonly book = rxResource({ stream: () => this.api.advisorBook() });
  protected readonly clients = computed(() =>
    [...(this.book.value()?.clients ?? [])].sort((a, b) => a.name.localeCompare(b.name)),
  );
  protected readonly history = rxResource({ stream: () => this.api.finalystBriefs() });
  protected readonly brief = rxResource<FinalystBrief, number | undefined>({
    params: () => this.briefId() ?? undefined, // idle until a brief is chosen
    stream: ({ params }) => this.api.finalystBrief(params),
  });
  protected readonly running = computed(() => this.brief.value()?.status === 'running');

  constructor() {
    const params = this.route.snapshot.queryParamMap;
    const client = accountParam(params.get('client') ?? undefined);
    if (client) this.clientId.set(client);
    const id = accountParam(params.get('brief') ?? undefined);
    if (id) this.briefId.set(id);

    // While a brief is running, reload it every 2 seconds to show the stage; stop when it finishes.
    const timer = setInterval(() => {
      if (this.running() && !this.brief.isLoading()) {
        this.brief.reload();
      } else if (this.wasRunning && !this.running()) {
        this.wasRunning = false;
        this.history.reload();
      }
      this.wasRunning ||= this.running();
    }, POLL_MS);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  private wasRunning = false;

  protected run(refresh: boolean): void {
    const clientId = this.clientId();
    if (!clientId) return;
    this.startError.set(null);
    this.api
      .startBrief({
        client_id: clientId,
        brief_type: this.briefType(),
        note: this.note().trim() || null,
        refresh,
      })
      .subscribe({
        next: (r) => {
          this.reused.set(r.reused);
          this.open(r.id);
          this.history.reload();
        },
        error: (err: unknown) => this.startError.set(errorText(err)),
      });
  }

  protected open(id: number): void {
    this.briefId.set(id);
    this.brief.reload();
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { brief: id },
      replaceUrl: true,
    });
  }

  protected stageIndex(stage: string | null): number {
    const i = STAGES.findIndex((s) => s.id === stage);
    return i < 0 ? 0 : i;
  }

  protected toId(value: string): number | null {
    return accountParam(value || undefined);
  }

  protected fmt(iso: string): string {
    return when.format(new Date(iso));
  }
}

function errorText(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    const detail = (err.error as { detail?: unknown } | null)?.detail;
    if (typeof detail === 'string') return detail;
  }
  return 'The brief couldn’t be started. Try again.';
}
