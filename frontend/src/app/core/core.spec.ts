import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { Router, provideRouter } from '@angular/router';
import { Auth } from './auth';
import { dateLong, money, percent, swatchSlot } from './format';
import { Session, sessionInterceptor } from './session';

describe('Session', () => {
  beforeEach(() => localStorage.clear());

  it('ignores tampered or malformed stored users', () => {
    localStorage.setItem(
      'advisoragent.demoUser',
      JSON.stringify({ kind: 'admin', id: 1, name: 'x' }),
    );
    expect(TestBed.inject(Session).user()).toBeNull();
  });

  it('round-trips a signed-in user and builds the demo header', () => {
    const session = TestBed.inject(Session);
    session.signIn({ kind: 'client', id: 63, name: 'Shelby Moody' });
    expect(session.header()).toBe('client:63');
    expect(JSON.parse(localStorage.getItem('advisoragent.demoUser')!).id).toBe(63);
    session.signOut();
    expect(session.header()).toBeNull();
  });
});

describe('sessionInterceptor', () => {
  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([{ path: 'demo', children: [] }]), // the 401 handler navigates here
        provideHttpClient(withInterceptors([sessionInterceptor])),
        provideHttpClientTesting(),
      ],
    });
  });

  it('adds the demo header to API calls only', () => {
    TestBed.inject(Session).signIn({ kind: 'advisor', id: 2, name: 'Anthony Gonzalez' });
    const http = TestBed.inject(HttpClient);
    const ctl = TestBed.inject(HttpTestingController);

    http.get('/api/me').subscribe();
    http.get('https://example.com/other').subscribe();

    expect(ctl.expectOne('/api/me').request.headers.get('X-Demo-User')).toBe('advisor:2');
    expect(ctl.expectOne('https://example.com/other').request.headers.has('X-Demo-User')).toBe(
      false,
    );
    ctl.verify();
  });

  it('signs out on 401', () => {
    const session = TestBed.inject(Session);
    session.signIn({ kind: 'client', id: 63, name: 'Shelby Moody' });
    TestBed.inject(HttpClient)
      .get('/api/client/accounts')
      .subscribe({ error: () => undefined });
    TestBed.inject(HttpTestingController)
      .expectOne('/api/client/accounts')
      .flush({}, { status: 401, statusText: 'Unauthorized' });
    expect(session.user()).toBeNull();
  });
});

describe('format', () => {
  it('keeps an account on the same swatch everywhere', () => {
    expect(swatchSlot(118)).toBe(swatchSlot(118));
    expect(swatchSlot(118)).toBe(118 % 8);
  });

  it('formats money, percents and dates without time-zone drift', () => {
    expect(money(1234.5)).toBe('$1,234.50');
    expect(money(null)).toBe('—');
    expect(percent(12.345)).toBe('12.3%');
    expect(dateLong('2026-11-11')).toBe('November 11, 2026');
  });
});

describe('sessionInterceptor in cognito mode', () => {
  const fakeAuth = {
    mode: signal<'demo' | 'cognito'>('cognito'),
    accessToken: () => 'header.payload.signature',
    clear: () => Promise.resolve(),
  };

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([{ path: 'login', children: [] }]),
        provideHttpClient(withInterceptors([sessionInterceptor])),
        provideHttpClientTesting(),
        { provide: Auth, useValue: fakeAuth },
      ],
    });
  });

  it('sends the access token as a Bearer token and never the demo header', () => {
    TestBed.inject(Session).signIn({ kind: 'advisor', id: 2, name: 'Anthony Gonzalez' });
    const http = TestBed.inject(HttpClient);
    const ctl = TestBed.inject(HttpTestingController);
    http.get('/api/me').subscribe();
    http.get('https://example.com/other').subscribe();
    const api = ctl.expectOne('/api/me').request.headers;
    expect(api.get('Authorization')).toBe('Bearer header.payload.signature');
    expect(api.has('X-Demo-User')).toBe(false);
    expect(ctl.expectOne('https://example.com/other').request.headers.has('Authorization')).toBe(
      false,
    );
    ctl.verify();
  });

  it('goes to /login on 401', async () => {
    const router = TestBed.inject(Router);
    const nav = vi.spyOn(router, 'navigateByUrl');
    TestBed.inject(HttpClient)
      .get('/api/client/accounts')
      .subscribe({ error: () => undefined });
    TestBed.inject(HttpTestingController)
      .expectOne('/api/client/accounts')
      .flush({}, { status: 401, statusText: 'Unauthorized' });
    await Promise.resolve();
    await Promise.resolve();
    expect(nav).toHaveBeenCalledWith('/login');
  });
});
