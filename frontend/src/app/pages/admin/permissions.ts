import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { of } from 'rxjs';
import { Api } from '../../core/api';
import { accountTypeLabel, dateShort } from '../../core/format';
import { AccessRow, Person } from '../../core/models';
import { accountParam } from '../../shared/filters';
import { FIELD, PersonPicker, apiError } from '../../shared/person-picker';
import { Empty, ErrorState, Loading, Swatch, isNotFound } from '../../shared/ui';

const ROLE_LABEL: Record<string, string> = {
  owner: 'Owner',
  joint_owner: 'Joint owner',
  advisor: 'Advisor',
  viewer: 'Viewer (read only)',
};

@Component({
  selector: 'app-admin-permissions',
  imports: [PersonPicker, Swatch, Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="max-w-[66ch] space-y-1">
      <h1 class="text-[1.75rem] font-semibold">Permissions</h1>
      <p class="text-ink-muted">
        Who can see an account. Changes take effect on the person's next page load, and are recorded
        in the audit log.
      </p>
    </header>

    <div class="mt-6 flex flex-wrap items-end gap-3">
      <label class="flex flex-col gap-1 text-sm"
        ><span class="text-ink-muted">Account ID</span>
        <input
          id="perm-account"
          type="number"
          min="1"
          [class]="field"
          class="w-40"
          [value]="accountId() ?? ''"
          (change)="open($any($event.target).value)"
      /></label>
      <span class="pb-3 text-sm text-ink-muted">or choose one from Accounts.</span>
    </div>

    <div class="mt-8">
      @if (accountId() === null) {
        <app-empty message="Enter an account ID, or use Manage access on the Accounts page." />
      } @else if (detail.isLoading() && !detail.value()) {
        <app-loading what="access" [rows]="4" />
      } @else if (notFound()) {
        <app-empty message="There's no account with that ID." />
      } @else if (detail.error()) {
        <app-error (retry)="detail.reload()" />
      } @else if (detail.value(); as d) {
        <h2 class="text-xl font-semibold">
          <app-swatch [accountId]="d.account_id" [label]="d.account_name + ' #' + d.account_id" />
        </h2>
        <p class="mt-1 text-sm text-ink-muted">
          {{ typeLabel[d.account_type] }} account, opened {{ dateShort(d.open_date)
          }}{{ d.close_date ? ', closed' : '' }}.
        </p>

        <div
          class="mt-4 overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface"
        >
          <table class="ledger w-full min-w-[44rem] text-[0.9375rem]">
            <caption class="sr-only">
              People with access to
              {{
                d.account_name
              }}
            </caption>
            <thead class="text-left text-sm text-ink-muted">
              <tr>
                <th scope="col" class="px-4 py-3 font-medium">Person</th>
                <th scope="col" class="px-4 py-3 font-medium">Type</th>
                <th scope="col" class="px-4 py-3 font-medium">Role</th>
                <th scope="col" class="px-4 py-3 font-medium">Granted</th>
                <th scope="col" class="px-4 py-3"><span class="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              @for (r of d.access; track r.access_id) {
                <tr class="border-t border-rule">
                  <th scope="row" class="px-4 py-3 text-left font-medium">
                    {{ r.name }}
                    <span class="text-sm font-normal text-ink-muted">{{ r.username }}</span>
                  </th>
                  <td class="px-4 py-3 capitalize">{{ r.person_type }}</td>
                  <td class="px-4 py-3">{{ roleLabel[r.role] }}</td>
                  <td class="px-4 py-3 text-sm text-ink-muted">
                    {{ dateShort(r.granted_at) }}{{ r.granted_by ? ' by ' + r.granted_by : '' }}
                  </td>
                  <td class="px-4 py-2 text-right whitespace-nowrap">
                    @if (confirming() === r.access_id) {
                      <button
                        type="button"
                        class="min-h-11 rounded-[var(--radius-control)] bg-loss px-3 text-sm font-medium text-paper"
                        (click)="revoke(r)"
                      >
                        Confirm revoke
                      </button>
                      <button
                        type="button"
                        class="min-h-11 px-3 text-sm text-ink-muted hover:text-ink"
                        (click)="confirming.set(null)"
                      >
                        Cancel
                      </button>
                    } @else {
                      <button
                        type="button"
                        class="min-h-11 rounded-[var(--radius-control)] px-3 text-sm text-loss hover:bg-surface-sunk"
                        (click)="confirming.set(r.access_id)"
                      >
                        Revoke
                      </button>
                    }
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>

        <form
          class="mt-6 grid gap-4 rounded-[var(--radius-panel)] border border-rule bg-surface p-5 sm:grid-cols-[1fr_14rem_auto] sm:items-end"
          (submit)="$event.preventDefault(); grant()"
        >
          <div>
            @if (person(); as p) {
              <p class="text-sm text-ink-muted">Grant access to</p>
              <p class="flex min-h-11 items-center gap-2">
                <span class="font-medium">{{ p.name }}</span>
                <span class="text-sm text-ink-muted">{{ p.person_type }} #{{ p.person_id }}</span>
                <button
                  type="button"
                  class="text-sm text-ink-muted underline"
                  (click)="person.set(null)"
                >
                  change
                </button>
              </p>
            } @else {
              <app-person-picker label="Grant access to" (picked)="pick($event)" />
            }
          </div>
          <label class="flex flex-col gap-1 text-sm"
            ><span class="text-ink-muted">Role</span>
            <select
              id="perm-role"
              [class]="field"
              [value]="role()"
              (change)="role.set($any($event.target).value)"
              [disabled]="!person()"
            >
              @for (r of roles(); track r) {
                <option [value]="r">{{ roleLabel[r] }}</option>
              }
            </select></label
          >
          <button
            type="submit"
            class="min-h-11 rounded-[var(--radius-control)] bg-ink px-5 font-medium text-paper hover:opacity-90 disabled:opacity-50"
            [disabled]="!person() || busy()"
          >
            Grant access
          </button>
        </form>
      }
      @if (message()) {
        <p class="mt-4 text-sm" [class.text-loss]="isError()" role="status">{{ message() }}</p>
      }
    </div>
  `,
})
export class AdminPermissions {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  readonly account = input<string>();
  protected readonly accountId = computed(() => accountParam(this.account()));
  protected readonly field = FIELD;
  protected readonly typeLabel = accountTypeLabel;
  protected readonly roleLabel = ROLE_LABEL;
  protected readonly dateShort = dateShort;

  protected readonly detail = rxResource({
    params: () => ({ id: this.accountId() }),
    stream: ({ params }) => (params.id === null ? of(null) : this.api.accountAccess(params.id)),
  });
  protected readonly notFound = computed(() => isNotFound(this.detail.error()));

  protected readonly person = signal<Person | null>(null);
  protected readonly role = signal('advisor');
  protected readonly roles = computed(() =>
    this.person()?.person_type === 'client'
      ? ['owner', 'joint_owner', 'viewer']
      : ['advisor', 'viewer'],
  );
  protected readonly confirming = signal<number | null>(null);
  protected readonly busy = signal(false);
  protected readonly message = signal('');
  protected readonly isError = signal(false);

  protected open(value: string): void {
    this.message.set('');
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { account: value || null },
    });
  }

  protected pick(p: Person): void {
    this.person.set(p);
    this.role.set(p.person_type === 'client' ? 'viewer' : 'advisor');
  }

  protected grant(): void {
    const p = this.person();
    const id = this.accountId();
    if (!p || id === null) return;
    this.busy.set(true);
    this.api
      .grant({
        account_id: id,
        person_type: p.person_type,
        person_id: p.person_id,
        role: this.role(),
      })
      .subscribe({
        next: () =>
          this.done(`Granted ${p.name} ${ROLE_LABEL[this.role()].toLowerCase()} access.`, false),
        error: (err) => this.done(apiError(err), true),
      });
  }

  protected revoke(r: AccessRow): void {
    this.busy.set(true);
    this.api.revoke(r.access_id).subscribe({
      next: () => this.done(`Revoked ${r.name}'s access.`, false),
      error: (err) => this.done(apiError(err), true),
    });
  }

  private done(text: string, error: boolean): void {
    this.busy.set(false);
    this.confirming.set(null);
    this.message.set(text);
    this.isError.set(error);
    if (!error) {
      this.person.set(null);
      this.detail.reload();
    }
  }
}
