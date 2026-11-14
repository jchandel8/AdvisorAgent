import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { of } from 'rxjs';
import { Api } from '../../core/api';
import { filenameFrom, saveBlob } from '../../core/download';
import { dateLong, dateShort, docTypeLabel } from '../../core/format';
import { DocumentDetail } from '../../core/models';
import { accountParam } from '../../shared/filters';
import { FIELD, apiError, httpStatus } from '../../shared/person-picker';
import { Empty, ErrorState, Icon, Loading, Swatch } from '../../shared/ui';
import { fmt } from './logs';

const DOC_TYPES = Object.entries(docTypeLabel).map(([value, label]) => ({ value, label }));

/** Every document across all accounts, newest first, with search and a type filter. */
@Component({
  selector: 'app-admin-documents',
  imports: [RouterLink, Swatch, Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="max-w-[66ch] space-y-1">
      <h1 class="text-[1.75rem] font-semibold">Documents</h1>
      <p class="text-ink-muted">
        Documents on every account. The list shows only titles; opening or downloading a document
        is recorded in the audit log.
      </p>
    </header>

    <div class="mt-8 mb-4 flex flex-wrap items-end gap-3">
      <label class="flex flex-col gap-1 text-sm">
        <span class="text-ink-muted">Search</span>
        <input
          id="doc-search"
          type="search"
          class="min-h-11 w-64 rounded-[var(--radius-control)] border border-rule-strong bg-surface px-3"
          placeholder="Title, account name or ID"
          (input)="query.set($any($event.target).value); page.set(1)"
        />
      </label>
      <label class="flex flex-col gap-1 text-sm">
        <span class="text-ink-muted">Type</span>
        <select
          id="doc-type"
          [class]="field"
          (change)="docTypeFilter.set($any($event.target).value || null); page.set(1)"
        >
          <option value="">All types</option>
          @for (t of types; track t.value) {
            <option [value]="t.value">{{ t.label }}</option>
          }
        </select>
      </label>
    </div>

    @if (docs.isLoading() && !docs.value()) {
      <app-loading what="documents" [rows]="8" />
    } @else if (docs.error()) {
      <app-error (retry)="docs.reload()" />
    } @else if (docs.value(); as d) {
      @if (!d.documents.length) {
        <app-empty message="No documents match. Clear the search or choose All types." />
      } @else {
        <div class="overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface">
          <table class="ledger w-full min-w-[56rem] text-[0.9375rem]">
            <caption class="sr-only">
              Documents, newest first
            </caption>
            <thead class="text-left text-sm text-ink-muted">
              <tr>
                <th scope="col" class="px-4 py-3 font-medium">Title</th>
                <th scope="col" class="px-4 py-3 font-medium">Type</th>
                <th scope="col" class="px-4 py-3 font-medium">Account</th>
                <th scope="col" class="px-4 py-3 font-medium">Uploaded by</th>
                <th scope="col" class="px-4 py-3 font-medium">Date</th>
                <th scope="col" class="px-4 py-3 font-medium">View details</th>
              </tr>
            </thead>
            <tbody>
              @for (r of d.documents; track r.document_id) {
                <tr class="border-t border-rule">
                  <th scope="row" class="px-4 py-3 text-left font-medium">
                    {{ r.title }}
                    @if (r.deleted_at) {
                      <span class="ml-1 text-sm font-normal text-ink-muted">(deleted)</span>
                    }
                  </th>
                  <td class="px-4 py-3">{{ docType[r.doc_type] ?? r.doc_type }}</td>
                  <td class="max-w-56 px-4 py-2">
                    <a
                      class="inline-flex min-h-11 max-w-full items-center hover:underline"
                      [routerLink]="['/admin/accounts', r.account_id]"
                      ><app-swatch
                        [accountId]="r.account_id"
                        [label]="r.account_name + ' #' + r.account_id"
                    /></a>
                  </td>
                  <td class="px-4 py-2">
                    @if (r.uploaded_by_id) {
                      <a
                        class="inline-flex min-h-11 items-center hover:underline"
                        [routerLink]="['/admin/users', r.uploaded_by_type ?? 'advisor', r.uploaded_by_id]"
                        >{{ r.uploaded_by }}</a
                      >
                      <span class="text-sm text-ink-muted">({{ r.uploaded_by_type }})</span>
                    } @else {
                      <span class="text-ink-muted">—</span>
                    }
                  </td>
                  <td class="num px-4 py-3 whitespace-nowrap">{{ dateShort(r.created_date) }}</td>
                  <td class="px-4 py-2">
                    <a
                      class="inline-flex min-h-11 items-center rounded-[var(--radius-control)] px-3 text-sm whitespace-nowrap text-admin hover:bg-admin-soft"
                      [routerLink]="['/admin/documents', r.document_id]"
                      [attr.aria-label]="'View details of ' + r.title"
                      >View details</a
                    >
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
        <nav class="mt-4 flex items-center justify-between gap-3" aria-label="Pages">
          <p class="num text-sm text-ink-muted">
            Page {{ d.page }} of {{ pages(d.total_rows, d.page_size) }} ({{ d.total_rows }}
            documents)
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
              [disabled]="page() >= pages(d.total_rows, d.page_size)"
              (click)="page.set(page() + 1)"
            >
              Next
            </button>
          </div>
        </nav>
      }
    }
  `,
})
export class AdminDocuments {
  private readonly api = inject(Api);
  protected readonly field = FIELD;
  protected readonly types = DOC_TYPES;
  protected readonly docType = docTypeLabel;
  protected readonly dateShort = dateShort;

  protected readonly query = signal('');
  protected readonly docTypeFilter = signal<string | null>(null);
  protected readonly page = signal(1);
  protected readonly docs = rxResource({
    params: () => ({ q: this.query(), type: this.docTypeFilter(), page: this.page() }),
    stream: ({ params }) => this.api.adminDocuments(params.q, params.type, params.page),
  });

  protected pages(total: number, size: number): number {
    return Math.max(1, Math.ceil(total / size));
  }
}

/** One document: who uploaded it and when, a preview and a download, and who has opened it. */
@Component({
  selector: 'app-admin-document-detail',
  imports: [RouterLink, Swatch, Icon, Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <a
      routerLink="/admin/documents"
      class="inline-flex min-h-11 items-center gap-2 text-sm text-admin hover:underline"
      ><app-icon name="back" [size]="16" /> All documents</a
    >

    @if (documentId() === null) {
      <app-empty class="mt-6 block" message="That isn't a document page. Go back to all documents." />
    } @else if (doc.isLoading() && !doc.value()) {
      <app-loading what="this document" [rows]="6" />
    } @else if (doc.error()) {
      @if (notFound()) {
        <app-empty class="mt-6 block" message="There's no document with that ID." />
      } @else {
        <app-error (retry)="doc.reload()" />
      }
    } @else if (doc.value(); as d) {
      <header class="mt-2 flex flex-wrap items-end justify-between gap-4">
        <div class="space-y-1">
          <h1 class="text-[1.75rem] font-semibold">{{ d.title }}</h1>
          <p class="text-ink-muted">
            {{ docType[d.doc_type] ?? d.doc_type }}, document #{{ d.document_id }}
            @if (d.deleted_at) {
              <span class="font-medium text-ink">, deleted by the uploader {{ fmt(d.deleted_at) }}</span>
            }
          </p>
        </div>
        <div class="flex flex-wrap gap-2">
          @if (d.previewable) {
            <button
              type="button"
              class="inline-flex min-h-11 items-center gap-2 rounded-[var(--radius-control)] border border-rule-strong bg-surface px-4 font-medium hover:bg-surface-sunk disabled:opacity-60"
              [disabled]="busy()"
              [attr.aria-expanded]="preview() !== null"
              aria-controls="doc-preview"
              (click)="togglePreview(d.document_id)"
            >
              <app-icon name="eye" /> {{ preview() !== null ? 'Hide preview' : 'Preview' }}
            </button>
          }
          <button
            type="button"
            class="inline-flex min-h-11 items-center gap-2 rounded-[var(--radius-control)] bg-admin px-4 font-medium text-paper hover:opacity-90 disabled:opacity-60"
            [disabled]="busy()"
            (click)="download(d)"
          >
            <app-icon name="download" /> {{ busy() === 'download' ? 'Downloading…' : 'Download' }}
          </button>
        </div>
      </header>
      <p class="mt-3 text-sm text-ink-muted">
        Previewing or downloading this document is recorded in the audit log under your name.
      </p>
      @if (actionError()) {
        <p class="mt-2 text-sm text-loss" role="alert">{{ actionError() }}</p>
      }
      @if (downloaded()) {
        <p class="mt-2 text-sm" role="status">{{ downloaded() }}</p>
      }

      <dl
        class="mt-6 max-w-3xl divide-y divide-rule rounded-[var(--radius-panel)] border border-rule bg-surface"
      >
        <div class="grid gap-1 px-5 py-4 sm:grid-cols-[12rem_1fr] sm:gap-4">
          <dt class="text-ink-muted">Account</dt>
          <dd>
            <a class="hover:underline" [routerLink]="['/admin/accounts', d.account_id]"
              ><app-swatch [accountId]="d.account_id" [label]="d.account_name + ' #' + d.account_id"
            /></a>
          </dd>
        </div>
        <div class="grid gap-1 px-5 py-4 sm:grid-cols-[12rem_1fr] sm:gap-4">
          <dt class="text-ink-muted">Uploaded by</dt>
          <dd>
            @if (d.uploaded_by_id) {
              <a
                class="hover:underline"
                [routerLink]="['/admin/users', d.uploaded_by_type ?? 'advisor', d.uploaded_by_id]"
                >{{ d.uploaded_by }}</a
              >
              <span class="text-ink-muted"> ({{ d.uploaded_by_type }})</span>
            } @else {
              —
            }
          </dd>
        </div>
        <div class="grid gap-1 px-5 py-4 sm:grid-cols-[12rem_1fr] sm:gap-4">
          <dt class="text-ink-muted">{{ d.uploaded_at ? 'Uploaded' : 'Document date' }}</dt>
          <dd>{{ d.uploaded_at ? fmt(d.uploaded_at) : dateLong(d.created_date) }}</dd>
        </div>
        @if (d.original_filename) {
          <div class="grid gap-1 px-5 py-4 sm:grid-cols-[12rem_1fr] sm:gap-4">
            <dt class="text-ink-muted">File</dt>
            <dd class="break-words">{{ d.original_filename }}</dd>
          </div>
        }
        @if (d.note) {
          <div class="grid gap-1 px-5 py-4 sm:grid-cols-[12rem_1fr] sm:gap-4">
            <dt class="text-ink-muted">Note</dt>
            <dd class="break-words">{{ d.note }}</dd>
          </div>
        }
        <div class="grid gap-1 px-5 py-4 sm:grid-cols-[12rem_1fr] sm:gap-4">
          <dt class="text-ink-muted">Last opened</dt>
          <dd>
            @if (d.access_log.length) {
              {{ fmt(d.access_log[0].created_at) }} by {{ d.access_log[0].name }}
              ({{ d.access_log[0].person_type }})
            } @else {
              Never opened
            }
          </dd>
        </div>
        <div class="grid gap-1 px-5 py-4 sm:grid-cols-[12rem_1fr] sm:gap-4">
          <dt class="text-ink-muted">Size</dt>
          <dd class="num">{{ d.size_kb }} KB</dd>
        </div>
      </dl>

      @if (preview() !== null) {
        <section id="doc-preview" class="mt-8 max-w-3xl" aria-labelledby="preview-title">
          <h2 id="preview-title" class="mb-3 text-xl font-semibold">Preview</h2>
          <pre
            class="max-h-[32rem] overflow-auto rounded-[var(--radius-panel)] border border-rule bg-surface p-5 font-sans text-[0.9375rem] leading-relaxed whitespace-pre-wrap"
            >{{ preview() }}</pre
          >
        </section>
      }

      <section class="mt-10 max-w-3xl" aria-labelledby="opened-title">
        <h2 id="opened-title" class="text-xl font-semibold">Who has opened it</h2>
        <p class="mt-1 mb-4 text-ink-muted">
          The 20 most recent opens and downloads, from the admin, advisor and client portals.
        </p>
        @if (!d.access_log.length) {
          <app-empty message="No one has opened or downloaded this document yet." />
        } @else {
          <div class="overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface">
            <table class="ledger w-full min-w-[32rem] text-[0.9375rem]">
              <caption class="sr-only">
                Opens and downloads, newest first
              </caption>
              <thead class="text-left text-sm text-ink-muted">
                <tr>
                  <th scope="col" class="px-4 py-3 font-medium">When</th>
                  <th scope="col" class="px-4 py-3 font-medium">Person</th>
                  <th scope="col" class="px-4 py-3 font-medium">Type</th>
                  <th scope="col" class="px-4 py-3 font-medium">Action</th>
                </tr>
              </thead>
              <tbody>
                @for (e of d.access_log; track e.key) {
                  <tr class="border-t border-rule">
                    <td class="num px-4 py-3 whitespace-nowrap">{{ fmt(e.created_at) }}</td>
                    <td class="px-4 py-3">
                      @if (e.person_id) {
                        <a class="hover:underline" [routerLink]="['/admin/users', e.person_type, e.person_id]">{{
                          e.name
                        }}</a>
                      } @else {
                        {{ e.name }}
                      }
                    </td>
                    <td class="px-4 py-3 capitalize">{{ e.person_type }}</td>
                    <td class="px-4 py-3">
                      {{ e.action === 'view' ? 'Opened' : 'Downloaded' }}
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      </section>
    }
  `,
})
export class AdminDocumentDetail {
  private readonly api = inject(Api);
  /** Route parameter :id. */
  readonly id = input<string>();
  protected readonly documentId = computed(() => accountParam(this.id()));

  protected readonly doc = rxResource<DocumentDetail | undefined, number | null>({
    params: () => this.documentId(),
    stream: ({ params }) => (params ? this.api.adminDocument(params) : of(undefined)),
  });
  protected readonly notFound = computed(() => httpStatus(this.doc.error()) === 404);

  protected readonly preview = signal<string | null>(null);
  protected readonly busy = signal<'preview' | 'download' | null>(null);
  protected readonly actionError = signal('');
  protected readonly downloaded = signal('');

  protected togglePreview(id: number): void {
    if (this.preview() !== null) {
      this.preview.set(null);
      return;
    }
    this.busy.set('preview');
    this.actionError.set('');
    this.api.documentContent(id).subscribe({
      next: (r) => {
        this.busy.set(null);
        this.preview.set(r.text);
        this.doc.reload(); // the view is now in "Who has opened it"
      },
      error: (err) => {
        this.busy.set(null);
        this.actionError.set(apiError(err, 'The preview didn’t load. Try again.'));
      },
    });
  }

  protected download(d: DocumentDetail): void {
    this.busy.set('download');
    this.actionError.set('');
    this.downloaded.set('');
    this.api.downloadDocument(d.document_id).subscribe({
      next: (res) => {
        this.busy.set(null);
        const name = filenameFrom(res.headers.get('Content-Disposition'), `document-${d.document_id}`);
        if (res.body) saveBlob(res.body, name);
        this.downloaded.set(`Downloaded ${name}.`);
        this.doc.reload();
      },
      error: (err) => {
        this.busy.set(null);
        this.actionError.set(apiError(err, 'The download didn’t start. Try again.'));
      },
    });
  }

  protected readonly docType = docTypeLabel;
  protected readonly dateLong = dateLong;
  protected readonly fmt = fmt;
}
