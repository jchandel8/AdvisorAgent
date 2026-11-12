import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Auth } from '../core/auth';
import { Session } from '../core/session';
import { Theme } from '../core/theme';
import { Icon } from '../shared/ui';

/** Sign-in page (Cognito mode). The password is entered on Cognito's own page, never in this app. */
@Component({
  selector: 'app-login',
  imports: [Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <main id="main" class="mx-auto grid min-h-dvh max-w-xl content-center gap-8 px-4 py-12 sm:px-8">
      <div class="flex items-start justify-between gap-4">
        <div class="space-y-3">
          <h1 class="text-[2rem] font-semibold">AdvisorAgent</h1>
          <p class="max-w-[52ch] text-ink-muted">
            Advisors see their clients and ask the assistant. Clients see their own accounts. You'll
            sign in on the secure Amazon Cognito page and come straight back.
          </p>
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

      <div class="space-y-4 rounded-[var(--radius-panel)] border border-rule bg-surface p-6">
        <button
          type="button"
          class="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-[var(--radius-control)] bg-ink px-5 font-semibold text-paper hover:opacity-90 disabled:opacity-60"
          [disabled]="busy()"
          (click)="signIn()"
        >
          <app-icon name="shield" /> {{ busy() ? 'Opening sign-in…' : 'Sign in' }}
        </button>
        @if (error()) {
          <p class="text-sm text-loss" role="alert">{{ error() }}</p>
        }
        <p class="text-sm text-ink-muted">
          Demo viewers: use the username and password the project owner shared with you. Advisors
          and clients open different portals automatically.
        </p>
      </div>
    </main>
  `,
})
export class Login implements OnInit {
  private readonly auth = inject(Auth);
  private readonly router = inject(Router);
  private readonly session = inject(Session);
  protected readonly theme = inject(Theme);

  protected readonly busy = signal(false);
  protected readonly error = signal('');

  ngOnInit(): void {
    const user = this.session.user();
    if (user) void this.router.navigateByUrl(`/${user.kind}`);
  }

  protected async signIn(): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    try {
      await this.auth.login();
    } catch {
      this.busy.set(false);
      this.error.set("Sign-in couldn't start. Check your connection and try again.");
    }
  }
}

/** Cognito redirects back here with a one-time code; exchange it, then open the right portal. */
@Component({
  selector: 'app-auth-callback',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <main
      id="main"
      class="mx-auto grid min-h-dvh max-w-xl content-center gap-4 px-4 sm:px-8"
      aria-live="polite"
    >
      @if (error()) {
        <h1 class="text-xl font-semibold">Sign-in didn't complete</h1>
        <p class="text-ink-muted">{{ error() }}</p>
        <a class="font-medium underline" href="/login">Back to sign-in</a>
      } @else {
        <p class="text-ink-muted">Signing you in…</p>
      }
    </main>
  `,
})
export class AuthCallback implements OnInit {
  private readonly auth = inject(Auth);
  private readonly router = inject(Router);
  protected readonly error = signal('');

  async ngOnInit(): Promise<void> {
    try {
      const portal = await this.auth.completeLogin();
      await this.router.navigateByUrl(portal, { replaceUrl: true });
    } catch {
      await this.auth.clear();
      this.error.set(
        "Your account isn't set up for this app yet, or the sign-in link expired. Ask the project owner for access, then try again.",
      );
    }
  }
}
