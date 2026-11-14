import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { Api } from '../core/api';
import { DocCount } from '../core/doc-count';
import { filenameFrom, saveBlob } from '../core/download';
import { dateShort, docTypeLabel } from '../core/format';
import { SharedDocument } from '../core/models';
import { Session } from '../core/session';
import { FIELD, apiError } from '../shared/person-picker';
import { Empty, ErrorState, Icon, Loading, Swatch } from '../shared/ui';

const MAX_BYTES = 10 * 1024 * 1024;
const ACCEPT = '.pdf,.txt,.png,.jpg,.jpeg,.docx';
const ALLOWED_EXT = ACCEPT.split(',');
// Types a browser can show in a tab. Anything else (DOCX) is downloaded instead.
const OPENS_IN_TAB = ['application/pdf', 'image/png', 'image/jpeg', 'text/plain'];

/**
 * Documents shared on the signed-in person's accounts, for the advisor and client portals alike.
 * Everyone with access to an account sees its documents; the server decides who that is.
 */
@Component({
  selector: 'app-documents',
  imports: [Swatch, Icon, Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="flex flex-wrap items-end justify-between gap-4">
      <div class="max-w-[62ch] space-y-1">
        <h1 class="text-[1.75rem] font-semibold">Documents</h1>
        <p class="text-ink-muted">
          @if (isAdvisor) {
            Share documents with your clients. Everyone with access to an account sees its
            documents.
          } @else {
            Documents you and your advisor share. Everyone on an account sees its documents.
          }
        </p>
      </div>
      <button
        type="button"
        class="inline-flex min-h-11 items-center gap-2 rounded-[var(--radius-control)] px-4 font-medium text-paper hover:opacity-90"
        [class.bg-advisor]="isAdvisor"
        [class.bg-client]="!isAdvisor"
        (click)="showForm.set(!showForm())"
        [attr.aria-expanded]="showForm()"
        aria-controls="upload-form"
      >
        <app-icon name="file" /> {{ showForm() ? 'Close' : 'Upload a document' }}
      </button>
    </header>

    @if (showForm()) {
      <form
        id="upload-form"
        class="mt-6 grid gap-4 rounded-[var(--radius-panel)] border border-rule bg-surface p-5 sm:grid-cols-2"
        (submit)="$event.preventDefault(); upload()"
      >
        <label class="flex flex-col gap-1 text-sm sm:col-span-2"
          ><span class="text-ink-muted">Account</span>
          @if (accounts.value(); as a) {
            @if (!a.accounts.length) {
              <span class="text-ink"
                >You don't have an account you can add documents to. Viewers can read documents
                but not upload them.</span
              >
            } @else {
              <select
                id="upload-account"
                [class]="field"
                required
                [value]="accountId() ?? ''"
                (change)="accountId.set(+$any($event.target).value || null)"
              >
                <option value="" disabled>Choose an account</option>
                @for (acct of a.accounts; track acct.account_id) {
                  <option [value]="acct.account_id">
                    {{ isAdvisor && acct.clients ? acct.clients + ': ' : ''
                    }}{{ acct.account_name }} #{{ acct.account_id }}
                  </option>
                }
              </select>
            }
          } @else {
            <span class="text-ink-muted">Loading your accounts…</span>
          }
        </label>
        <label class="flex flex-col gap-1 text-sm"
          ><span class="text-ink-muted">Title</span>
          <input
            id="upload-title"
            [class]="field"
            required
            maxlength="120"
            [value]="title()"
            (input)="title.set($any($event.target).value)"
        /></label>
        <label class="flex flex-col gap-1 text-sm"
          ><span class="text-ink-muted">Type</span>
          <select
            id="upload-type"
            [class]="field"
            [value]="docType()"
            (change)="docType.set($any($event.target).value)"
          >
            @for (t of types; track t.value) {
              <option [value]="t.value">{{ t.label }}</option>
            }
          </select></label
        >
        <label class="flex flex-col gap-1 text-sm sm:col-span-2"
          ><span class="text-ink-muted">Note for the others on the account (optional)</span>
          <textarea
            id="upload-note"
            rows="2"
            maxlength="500"
            class="rounded-[var(--radius-control)] border border-rule-strong bg-surface px-3 py-2"
            [value]="note()"
            (input)="note.set($any($event.target).value)"
          ></textarea>
        </label>
        <label class="flex flex-col gap-1 text-sm sm:col-span-2"
          ><span class="text-ink-muted">File</span>
          <input
            id="upload-file"
            type="file"
            required
            [accept]="accept"
            class="min-h-11 text-sm file:mr-3 file:min-h-11 file:rounded-[var(--radius-control)] file:border file:border-rule-strong file:bg-surface file:px-4"
            (change)="pick($any($event.target).files?.[0] ?? null)"
          />
          <span class="text-ink-muted">PDF, TXT, PNG, JPG or DOCX, up to 10 MB.</span>
        </label>
        <div class="flex flex-wrap items-center gap-3 sm:col-span-2">
          <button
            type="submit"
            class="min-h-11 rounded-[var(--radius-control)] bg-ink px-5 font-medium text-paper hover:opacity-90 disabled:opacity-60"
            [disabled]="saving()"
          >
            {{ saving() ? 'Uploading…' : 'Upload' }}
          </button>
          @if (formError()) {
            <p class="text-sm text-loss" role="alert">{{ formError() }}</p>
          }
        </div>
      </form>
    }
    @if (message()) {
      <p class="mt-4 rounded-[var(--radius-control)] border border-rule bg-surface px-4 py-3" role="status">
        {{ message() }}
      </p>
    }

    <section class="mt-8" aria-labelledby="docs-title">
      <div class="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="docs-title" class="text-xl font-semibold">Shared documents</h2>
          @if (docs.value(); as d) {
            <p class="mt-1 text-ink-muted" aria-live="polite">
              @if (d.new_count) {
                {{ d.new_count }} new for you to review.
              } @else {
                Nothing new to review.
              }
            </p>
          }
        </div>
        <div class="flex flex-wrap items-end gap-3">
          @if (accountOptions().length > 1) {
            <label class="flex flex-col gap-1 text-sm"
              ><span class="text-ink-muted">Show account</span>
              <select
                id="docs-account"
                [class]="field"
                (change)="filterAccount.set(+$any($event.target).value || null)"
              >
                <option value="">All accounts</option>
                @for (a of accountOptions(); track a.id) {
                  <option [value]="a.id">{{ a.name }} #{{ a.id }}</option>
                }
              </select></label
            >
          }
          <label class="flex flex-col gap-1 text-sm"
            ><span class="text-ink-muted">Search</span>
            <input
              type="search"
              class="min-h-11 w-56 rounded-[var(--radius-control)] border border-rule-strong bg-surface px-3"
              placeholder="Title or account"
              (input)="query.set($any($event.target).value)"
          /></label>
        </div>
      </div>

      @if (docs.isLoading() && !docs.value()) {
        <app-loading what="documents" [rows]="6" />
      } @else if (docs.error()) {
        <app-error (retry)="docs.reload()" />
      } @else if (docs.value()) {
        @if (!shown().length) {
          <app-empty
            [message]="
              docs.value()?.documents?.length
                ? 'No documents match. Clear the search or choose All accounts.'
                : 'No documents yet. Upload one to share it with everyone on the account.'
            "
          />
        } @else {
          <div class="overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface">
            <table class="ledger w-full min-w-[56rem] text-[0.9375rem]">
              <caption class="sr-only">
                Shared documents, newest first
              </caption>
              <thead class="text-left text-sm text-ink-muted">
                <tr>
                  <th scope="col" class="px-4 py-3 font-medium">Document</th>
                  <th scope="col" class="px-4 py-3 font-medium">Account</th>
                  <th scope="col" class="px-4 py-3 font-medium">Shared by</th>
                  <th scope="col" class="px-4 py-3 font-medium">Date</th>
                  <th scope="col" class="px-4 py-3 font-medium">Opened by others</th>
                  <th scope="col" class="px-4 py-3"><span class="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                @for (d of shown(); track d.document_id) {
                  <tr class="border-t border-rule align-top">
                    <th scope="row" class="max-w-72 px-4 py-3 text-left font-medium">
                      <span class="flex flex-wrap items-center gap-2">
                        {{ d.title }}
                        @if (d.is_new) {
                          <span
                            class="rounded-full border border-ink px-2 py-0.5 text-xs font-semibold"
                            >New</span
                          >
                        }
                      </span>
                      <span class="block text-sm font-normal text-ink-muted"
                        >{{ typeLabel[d.doc_type] ?? d.doc_type }}{{
                          d.original_filename ? ', ' + d.original_filename : ''
                        }}</span
                      >
                      @if (d.note) {
                        <span class="mt-1 block text-sm font-normal">“{{ d.note }}”</span>
                      }
                    </th>
                    <td class="max-w-56 px-4 py-3">
                      <app-swatch [accountId]="d.account_id" [label]="d.account_name" />
                    </td>
                    <td class="px-4 py-3">
                      @if (d.mine) {
                        You
                      } @else if (d.uploaded_by) {
                        {{ d.uploaded_by }}
                        <span class="text-sm text-ink-muted">({{ d.uploaded_by_type }})</span>
                      } @else {
                        <span class="text-ink-muted">—</span>
                      }
                    </td>
                    <td class="num px-4 py-3 whitespace-nowrap">
                      {{ dateShort(d.uploaded_at ?? d.created_date) }}
                    </td>
                    <td class="px-4 py-3 text-ink-muted">
                      {{ d.opened_by || (d.mine ? 'Not opened yet' : '—') }}
                    </td>
                    <td class="px-4 py-2">
                      <div class="flex flex-wrap justify-end gap-1">
                        <button
                          type="button"
                          class="inline-flex min-h-11 items-center gap-1 rounded-[var(--radius-control)] px-3 text-sm hover:bg-surface-sunk disabled:opacity-60"
                          [disabled]="busyId() === d.document_id"
                          [attr.aria-label]="'Open ' + d.title"
                          (click)="open(d)"
                        >
                          <app-icon name="eye" [size]="16" /> Open
                        </button>
                        <button
                          type="button"
                          class="inline-flex min-h-11 items-center gap-1 rounded-[var(--radius-control)] px-3 text-sm hover:bg-surface-sunk disabled:opacity-60"
                          [disabled]="busyId() === d.document_id"
                          [attr.aria-label]="'Download ' + d.title"
                          (click)="download(d)"
                        >
                          <app-icon name="download" [size]="16" /> Download
                        </button>
                        @if (d.mine) {
                          @if (confirmId() === d.document_id) {
                            <button
                              type="button"
                              class="min-h-11 rounded-[var(--radius-control)] bg-loss px-3 text-sm font-medium text-paper"
                              (click)="remove(d)"
                            >
                              Confirm delete
                            </button>
                            <button
                              type="button"
                              class="min-h-11 rounded-[var(--radius-control)] px-3 text-sm hover:bg-surface-sunk"
                              (click)="confirmId.set(null)"
                            >
                              Keep
                            </button>
                          } @else {
                            <button
                              type="button"
                              class="min-h-11 rounded-[var(--radius-control)] px-3 text-sm text-loss hover:bg-surface-sunk"
                              [attr.aria-label]="'Delete ' + d.title"
                              (click)="confirmId.set(d.document_id)"
                            >
                              Delete
                            </button>
                          }
                        }
                      </div>
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      }
    </section>
  `,
})
export class Documents {
  private readonly api = inject(Api);
  private readonly docCount = inject(DocCount);
  protected readonly isAdvisor = inject(Session).user()?.kind === 'advisor';
  protected readonly field = FIELD;
  protected readonly accept = ACCEPT;
  protected readonly typeLabel = docTypeLabel;
  protected readonly dateShort = dateShort;
  protected readonly types = [
    { value: 'statement', label: 'Statement' },
    { value: 'review_notes', label: 'Review notes' },
    { value: 'agreement', label: 'Agreement' },
    { value: 'ips', label: 'Investment policy' },
    { value: 'other', label: 'Other' },
  ];

  protected readonly docs = rxResource({ stream: () => this.api.documents() });
  protected readonly accounts = rxResource({ stream: () => this.api.uploadAccounts() });

  protected readonly query = signal('');
  protected readonly filterAccount = signal<number | null>(null);
  protected readonly accountOptions = computed(() => {
    const seen = new Map<number, string>();
    for (const d of this.docs.value()?.documents ?? []) seen.set(d.account_id, d.account_name);
    return [...seen].map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name));
  });
  protected readonly shown = computed(() => {
    const q = this.query().trim().toLowerCase();
    const acct = this.filterAccount();
    return (this.docs.value()?.documents ?? []).filter(
      (d) =>
        (acct === null || d.account_id === acct) &&
        (!q || `${d.title} ${d.account_name}`.toLowerCase().includes(q)),
    );
  });

  protected readonly showForm = signal(false);
  protected readonly accountId = signal<number | null>(null);
  protected readonly title = signal('');
  protected readonly docType = signal('statement');
  protected readonly note = signal('');
  private file: File | null = null;
  protected readonly saving = signal(false);
  protected readonly formError = signal('');
  protected readonly message = signal('');
  protected readonly busyId = signal<number | null>(null);
  protected readonly confirmId = signal<number | null>(null);

  protected pick(file: File | null): void {
    this.file = file;
    this.formError.set('');
    if (file && !this.title()) this.title.set(file.name.replace(/\.[^.]+$/, ''));
  }

  protected upload(): void {
    const f = this.file;
    const ext = f ? '.' + (f.name.split('.').pop() ?? '').toLowerCase() : '';
    // Quick checks for a friendly message; the server checks again, including the file's contents.
    if (!this.accountId()) return this.formError.set('Choose an account.');
    if (!this.title().trim()) return this.formError.set('Enter a title.');
    if (!f) return this.formError.set('Choose a file.');
    if (!ALLOWED_EXT.includes(ext)) return this.formError.set('Upload a PDF, TXT, PNG, JPG or DOCX file.');
    if (f.size > MAX_BYTES) return this.formError.set('Files can be at most 10 MB.');

    const form = new FormData();
    form.append('account_id', String(this.accountId()));
    form.append('title', this.title().trim());
    form.append('doc_type', this.docType());
    if (this.note().trim()) form.append('note', this.note().trim());
    form.append('file', f, f.name);

    this.saving.set(true);
    this.formError.set('');
    this.api.uploadDocument(form).subscribe({
      next: (r) => {
        this.saving.set(false);
        this.showForm.set(false);
        this.message.set(`Shared ${r.title}. Everyone with access to the account can see it now.`);
        this.title.set('');
        this.note.set('');
        this.file = null;
        this.docs.reload();
      },
      error: (err) => {
        this.saving.set(false);
        this.formError.set(apiError(err, 'The upload didn’t work. Try again.'));
      },
    });
  }

  /** Opens viewable files in a new tab; others download. The tab is opened during the click so it isn't blocked. */
  protected open(d: SharedDocument): void {
    const inTab = OPENS_IN_TAB.some((t) => (d.content_type ?? 'text/plain').startsWith(t));
    if (!inTab) return this.download(d);
    const tab = window.open('', '_blank');
    this.fetch(d, true, (blob, name) => {
      const url = URL.createObjectURL(blob);
      if (tab) {
        tab.location.href = url;
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      } else {
        URL.revokeObjectURL(url);
        saveBlob(blob, name); // pop-ups blocked: save it instead
      }
    }, () => tab?.close());
  }

  protected download(d: SharedDocument): void {
    this.fetch(d, false, (blob, name) => saveBlob(blob, name));
  }

  private fetch(
    d: SharedDocument,
    inline: boolean,
    done: (blob: Blob, name: string) => void,
    failed: () => void = () => undefined,
  ): void {
    this.busyId.set(d.document_id);
    this.message.set('');
    this.api.documentFile(d.document_id, inline).subscribe({
      next: (res) => {
        this.busyId.set(null);
        const name = filenameFrom(res.headers.get('Content-Disposition'), `document-${d.document_id}`);
        if (res.body) done(res.body, name);
        if (d.is_new) {
          this.docs.reload(); // it's no longer new for you
          this.docCount.refresh();
        }
      },
      error: (err) => {
        this.busyId.set(null);
        failed();
        this.message.set(apiError(err, 'That document didn’t open. Reload and try again.'));
      },
    });
  }

  protected remove(d: SharedDocument): void {
    this.confirmId.set(null);
    this.api.deleteDocument(d.document_id).subscribe({
      next: () => {
        this.message.set(`Deleted ${d.title}. No one on the account can see it now.`);
        this.docs.reload();
      },
      error: (err) => this.message.set(apiError(err)),
    });
  }
}
