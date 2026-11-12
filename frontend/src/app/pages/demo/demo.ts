import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { Api } from '../../core/api';
import { Auth } from '../../core/auth';
import { DemoUser } from '../../core/models';
import { Session } from '../../core/session';
import { Theme } from '../../core/theme';
import { Empty, ErrorState, Icon, Loading } from '../../shared/ui';

/** Local demo sign-in: choose who this window is. Replaced by Cognito login in build step 3. */
@Component({
  selector: 'app-demo',
  imports: [Icon, Loading, ErrorState, Empty],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <main id="main" class="mx-auto max-w-4xl px-4 py-10 sm:px-8 sm:py-16">
      <div class="flex items-start justify-between gap-4">
        <div class="space-y-3">
          <h1 class="text-[1.75rem] font-semibold sm:text-[2.5rem]">
            {{ picker() ? 'Choose who you are in this window' : 'Demo users' }}
          </h1>
          <p class="max-w-[62ch] text-ink-muted">
            Open the advisor in this window and a client in a private window to see the same
            accounts from both sides. Each person sees only the accounts they've been given access
            to.
            @if (!picker()) {
              Sign in with one of these usernames and the demo password the project owner shared
              with you.
            }
          </p>
          @if (!picker()) {
            <a
              href="/login"
              class="inline-flex min-h-11 items-center rounded-[var(--radius-control)] bg-ink px-5 font-semibold text-paper hover:opacity-90"
              >Sign in</a
            >
          }
        </div>
        <button
          type="button"
          class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-[var(--radius-control)] text-ink-muted hover:bg-surface-sunk"
          [attr.aria-label]="theme.current() === 'dark' ? 'Use light theme' : 'Use dark theme'"
          (click)="theme.toggle()"
        >
          <app-icon [name]="theme.current() === 'dark' ? 'sun' : 'moon'" />
        </button>
      </div>

      <section class="mt-10" aria-labelledby="demo-users">
        <h2 id="demo-users" class="sr-only">Demo users</h2>
        @if (users.isLoading()) {
          <app-loading what="demo users" [rows]="5" />
        } @else if (users.error()) {
          <app-error
            message="The demo user list didn't load. Start the stack with docker compose up, then try again."
            (retry)="users.reload()"
          />
        } @else if (!(users.value()?.users ?? []).length) {
          <app-empty
            message="No demo users yet. Load the seed data with python -m wealth.datagen."
          />
        } @else {
          <div class="grid gap-8 md:grid-cols-2 lg:grid-cols-3">
            @for (group of groups(); track group.title) {
              <div>
                <h3 class="mb-3 flex items-center gap-2 font-semibold">
                  <span
                    class="inline-block h-4 w-1.5 rounded-[2px]"
                    [class.bg-advisor]="group.kind === 'advisor'"
                    [class.bg-client]="group.kind === 'client'"
                    [class.bg-admin]="group.kind === 'admin'"
                    aria-hidden="true"
                  ></span>
                  {{ group.title }}
                </h3>
                <ul
                  class="divide-y divide-rule overflow-hidden rounded-[var(--radius-panel)] border border-rule bg-surface"
                >
                  @for (u of group.users; track u.kind + u.id) {
                    <li>
                      @if (picker()) {
                        <button
                          type="button"
                          class="w-full px-5 py-4 text-left transition-colors duration-150 hover:bg-surface-sunk"
                          (click)="choose(u)"
                        >
                          <span class="block font-semibold">{{ u.name }}</span>
                          <span class="mt-0.5 block text-sm text-ink-muted">{{ describe(u) }}</span>
                          <span class="mt-2 block text-sm">{{ u.note }}</span>
                        </button>
                      } @else {
                        <div class="px-5 py-4">
                          <span class="block font-semibold">{{ u.name }}</span>
                          <span class="mt-0.5 block text-sm"
                            >Username <strong class="font-semibold">{{ u.username }}</strong></span
                          >
                          <span class="mt-0.5 block text-sm text-ink-muted">{{ describe(u) }}</span>
                          <span class="mt-2 block text-sm">{{ u.note }}</span>
                        </div>
                      }
                    </li>
                  }
                </ul>
              </div>
            }
          </div>
        }
      </section>

      <p class="mt-10 flex max-w-[62ch] items-start gap-2 text-sm text-ink-muted">
        <app-icon name="shield" class="mt-0.5" />
        @if (picker()) {
          This picker exists only in local development. The API checks every request against the
          account access list, whatever this page sends.
        } @else {
          Every request is checked against the signed-in person and the account access list. The
          admin can grant or revoke access while you watch, and the portals reflect it on the next
          page load.
        }
      </p>
    </main>
  `,
})
export class Demo {
  private readonly api = inject(Api);
  private readonly session = inject(Session);
  private readonly router = inject(Router);
  protected readonly theme = inject(Theme);

  private readonly auth = inject(Auth);
  /** Demo mode: pick a person to sign in as. Cognito mode: show who to sign in as (never passwords). */
  protected readonly picker = computed(() => this.auth.mode() === 'demo');
  protected readonly users = rxResource({ stream: () => this.api.demoUsers() });
  protected readonly groups = computed(() => {
    const all = this.users.value()?.users ?? [];
    return [
      { kind: 'advisor', title: 'Advisors', users: all.filter((u) => u.kind === 'advisor') },
      { kind: 'client', title: 'Clients', users: all.filter((u) => u.kind === 'client') },
      { kind: 'admin', title: 'Admin', users: all.filter((u) => u.kind === 'admin') },
    ].filter((g) => g.users.length);
  });

  protected describe(u: DemoUser): string {
    if (u.kind === 'admin') return 'Manages users, accounts and access';
    return u.kind === 'advisor'
      ? `${u.client_count} clients, ${u.account_count} accounts`
      : `${u.account_count} ${u.account_count === 1 ? 'account' : 'accounts'}`;
  }

  protected choose(u: DemoUser): void {
    this.session.signIn({ kind: u.kind, id: u.id, name: u.name });
    void this.router.navigateByUrl(`/${u.kind}`);
  }
}
