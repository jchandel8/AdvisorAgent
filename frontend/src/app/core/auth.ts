import { Injectable, inject, signal } from '@angular/core';
import { UserManager, User } from 'oidc-client-ts';
import { Me } from './models';
import { Session } from './session';

export type AuthMode = 'demo' | 'cognito';

interface AuthConfig {
  mode: AuthMode;
  authority?: string;
  client_id?: string;
  domain?: string;
}

/**
 * Sign-in. The API says which mode is active (GET /api/auth/config), so one build works everywhere:
 * - demo: the local-only user picker (the backend refuses it on AWS).
 * - cognito: OAuth 2.0 authorization code flow with PKCE through Cognito's hosted sign-in page. The app
 *   never sees a password; it gets an access token and sends it as a Bearer token. Who you are and which
 *   portal you may open come from /api/me, which the backend derives from the verified token.
 */
@Injectable({ providedIn: 'root' })
export class Auth {
  private readonly session = inject(Session);
  private manager: UserManager | null = null;
  private config: AuthConfig = { mode: 'demo' };
  private user: User | null = null;

  readonly mode = signal<AuthMode>('demo');
  readonly ready = signal(false);

  /** Runs once before the first route (app initializer). Never throws: a failure leaves demo mode off. */
  async init(): Promise<void> {
    try {
      const res = await fetch('/api/auth/config');
      this.config = (await res.json()) as AuthConfig;
    } catch {
      this.config = { mode: 'cognito' }; // fail closed: no demo picker if the API can't be reached
    }
    this.mode.set(this.config.mode);
    if (this.config.mode === 'cognito' && this.config.authority && this.config.client_id) {
      this.session.signOut(); // never trust a stored demo identity in cognito mode
      this.manager = new UserManager({
        authority: this.config.authority,
        client_id: this.config.client_id,
        redirect_uri: `${location.origin}/auth/callback`,
        post_logout_redirect_uri: `${location.origin}/login`,
        response_type: 'code',
        scope: 'openid email profile',
        automaticSilentRenew: true,
      });
      this.manager.events.addUserLoaded((u) => {
        this.user = u;
      });
      this.manager.events.addUserUnloaded(() => {
        this.user = null;
      });
      const existing = await this.manager.getUser();
      if (existing && !existing.expired) {
        this.user = existing;
        await this.loadMe().catch(() => this.clear());
      }
    }
    this.ready.set(true);
  }

  accessToken(): string | null {
    return this.user && !this.user.expired ? this.user.access_token : null;
  }

  /** Sends the browser to Cognito's sign-in page. */
  async login(): Promise<void> {
    if (!this.manager) throw new Error('Sign-in is not configured.');
    await this.manager.signinRedirect();
  }

  /** Completes the redirect back from Cognito; returns the portal to open. */
  async completeLogin(): Promise<string> {
    if (!this.manager) throw new Error('Sign-in is not configured.');
    this.user = await this.manager.signinRedirectCallback();
    const me = await this.loadMe();
    return me.portal;
  }

  /** Signs out of the app and of Cognito's hosted session, then returns to /login. */
  async logout(): Promise<void> {
    await this.clear();
    if (this.config.domain && this.config.client_id) {
      const back = encodeURIComponent(`${location.origin}/login`);
      location.assign(
        `https://${this.config.domain}/logout?client_id=${this.config.client_id}&logout_uri=${back}`,
      );
    } else {
      location.assign('/login');
    }
  }

  async clear(): Promise<void> {
    this.user = null;
    this.session.signOut();
    await this.manager?.removeUser().catch(() => undefined);
  }

  private async loadMe(): Promise<Me> {
    const token = this.accessToken();
    const res = await fetch('/api/me', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`Sign-in was not accepted (${res.status}).`);
    const me = (await res.json()) as Me;
    if (me.kind === 'advisor' || me.kind === 'client') {
      this.session.signIn({ kind: me.kind, id: me.id, name: me.name }, { persist: false });
    }
    return me;
  }
}
