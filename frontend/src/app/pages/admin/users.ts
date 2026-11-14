import { ChangeDetectionStrategy, Component, OnInit, inject, input, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { Api } from '../../core/api';
import { NewUser } from '../../core/models';
import { FIELD, apiError } from '../../shared/person-picker';
import { Empty, ErrorState, Icon, Loading } from '../../shared/ui';

type Kind = 'advisor' | 'client' | 'admin';

@Component({
  selector: 'app-admin-users',
  imports: [RouterLink, Icon, Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="flex flex-wrap items-end justify-between gap-4">
      <div class="space-y-1">
        <h1 class="text-[1.75rem] font-semibold">Users</h1>
        <p class="max-w-[62ch] text-ink-muted">
          Creating a user adds them to AdvisorAgent and, with Cognito sign-in on, creates their
          login in the right group. They see nothing until you grant access to accounts.
        </p>
      </div>
      <button
        type="button"
        class="inline-flex min-h-11 items-center gap-2 rounded-[var(--radius-control)] bg-admin px-4 font-medium text-paper hover:opacity-90"
        (click)="showForm.set(!showForm())"
        [attr.aria-expanded]="showForm()"
      >
        <app-icon name="user" /> {{ showForm() ? 'Close' : 'Create user' }}
      </button>
    </header>

    @if (showForm()) {
      <form
        class="mt-6 grid gap-4 rounded-[var(--radius-panel)] border border-rule bg-surface p-5 sm:grid-cols-2"
        (submit)="$event.preventDefault(); create()"
      >
        <fieldset class="sm:col-span-2">
          <legend class="mb-2 text-sm text-ink-muted">Type</legend>
          <div class="flex gap-2">
            @for (k of ['advisor', 'client']; track k) {
              <label
                class="inline-flex min-h-11 items-center gap-2 rounded-full border px-4"
                [class.border-ink]="form.kind === k"
                [class.border-rule-strong]="form.kind !== k"
              >
                <input
                  type="radio"
                  name="kind"
                  [value]="k"
                  [checked]="form.kind === k"
                  (change)="form.kind = $any(k)"
                />
                {{ k === 'advisor' ? 'Advisor' : 'Client' }}
              </label>
            }
          </div>
        </fieldset>
        <label class="flex flex-col gap-1 text-sm"
          ><span class="text-ink-muted">First name</span>
          <input
            [class]="field"
            required
            [value]="form.first_name"
            (input)="form.first_name = $any($event.target).value"
            id="new-first"
        /></label>
        <label class="flex flex-col gap-1 text-sm"
          ><span class="text-ink-muted">Last name</span>
          <input
            [class]="field"
            required
            [value]="form.last_name"
            (input)="form.last_name = $any($event.target).value"
            id="new-last"
        /></label>
        <label class="flex flex-col gap-1 text-sm"
          ><span class="text-ink-muted">Email</span>
          <input
            type="email"
            [class]="field"
            required
            [value]="form.email"
            (input)="form.email = $any($event.target).value"
            id="new-email"
        /></label>
        <label class="flex flex-col gap-1 text-sm"
          ><span class="text-ink-muted">Username (optional)</span>
          <input
            [class]="field"
            placeholder="first.last"
            [value]="form.username ?? ''"
            (input)="form.username = $any($event.target).value || null"
            id="new-username"
        /></label>
        <label class="flex flex-col gap-1 text-sm"
          ><span class="text-ink-muted">Phone (optional)</span>
          <input
            [class]="field"
            [value]="form.phone ?? ''"
            (input)="form.phone = $any($event.target).value || null"
            id="new-phone"
        /></label>
        @if (form.kind === 'client') {
          <label class="flex flex-col gap-1 text-sm"
            ><span class="text-ink-muted">Risk profile</span>
            <select
              [class]="field"
              [value]="form.risk_profile"
              (change)="form.risk_profile = $any($event.target).value"
              id="new-risk"
            >
              <option value="conservative">Conservative</option>
              <option value="moderate">Moderate</option>
              <option value="growth">Growth</option>
              <option value="aggressive">Aggressive</option>
            </select></label
          >
        }
        <div class="flex flex-wrap items-center gap-3 sm:col-span-2">
          <button
            type="submit"
            class="min-h-11 rounded-[var(--radius-control)] bg-ink px-5 font-medium text-paper hover:opacity-90 disabled:opacity-60"
            [disabled]="saving()"
          >
            {{ saving() ? 'Creating…' : 'Create user' }}
          </button>
          @if (formError()) {
            <p class="text-sm text-loss" role="alert">{{ formError() }}</p>
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

    <section class="mt-8" aria-labelledby="list-title">
      <h2 id="list-title" class="sr-only">User list</h2>
      <div class="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div role="group" aria-label="User type" class="flex flex-wrap gap-2">
          @for (k of kinds; track k.value) {
            <button
              type="button"
              class="inline-flex min-h-11 items-center rounded-full border px-4 text-sm"
              [class]="
                kind() === k.value
                  ? 'border-ink bg-ink font-medium text-paper'
                  : 'border-rule-strong bg-surface hover:bg-surface-sunk'
              "
              [attr.aria-pressed]="kind() === k.value"
              (click)="kind.set(k.value)"
            >
              {{ k.label }}
            </button>
          }
        </div>
        <label class="flex flex-col gap-1 text-sm">
          <span class="text-ink-muted">Search</span>
          <input
            type="search"
            class="min-h-11 w-64 rounded-[var(--radius-control)] border border-rule-strong bg-surface px-3"
            placeholder="Name or username"
            (input)="query.set($any($event.target).value)"
          />
        </label>
      </div>

      @if (users.isLoading() && !users.value()) {
        <app-loading what="users" [rows]="6" />
      } @else if (users.error()) {
        <app-error (retry)="users.reload()" />
      } @else if (users.value(); as u) {
        @if (!u.users.length) {
          <app-empty message="No users match that search." />
        } @else {
          <div class="overflow-x-auto rounded-[var(--radius-panel)] border border-rule bg-surface">
            <table class="ledger w-full min-w-[40rem] text-[0.9375rem]">
              <caption class="sr-only">
                {{
                  kind()
                }}s
              </caption>
              <thead class="text-left text-sm text-ink-muted">
                <tr>
                  <th scope="col" class="px-4 py-3 font-medium">Name</th>
                  <th scope="col" class="px-4 py-3 font-medium">Username</th>
                  <th scope="col" class="px-4 py-3 font-medium">Email</th>
                  @if (kind() !== 'admin') {
                    <th scope="col" class="px-4 py-3 text-right font-medium">Accounts</th>
                  }
                  @if (kind() === 'advisor') {
                    <th scope="col" class="px-4 py-3 text-right font-medium">Clients</th>
                  }
                  @if (kind() === 'client') {
                    <th scope="col" class="px-4 py-3 font-medium">Risk profile</th>
                  }
                </tr>
              </thead>
              <tbody>
                @for (p of u.users; track p.id) {
                  <tr class="border-t border-rule">
                    <th scope="row" class="px-4 py-2 text-left font-medium">
                      <a
                        class="inline-flex min-h-11 items-center gap-2 hover:underline"
                        [routerLink]="['/admin/users', kind(), p.id]"
                        >{{ p.first_name }} {{ p.last_name }}
                        <span class="num text-sm font-normal text-ink-muted">#{{ p.id }}</span></a
                      >
                    </th>
                    <td class="px-4 py-3">{{ p.username }}</td>
                    <td class="px-4 py-3 text-ink-muted">{{ p.email }}</td>
                    @if (kind() !== 'admin') {
                      <td class="num px-4 py-3 text-right">{{ p.account_count }}</td>
                    }
                    @if (kind() === 'advisor') {
                      <td class="num px-4 py-3 text-right">{{ p.client_count }}</td>
                    }
                    @if (kind() === 'client') {
                      <td class="px-4 py-3 capitalize">{{ p.risk_profile }}</td>
                    }
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
export class AdminUsers implements OnInit {
  private readonly api = inject(Api);
  /** ?kind=advisor|client|admin (the "All users" link from a user page keeps the tab). */
  readonly kindParam = input<string>(undefined, { alias: 'kind' });
  protected readonly field = FIELD;
  protected readonly kinds: { value: Kind; label: string }[] = [
    { value: 'advisor', label: 'Advisors' },
    { value: 'client', label: 'Clients' },
    { value: 'admin', label: 'Admins' },
  ];
  protected readonly kind = signal<Kind>('advisor');
  protected readonly query = signal('');
  protected readonly users = rxResource({
    params: () => ({ kind: this.kind(), q: this.query() }),
    stream: ({ params }) => this.api.adminUsers(params.kind, params.q),
  });

  ngOnInit(): void {
    const k = this.kindParam();
    if (k === 'advisor' || k === 'client' || k === 'admin') this.kind.set(k);
  }

  protected readonly showForm = signal(false);
  protected readonly saving = signal(false);
  protected readonly formError = signal('');
  protected readonly created = signal('');
  protected form: NewUser = this.blank();

  private blank(): NewUser {
    return {
      kind: 'advisor',
      first_name: '',
      last_name: '',
      email: '',
      username: null,
      phone: null,
      risk_profile: 'moderate',
    };
  }

  protected create(): void {
    this.saving.set(true);
    this.formError.set('');
    const body: NewUser = { ...this.form };
    if (body.kind !== 'client') delete body.risk_profile;
    this.api.createUser(body).subscribe({
      next: (u) => {
        this.saving.set(false);
        this.showForm.set(false);
        this.created.set(
          `Created ${u.kind} ${u.name}, username ${u.username}. Grant them access to accounts on the Permissions page.`,
        );
        this.form = this.blank();
        this.kind.set(u.kind as Kind);
        this.users.reload();
      },
      error: (err) => {
        this.saving.set(false);
        this.formError.set(apiError(err));
      },
    });
  }
}
