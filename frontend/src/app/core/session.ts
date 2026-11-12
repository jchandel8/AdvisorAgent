import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';
import { Auth } from './auth';
import { PersonKind } from './models';

export interface SessionUser {
  kind: PersonKind;
  id: number;
  name: string;
}

const KEY = 'advisoragent.demoUser';

/**
 * Who this browser window is signed in as, for showing the right portal. This is NOT security: the
 * backend checks the user and the account access on every request.
 * - demo mode: the picked demo user, kept in localStorage so a normal and a private window can differ.
 * - cognito mode: filled from /api/me after sign-in, kept in memory only (the token is the source).
 */
@Injectable({ providedIn: 'root' })
export class Session {
  private readonly current = signal<SessionUser | null>(this.read());
  readonly user = this.current.asReadonly();
  readonly signedIn = computed(() => this.current() !== null);

  signIn(user: SessionUser, opts: { persist?: boolean } = {}): void {
    this.current.set(user);
    if (opts.persist === false) return;
    try {
      localStorage.setItem(KEY, JSON.stringify(user));
    } catch {
      /* storage blocked: the session lasts until reload */
    }
  }

  signOut(): void {
    this.current.set(null);
    try {
      localStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
  }

  header(): string | null {
    const u = this.current();
    return u ? `${u.kind}:${u.id}` : null;
  }

  private read(): SessionUser | null {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return null;
      const u = JSON.parse(raw) as Partial<SessionUser>;
      if (
        (u.kind === 'advisor' || u.kind === 'client' || u.kind === 'admin') &&
        Number.isInteger(u.id) &&
        typeof u.name === 'string'
      ) {
        return { kind: u.kind, id: u.id as number, name: u.name };
      }
    } catch {
      /* ignore bad or blocked storage */
    }
    return null;
  }
}

/** Where to send someone who isn't signed in: the demo picker locally, the sign-in page with Cognito. */
export function signInPath(auth: Auth): string {
  return auth.mode() === 'cognito' ? '/login' : '/demo';
}

/**
 * Adds identity to API calls: the Cognito access token as a Bearer token, or the demo header locally.
 * A 401 means the sign-in is gone or invalid, so the user goes back to sign in.
 */
export const sessionInterceptor: HttpInterceptorFn = (req, next) => {
  const session = inject(Session);
  const auth = inject(Auth);
  const router = inject(Router);
  let outgoing = req;
  if (req.url.startsWith('/api/')) {
    if (auth.mode() === 'cognito') {
      const token = auth.accessToken();
      if (token) outgoing = req.clone({ setHeaders: { Authorization: `Bearer ${token}` } });
    } else {
      const header = session.header();
      if (header) outgoing = req.clone({ setHeaders: { 'X-Demo-User': header } });
    }
  }
  return next(outgoing).pipe(
    catchError((err: unknown) => {
      if (err instanceof HttpErrorResponse && err.status === 401 && req.url !== '/api/demo/users') {
        void auth.clear().then(() => router.navigateByUrl(signInPath(auth)));
      }
      return throwError(() => err);
    }),
  );
};

/** Opens a portal only for the matching kind of user. The backend enforces the same rule. */
export function portalGuard(kind: PersonKind): CanActivateFn {
  return () => {
    const user = inject(Session).user();
    if (user?.kind === kind) return true;
    // Signed in to the other portal: go to your own. Not signed in: go to sign-in.
    return inject(Router).parseUrl(user ? `/${user.kind}` : signInPath(inject(Auth)));
  };
}

/** The demo picker exists only in demo mode. */
export const demoModeGuard: CanActivateFn = () =>
  inject(Auth).mode() === 'demo' ? true : inject(Router).parseUrl('/login');
