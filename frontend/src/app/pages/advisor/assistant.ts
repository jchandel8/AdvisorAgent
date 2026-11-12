import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  inject,
  input,
  signal,
  viewChild,
} from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { Api } from '../../core/api';
import { ToolCall } from '../../core/models';
import { accountParam } from '../../shared/filters';
import { Icon } from '../../shared/ui';

interface Message {
  id: number;
  role: 'user' | 'assistant';
  text: string;
  html?: string;
  toolCalls?: ToolCall[];
  fromCache?: boolean;
  error?: boolean;
  blocked?: boolean;
}

const MAX_LENGTH = 2000;

/**
 * Advanced Assistant. The selected client is only context: the API checks the advisor can access that
 * client before every round of tool calls, and every tool is limited to the advisor's accounts.
 */
@Component({
  selector: 'app-assistant',
  imports: [Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flex min-h-[calc(100dvh-10rem)] flex-col">
      <header class="flex flex-wrap items-end justify-between gap-4">
        <div class="space-y-1">
          <h1 class="text-[1.75rem] font-semibold">Assistant</h1>
          <p class="max-w-[62ch] text-ink-muted">
            Ask about your clients in plain English. Answers use only the accounts you have access
            to.
          </p>
        </div>
        <div class="flex flex-wrap items-end gap-3">
          <label class="flex flex-col gap-1 text-sm">
            <span class="text-ink-muted">Questions are about</span>
            <select
              class="min-h-11 w-64 rounded-[var(--radius-control)] border border-rule-strong bg-surface px-3 text-base"
              (change)="chooseClient($any($event.target).value)"
            >
              <option value="" [selected]="clientId() === null">All your clients</option>
              @for (c of clients(); track c.client_id) {
                <option [value]="c.client_id" [selected]="c.client_id === clientId()">
                  {{ c.name }}
                </option>
              }
            </select>
          </label>
          @if (messages().length) {
            <button
              type="button"
              class="inline-flex min-h-11 items-center gap-2 rounded-[var(--radius-control)] border border-rule-strong px-4 text-sm hover:bg-surface-sunk"
              (click)="newConversation()"
            >
              <app-icon name="refresh" [size]="16" /> New conversation
            </button>
          }
        </div>
      </header>

      <!-- Conversation -->
      <section
        class="mt-6 flex-1 space-y-6"
        role="log"
        aria-live="polite"
        aria-label="Conversation"
      >
        @if (!messages().length) {
          <div class="rounded-[var(--radius-panel)] border border-rule bg-surface p-6">
            <p class="font-semibold">Try one of these</p>
            <ul class="mt-3 flex flex-col gap-2">
              @for (s of suggestions(); track s) {
                <li>
                  <button
                    type="button"
                    class="w-full rounded-[var(--radius-control)] border border-rule px-4 py-3 text-left transition-colors duration-150 hover:border-advisor hover:bg-advisor-soft"
                    (click)="send(s)"
                  >
                    {{ s }}
                  </button>
                </li>
              }
            </ul>
          </div>
        }

        @for (m of messages(); track m.id) {
          @if (m.role === 'user') {
            <div class="flex justify-end">
              <p
                class="max-w-[62ch] rounded-[var(--radius-panel)] bg-advisor-soft px-4 py-3 whitespace-pre-wrap"
              >
                <span class="sr-only">You asked: </span>{{ m.text }}
              </p>
            </div>
          } @else {
            <article
              class="max-w-[75ch] space-y-3"
              [attr.aria-label]="m.error ? 'Error' : 'Answer'"
            >
              @if (m.error) {
                <div
                  class="flex items-start gap-3 rounded-[var(--radius-control)] border border-rule bg-surface p-4"
                  role="alert"
                >
                  <app-icon name="alert" class="mt-0.5 text-loss" />
                  <div class="space-y-2">
                    <p>{{ m.text }}</p>
                    <button
                      type="button"
                      class="inline-flex min-h-11 items-center gap-2 rounded-[var(--radius-control)] border border-rule-strong px-3 text-sm hover:bg-surface-sunk"
                      (click)="retry()"
                    >
                      <app-icon name="refresh" [size]="16" /> Ask again
                    </button>
                  </div>
                </div>
              } @else if (m.blocked) {
                <p
                  class="flex items-start gap-3 rounded-[var(--radius-control)] border border-rule bg-surface-sunk p-4"
                >
                  <app-icon name="shield" class="mt-0.5 text-advisor" />
                  <span>{{ m.text }}</span>
                </p>
              } @else {
                <div class="answer" [innerHTML]="m.html"></div>
                <details
                  class="group rounded-[var(--radius-control)] border border-rule bg-surface text-sm"
                >
                  <summary
                    class="flex min-h-11 cursor-pointer list-none items-center gap-2 px-3 text-ink-muted hover:text-ink"
                  >
                    <app-icon name="database" [size]="16" />
                    @if (m.fromCache) {
                      Saved answer to the same question, no AI cost
                    } @else if (m.toolCalls?.length) {
                      Looked up {{ m.toolCalls!.length }}
                      {{ m.toolCalls!.length === 1 ? 'thing' : 'things' }} to answer this
                    } @else {
                      Answered without looking anything up
                    }
                  </summary>
                  @if (m.toolCalls?.length) {
                    <ul class="space-y-1 border-t border-rule px-3 py-3">
                      @for (c of m.toolCalls; track $index) {
                        <li class="flex items-start gap-2">
                          <span class="mt-0.5 text-ink-muted" aria-hidden="true">{{
                            c.is_error ? '✕' : '✓'
                          }}</span>
                          <span>
                            {{ describe(c) }}
                            @if (c.is_error) {
                              <span class="text-ink-muted">: not available to you</span>
                            }
                          </span>
                        </li>
                      }
                    </ul>
                    <p
                      class="flex items-center gap-2 border-t border-rule px-3 py-2 text-ink-muted"
                    >
                      <app-icon name="shield" [size]="16" /> Every lookup ran as you and could only
                      read accounts you have access to.
                    </p>
                  }
                </details>
              }
            </article>
          }
        }

        @if (pending()) {
          <p class="flex items-center gap-3 text-ink-muted" role="status">
            <span class="inline-flex gap-1" aria-hidden="true">
              <span class="h-2 w-2 animate-pulse rounded-full bg-advisor"></span>
              <span
                class="h-2 w-2 animate-pulse rounded-full bg-advisor [animation-delay:150ms]"
              ></span>
              <span
                class="h-2 w-2 animate-pulse rounded-full bg-advisor [animation-delay:300ms]"
              ></span>
            </span>
            Looking that up…
          </p>
        }
        <div #end></div>
      </section>

      <!-- Composer -->
      <form
        class="sticky bottom-20 mt-6 lg:bottom-6"
        (submit)="$event.preventDefault(); send(draft())"
      >
        <div
          class="rounded-[var(--radius-panel)] border border-rule-strong bg-surface p-2 shadow-[0_8px_24px_-12px_rgb(0_0_0/0.25)] focus-within:border-advisor"
        >
          <label for="question" class="sr-only">Your question</label>
          <textarea
            #box
            id="question"
            rows="2"
            class="block w-full resize-none bg-transparent px-3 py-2 outline-none placeholder:text-ink-muted"
            [placeholder]="placeholder()"
            [maxLength]="maxLength"
            [value]="draft()"
            (input)="draft.set($any($event.target).value)"
            (keydown.enter)="onEnter($any($event))"
            [disabled]="pending()"
          ></textarea>
          <div class="flex items-center justify-between gap-3 px-3 pb-1">
            <span class="text-xs text-ink-muted">Enter to send, Shift+Enter for a new line</span>
            <button
              type="submit"
              class="inline-flex min-h-11 items-center gap-2 rounded-[var(--radius-control)] bg-advisor px-4 font-medium text-paper hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              [disabled]="pending() || !draft().trim()"
            >
              <app-icon name="send" [size]="16" /> Ask
            </button>
          </div>
        </div>
      </form>
    </div>
  `,
})
export class Assistant {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly injector = inject(Injector);

  /** ?client= from the URL: the client picked in the dropdown (verified by the API on every message). */
  readonly client = input<string>();
  protected readonly clientId = computed(() => accountParam(this.client()));

  private readonly end = viewChild.required<ElementRef<HTMLElement>>('end');
  private readonly box = viewChild.required<ElementRef<HTMLTextAreaElement>>('box');

  protected readonly maxLength = MAX_LENGTH;
  protected readonly messages = signal<Message[]>([]);
  protected readonly pending = signal(false);
  protected readonly draft = signal('');
  private conversationId: string | null = null;
  private lastQuestion = '';
  private nextId = 1;

  private readonly book = rxResource({ stream: () => this.api.advisorBook() });
  protected readonly clients = computed(() =>
    [...(this.book.value()?.clients ?? [])].sort((a, b) => a.name.localeCompare(b.name)),
  );
  private readonly names = computed(
    () => new Map(this.clients().map((c) => [c.client_id, c.name])),
  );
  private readonly focusName = computed(() => {
    const id = this.clientId();
    return id === null ? null : (this.names().get(id) ?? `client #${id}`);
  });

  protected readonly placeholder = computed(() =>
    this.focusName() ? `Ask about ${this.focusName()}` : 'Ask about your clients',
  );

  protected readonly suggestions = computed(() => {
    const name = this.focusName();
    return name
      ? [
          `How is ${name}'s portfolio allocated, and is it heavy in any sector?`,
          `What did ${name} buy and sell in the last 3 months, and what was the realized gain?`,
          `How has ${name}'s portfolio performed this year and over the last year?`,
        ]
      : [
          'Which of my clients are overweight in tech and have a review due this month?',
          'Who are my five largest clients by value?',
          'Which client reviews are overdue?',
        ];
  });

  protected chooseClient(value: string): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { client: value || null },
    });
  }

  protected newConversation(): void {
    this.messages.set([]);
    this.conversationId = null;
    this.draft.set('');
    this.box().nativeElement.focus();
  }

  protected onEnter(event: KeyboardEvent): void {
    if (event.shiftKey || event.isComposing) return; // new line, or an IME is composing text
    event.preventDefault();
    this.send(this.draft());
  }

  protected retry(): void {
    this.messages.update((ms) => (ms.at(-1)?.error ? ms.slice(0, -1) : ms));
    this.ask(this.lastQuestion, false);
  }

  protected send(text: string): void {
    const question = text.trim().slice(0, MAX_LENGTH);
    if (!question || this.pending()) return;
    this.draft.set('');
    this.ask(question, true);
  }

  private ask(question: string, addUserMessage: boolean): void {
    this.lastQuestion = question;
    if (addUserMessage) this.push({ role: 'user', text: question });
    this.pending.set(true);
    this.scrollToEnd();

    this.api
      .ask({ message: question, conversation_id: this.conversationId, client_id: this.clientId() })
      .subscribe({
        next: (reply) => {
          this.conversationId = reply.conversation_id;
          this.push({
            role: 'assistant',
            text: reply.answer,
            html: renderMarkdown(reply.answer),
            toolCalls: reply.tool_calls,
            fromCache: reply.from_cache,
            blocked: reply.blocked,
          });
          this.pending.set(false);
          this.scrollToEnd();
        },
        error: (err: unknown) => {
          this.push({ role: 'assistant', text: errorText(err), error: true });
          this.pending.set(false);
          this.scrollToEnd();
        },
      });
  }

  private push(m: Omit<Message, 'id'>): void {
    this.messages.update((ms) => [...ms, { ...m, id: this.nextId++ }]);
  }

  private scrollToEnd(): void {
    afterNextRender(
      () =>
        this.end().nativeElement.scrollIntoView({
          behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
          block: 'end',
        }),
      { injector: this.injector },
    );
  }

  /** Plain-language description of one tool call, for the "what was looked up" list. */
  protected describe(c: ToolCall): string {
    const i = c.input as Record<string, unknown>;
    const who = (): string => {
      if (typeof i['client_id'] === 'number')
        return this.names().get(i['client_id']) ?? `client #${i['client_id']}`;
      if (typeof i['account_id'] === 'number') return `account #${i['account_id']}`;
      return 'your clients';
    };
    const filters = [
      ...((i['sectors'] as string[] | undefined) ?? []),
      ...((i['asset_classes'] as string[] | undefined) ?? []).map((a) => a.replace('_', ' ')),
      ...((i['types'] as string[] | undefined) ?? []).map((t) => `${t}s`),
    ];
    const only = filters.length ? `, ${filters.join(' and ')} only` : '';
    switch (c.name) {
      case 'get_my_clients':
        return 'Your client list';
      case 'find_reviews_due':
        return `Reviews due in the next ${i['within_days']} days`;
      case 'get_accounts':
        return `Accounts for ${who()}`;
      case 'get_holdings':
        return `Holdings for ${who()}${only}`;
      case 'get_transactions': {
        const range = i['start_date']
          ? ` from ${i['start_date']}${i['end_date'] ? ` to ${i['end_date']}` : ''}`
          : '';
        return `Transactions for ${who()}${only}${range}`;
      }
      case 'get_performance':
        return `Performance for ${who()}`;
      default:
        return c.name;
    }
  }
}

/** Markdown from the model -> sanitized HTML. DOMPurify removes scripts, handlers and unsafe URLs. */
function renderMarkdown(text: string): string {
  const html = marked.parse(text, { async: false, gfm: true, breaks: false }) as string;
  return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
}

function errorText(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    const detail = (err.error as { detail?: unknown } | null)?.detail;
    if (typeof detail === 'string') return detail;
    if (err.status === 0)
      return "The assistant couldn't be reached. Check that the API is running, then ask again.";
  }
  return 'The assistant ran into a problem with that question. Ask again, or rephrase it.';
}
