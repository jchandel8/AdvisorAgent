import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { of } from 'rxjs';
import { Api } from '../../core/api';
import { accountTypeLabel, dateLong, dateShort, docTypeLabel, roleLabel } from '../../core/format';
import { AccountDetail } from '../../core/models';
import { accountParam } from '../../shared/filters';
import { httpStatus } from '../../shared/person-picker';
import { Empty, ErrorState, Icon, Loading, Swatch } from '../../shared/ui';

/** One account: its facts, everyone who can see it, and its documents. No portfolio values. */
@Component({
  selector: 'app-admin-account-detail',
  imports: [RouterLink, Swatch, Icon, Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <a
      routerLink="/admin/accounts"
      class="inline-flex min-h-11 items-center gap-2 text-sm text-admin hover:underline"
      ><app-icon name="back" [size]="16" /> All accounts</a
    >

    @if (accountId() === null) {
      <app-empty class="mt-6 block" message="That isn't an account page. Go back to all accounts." />
    } @else if (account.isLoading() && !account.value()) {
      <app-loading what="this account" [rows]="6" />
    } @else if (account.error()) {
      @if (notFound()) {
        <app-empty class="mt-6 block" message="There's no account with that ID." />
      } @else {
        <app-error (retry)="account.reload()" />
      }
    } @else if (account.value(); as a) {
      <header class="mt-2 flex flex-wrap items-end justify-between gap-4">
        <div class="space-y-1">
          <h1 class="text-[1.75rem] font-semibold">
            <app-swatch [accountId]="a.account_id" [label]="a.account_name" />
          </h1>
          <p class="text-ink-muted">
            {{ typeLabel[a.account_type] }} account #{{ a.account_id }}, opened
            {{ dateLong(a.open_date) }}
            @if (a.close_date) {
              <span class="font-medium text-ink">, closed {{ dateLong(a.close_date) }}</span>
            }
          </p>
          @if (a.description) {
            <p class="max-w-[66ch]">{{ a.description }}</p>
          }
        </div>
        <a
          class="inline-flex min-h-11 items-center gap-2 rounded-[var(--radius-control)] bg-admin px-4 font-medium text-paper hover:opacity-90"
          [routerLink]="['/admin/permissions']"
          [queryParams]="{ account: a.account_id }"
          ><app-icon name="shield" /> Manage access</a
        >
      </header>

      <section class="mt-8" aria-labelledby="people-title">
        <h2 id="people-title" class="text-xl font-semibold">People with access</h2>
        <p class="mt-1 mb-4 max-w-[66ch] text-ink-muted">
          Exactly who can see this account in the advisor and client portals.
        </p>
        <div class="overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface">
          <table class="ledger w-full min-w-[44rem] text-[0.9375rem]">
            <caption class="sr-only">
              People with access to {{ a.account_name }}
            </caption>
            <thead class="text-left text-sm text-ink-muted">
              <tr>
                <th scope="col" class="px-4 py-3 font-medium">Name</th>
                <th scope="col" class="px-4 py-3 font-medium">Type</th>
                <th scope="col" class="px-4 py-3 font-medium">Role</th>
                <th scope="col" class="px-4 py-3 font-medium">Since</th>
                <th scope="col" class="px-4 py-3 font-medium">Granted by</th>
              </tr>
            </thead>
            <tbody>
              @for (p of a.access; track p.access_id) {
                <tr class="border-t border-rule">
                  <th scope="row" class="px-4 py-2 text-left font-medium">
                    <a
                      class="inline-flex min-h-11 items-center gap-2 hover:underline"
                      [routerLink]="['/admin/users', p.person_type, p.person_id]"
                      >{{ p.name }}
                      <span class="text-sm font-normal text-ink-muted">{{ p.username }}</span></a
                    >
                  </th>
                  <td class="px-4 py-3 capitalize">{{ p.person_type }}</td>
                  <td class="px-4 py-3">{{ roleLabel[p.role] ?? p.role }}</td>
                  <td class="num px-4 py-3 whitespace-nowrap">{{ dateShort(p.granted_at) }}</td>
                  <td class="px-4 py-3 text-ink-muted">{{ p.granted_by || 'Seeded data' }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      </section>

      <section class="mt-10" aria-labelledby="docs-title">
        <h2 id="docs-title" class="text-xl font-semibold">Documents</h2>
        <p class="mt-1 mb-4 max-w-[66ch] text-ink-muted">
          Opening or downloading a document is recorded in the audit log.
        </p>
        @if (!a.documents.length) {
          <app-empty message="This account has no documents." />
        } @else {
          <div class="overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface">
            <table class="ledger w-full min-w-[44rem] text-[0.9375rem]">
              <caption class="sr-only">
                Documents of {{ a.account_name }}, newest first
              </caption>
              <thead class="text-left text-sm text-ink-muted">
                <tr>
                  <th scope="col" class="px-4 py-3 font-medium">Title</th>
                  <th scope="col" class="px-4 py-3 font-medium">Type</th>
                  <th scope="col" class="px-4 py-3 font-medium">Date</th>
                  <th scope="col" class="px-4 py-3 font-medium">Uploaded by</th>
                  <th scope="col" class="px-4 py-3"><span class="sr-only">Details</span></th>
                </tr>
              </thead>
              <tbody>
                @for (d of a.documents; track d.document_id) {
                  <tr class="border-t border-rule">
                    <th scope="row" class="px-4 py-3 text-left font-medium">{{ d.title }}</th>
                    <td class="px-4 py-3">{{ docType[d.doc_type] ?? d.doc_type }}</td>
                    <td class="num px-4 py-3 whitespace-nowrap">{{ dateShort(d.created_date) }}</td>
                    <td class="px-4 py-3 text-ink-muted">
                      {{ d.uploaded_by || '—' }}{{ d.uploaded_by_type ? ' (' + d.uploaded_by_type + ')' : '' }}{{
                        d.deleted_at ? ', deleted' : ''
                      }}
                    </td>
                    <td class="px-4 py-2 text-right">
                      <a
                        class="inline-flex min-h-11 items-center rounded-[var(--radius-control)] px-3 text-sm whitespace-nowrap text-admin hover:bg-admin-soft"
                        [routerLink]="['/admin/documents', d.document_id]"
                        [attr.aria-label]="'View details of ' + d.title"
                        >View details</a
                      >
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
export class AdminAccountDetail {
  private readonly api = inject(Api);
  /** Route parameter :id. */
  readonly id = input<string>();
  protected readonly accountId = computed(() => accountParam(this.id()));

  protected readonly account = rxResource<AccountDetail | undefined, number | null>({
    params: () => this.accountId(),
    stream: ({ params }) => (params ? this.api.adminAccount(params) : of(undefined)),
  });
  protected readonly notFound = computed(
    () => httpStatus(this.account.error()) === 404,
  );

  protected readonly typeLabel = accountTypeLabel;
  protected readonly roleLabel = roleLabel;
  protected readonly docType = docTypeLabel;
  protected readonly dateLong = dateLong;
  protected readonly dateShort = dateShort;
}
