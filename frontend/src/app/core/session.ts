import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';
import { PersonKind } from './models';

export interface SessionUser {
  kind: PersonKind;
  id: number;
  name: string;
}

const KEY = 'advisoragent.demoUser';

/**
 * Which demo user this browser window is signed in as (local stand-in for Cognito, build step 3).
 * Stored in localStorage, so a normal window and a private window can be different users side by side.
 * This is NOT security: the backend checks the user and the account access on every request.
 */
@Injectable({ providedIn: 'root' })
export class Session {
  private readonly current = signal<SessionUser | null>(this.read());
  readonly user = this.current.asReadonly();
  readonly signedIn = computed(() => this.current() !== null);

  signIn(user: SessionUser): void {
    this.current.set(user);
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
      if ((u.kind === 'advisor' || u.kind === 'client') && Number.isInteger(u.id) && typeof u.name === 'string') {
        return { kind: u.kind, id: u.id as number, name: u.name };
      }
    } catch {
      /* ignore bad or blocked storage */
    }
    return null;
  }
}

/** Adds the demo identity header to API calls; a 401 means the user is gone, so go back to the picker. */
export const sessionInterceptor: HttpInterceptorFn = (req, next) => {
  const session = inject(Session);
  const router = inject(Router);
  const header = session.header();
  const withUser = header && req.url.startsWith('/api/') ? req.clone({ setHeaders: { 'X-Demo-User': header } }) : req;
  return next(withUser).pipe(
    catchError((err: unknown) => {
      if (err instanceof HttpErrorResponse && err.status === 401 && req.url !== '/api/demo/users') {
        session.signOut();
        void router.navigateByUrl('/demo');
      }
      return throwError(() => err);
    }),
  );
};

/** Opens a portal only for the matching kind of user. The backend enforces the same rule. */
export function portalGuard(kind: PersonKind): CanActivateFn {
  return () => {
    const user = inject(Session).user();
    return user?.kind === kind ? true : inject(Router).parseUrl('/demo');
  };
}
