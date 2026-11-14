import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { Api } from '../../core/api';
import { accountTypeLabel, dateShort } from '../../core/format';
import { Person } from '../../core/models';
import { FIELD, PersonPicker, apiError } from '../../shared/person-picker';
import { Empty, ErrorState, Icon, Loading, Swatch } from '../../shared/ui';

@Component({
  selector: 'app-admin-accounts',
  imports: [RouterLink, PersonPicker, Swatch, Icon, Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="flex flex-wrap items-end justify-between gap-4">
      <div class="space-y-1">
        <h1 class="text-[1.75rem] font-semibold">Accounts</h1>
        <p class="max-w-[62ch] text-ink-muted">
          A new account starts empty. Its owners and advisors can see it as soon as it's created.
        </p>
      </div>
      <button
        type="button"
        class="inline-flex min-h-11 items-center gap-2 rounded-[var(--radius-control)] bg-admin px-4 font-medium text-paper hover:opacity-90"
        (click)="showForm.set(!showForm())"
        [attr.aria-expanded]="showForm()"
      >
        <app-icon name="briefcase" /> {{ showForm() ? 'Close' : 'Create account' }}
      </button>
    </header>

    @if (showForm()) {
      <form
        class="mt-6 grid gap-4 rounded-[var(--radius-panel)] border border-rule bg-surface p-5 sm:grid-cols-2"
        (submit)="$event.preventDefault(); create()"
      >
        <label class="flex flex-col gap-1 text-sm"
          ><span class="text-ink-muted">Account name</span>
          <input
            id="acct-name"
            [class]="field"
            required
            [value]="name()"
            (input)="name.set($any($event.target).value)"
        /></label>
        <label class="flex flex-col gap-1 text-sm"
          ><span class="text-ink-muted">Type</span>
          <select
            id="acct-type"
            [class]="field"
            [value]="type()"
            (change)="type.set($any($event.target).value)"
          >
            <option value="individual">Individual</option>
            <option value="joint">Joint (two owners)</option>
            <option value="ira">IRA</option>
            <option value="trust">Trust</option>
          </select></label
        >
        <div>
          <app-person-picker label="Owners (clients)" kind="client" (picked)="addOwner($event)" />
          <ul class="mt-2 flex flex-wrap gap-2" aria-label="Chosen owners">
            @for (p of owners(); track p.person_id) {
              <li
                class="inline-flex items-center gap-2 rounded-full border border-rule-strong px-3 py-1 text-sm"
              >
                {{ p.name }}
                <button
                  type="button"
                  class="text-ink-muted hover:text-ink"
                  [attr.aria-label]="'Remove ' + p.name"
                  (click)="owners.set(remove(owners(), p))"
                >
                  ✕
                </button>
              </li>
            }
          </ul>
        </div>
        <div>
          <app-person-picker label="Advisors" kind="advisor" (picked)="addAdvisor($event)" />
          <ul class="mt-2 flex flex-wrap gap-2" aria-label="Chosen advisors">
            @for (p of advisors(); track p.person_id) {
              <li
                class="inline-flex items-center gap-2 rounded-full border border-rule-strong px-3 py-1 text-sm"
              >
                {{ p.name }}
                <button
                  type="button"
                  class="text-ink-muted hover:text-ink"
                  [attr.aria-label]="'Remove ' + p.name"
                  (click)="advisors.set(remove(advisors(), p))"
                >
                  ✕
                </button>
              </li>
            }
          </ul>
        </div>
        <div class="flex flex-wrap items-center gap-3 sm:col-span-2">
          <button
            type="submit"
            class="min-h-11 rounded-[var(--radius-control)] bg-ink px-5 font-medium text-paper hover:opacity-90 disabled:opacity-60"
            [disabled]="saving()"
          >
            {{ saving() ? 'Creating…' : 'Create account' }}
          </button>
          <span class="text-sm text-ink-muted"
            >{{ type() === 'joint' ? 'Pick two owners.' : 'Pick one owner.' }} Pick at least one
            advisor.</span
          >
          @if (formError()) {
            <p class="w-full text-sm text-loss" role="alert">{{ formError() }}</p>
          }
        </div>
      </form>
    }
    @if (created()) {
      <p
        class="mt-4 rounded-[var(--radius-control)] border border-rule bg-admin-soft px-4 py-3"
        role="status"
      >
        {{ created() }}
      </p>
    }

    <section class="mt-8" aria-labelledby="accounts-title">
      <div class="mb-4 flex flex-wrap items-end justify-between gap-3">
        <h2 id="accounts-title" class="text-xl font-semibold">All accounts</h2>
        <label class="flex flex-col gap-1 text-sm"
          ><span class="text-ink-muted">Search</span>
          <input
            type="search"
            class="min-h-11 w-64 rounded-[var(--radius-control)] border border-rule-strong bg-surface px-3"
            placeholder="Account name or ID"
            (input)="query.set($any($event.target).value)"
        /></label>
      </div>
      @if (accounts.isLoading() && !accounts.value()) {
        <app-loading what="accounts" [rows]="6" />
      } @else if (accounts.error()) {
        <app-error (retry)="accounts.reload()" />
      } @else if (accounts.value(); as a) {
        @if (!a.accounts.length) {
          <app-empty message="No accounts match that search." />
        } @else {
          <div class="overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface">
            <table class="ledger w-full min-w-[52rem] text-[0.9375rem]">
              <caption class="sr-only">
                All accounts, newest first
              </caption>
              <thead class="text-left text-sm text-ink-muted">
                <tr>
                  <th scope="col" class="px-4 py-3 font-medium">Account</th>
                  <th scope="col" class="px-4 py-3 font-medium">Type</th>
                  <th scope="col" class="px-4 py-3 font-medium">Clients</th>
                  <th scope="col" class="px-4 py-3 font-medium">Advisors</th>
                  <th scope="col" class="px-4 py-3 font-medium">Opened</th>
                  <th scope="col" class="px-4 py-3"><span class="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                @for (r of a.accounts; track r.account_id) {
                  <tr class="border-t border-rule">
                    <th scope="row" class="max-w-64 px-4 py-2 text-left font-medium">
                      <a
                        class="inline-flex min-h-11 max-w-full items-center hover:underline"
                        [routerLink]="['/admin/accounts', r.account_id]"
                        ><app-swatch
                          [accountId]="r.account_id"
                          [label]="r.account_name + ' #' + r.account_id"
                      /></a>
                    </th>
                    <td class="px-4 py-3">
                      {{ typeLabel[r.account_type] }}{{ r.close_date ? ' (closed)' : '' }}
                    </td>
                    <td class="px-4 py-3 text-ink-muted">{{ r.clients || '—' }}</td>
                    <td class="px-4 py-3 text-ink-muted">{{ r.advisors || '—' }}</td>
                    <td class="num px-4 py-3 whitespace-nowrap">{{ dateShort(r.open_date) }}</td>
                    <td class="px-4 py-2 text-right">
                      <a
                        class="inline-flex min-h-11 items-center rounded-[var(--radius-control)] px-3 text-sm text-admin hover:bg-admin-soft"
                        [routerLink]="['/admin/permissions']"
                        [queryParams]="{ account: r.account_id }"
                        >Manage access</a
                      >
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
export class AdminAccounts {
  private readonly api = inject(Api);
  protected readonly field = FIELD;
  protected readonly typeLabel = accountTypeLabel;
  protected readonly dateShort = dateShort;

  protected readonly query = signal('');
  protected readonly accounts = rxResource({
    params: () => ({ q: this.query() }),
    stream: ({ params }) => this.api.adminAccounts(params.q),
  });

  protected readonly showForm = signal(false);
  protected readonly name = signal('');
  protected readonly type = signal<'individual' | 'joint' | 'ira' | 'trust'>('individual');
  protected readonly owners = signal<Person[]>([]);
  protected readonly advisors = signal<Person[]>([]);
  protected readonly saving = signal(false);
  protected readonly formError = signal('');
  protected readonly created = signal('');

  protected addOwner(p: Person): void {
    if (!this.owners().some((o) => o.person_id === p.person_id))
      this.owners.set([...this.owners(), p]);
  }
  protected addAdvisor(p: Person): void {
    if (!this.advisors().some((o) => o.person_id === p.person_id))
      this.advisors.set([...this.advisors(), p]);
  }
  protected remove(list: Person[], p: Person): Person[] {
    return list.filter((x) => x.person_id !== p.person_id);
  }

  protected create(): void {
    this.saving.set(true);
    this.formError.set('');
    this.api
      .createAccount({
        account_name: this.name(),
        account_type: this.type(),
        owner_client_ids: this.owners().map((p) => p.person_id),
        advisor_ids: this.advisors().map((p) => p.person_id),
      })
      .subscribe({
        next: (r) => {
          this.saving.set(false);
          this.showForm.set(false);
          this.created.set(
            `Created ${r.account_name} (#${r.account_id}). Its owners and advisors can see it now.`,
          );
          this.name.set('');
          this.owners.set([]);
          this.advisors.set([]);
          this.accounts.reload();
        },
        error: (err) => {
          this.saving.set(false);
          this.formError.set(apiError(err));
        },
      });
  }
}
