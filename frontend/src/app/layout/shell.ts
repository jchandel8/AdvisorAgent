import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { map } from 'rxjs';
import { Session } from '../core/session';
import { Theme } from '../core/theme';
import { Icon, IconName } from '../shared/ui';

export interface NavItem {
  path: string;
  label: string;
  icon: IconName;
}

export interface ShellData {
  portal: 'advisor' | 'client';
  title: string;
  nav: NavItem[];
}

/**
 * App frame for one portal. The rail's color band names the portal, so in a side-by-side demo the
 * advisor window (evergreen) and the client window (ink blue) are told apart at a glance.
 */
@Component({
  selector: 'app-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <a
      href="#main"
      class="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2"
      >Skip to content</a
    >
    <div class="min-h-dvh lg:grid lg:grid-cols-[15rem_1fr]">
      <!-- Rail (desktop) / top band (phone) -->
      <header class="lg:sticky lg:top-0 lg:flex lg:h-dvh lg:flex-col lg:border-r lg:border-rule lg:bg-surface">
        <div class="px-5 py-4 text-paper" [class.bg-advisor]="isAdvisor()" [class.bg-client]="!isAdvisor()">
          <p class="text-lg leading-tight font-semibold">{{ data().title }}</p>
          <p class="text-sm opacity-85">AdvisorAgent</p>
        </div>

        <nav class="hidden flex-1 px-3 py-4 lg:block" [attr.aria-label]="data().title">
          <ul class="space-y-1">
            @for (item of data().nav; track item.path) {
              <li>
                <a
                  [routerLink]="item.path"
                  routerLinkActive
                  #rla="routerLinkActive"
                  [attr.aria-current]="rla.isActive ? 'page' : null"
                  class="flex min-h-11 items-center gap-3 rounded-[var(--radius-control)] px-3 text-ink-muted transition-colors duration-150 hover:bg-surface-sunk hover:text-ink"
                  [class.font-semibold]="rla.isActive"
                  [class.text-ink]="rla.isActive"
                  [class.bg-advisor-soft]="rla.isActive && isAdvisor()"
                  [class.bg-client-soft]="rla.isActive && !isAdvisor()"
                >
                  <app-icon [name]="item.icon" />
                  {{ item.label }}
                </a>
              </li>
            }
          </ul>
        </nav>

        <div class="flex items-center justify-between gap-2 border-b border-rule bg-surface px-5 py-2 lg:block lg:space-y-2 lg:border-t lg:border-b-0 lg:py-4">
          <p class="min-w-0 truncate text-sm">
            <span class="text-ink-muted">Signed in as</span>
            <span class="font-medium"> {{ user()?.name }}</span>
          </p>
          <div class="flex items-center gap-1">
            <button
              type="button"
              class="inline-flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-[var(--radius-control)] px-2 text-sm text-ink-muted hover:bg-surface-sunk hover:text-ink"
              (click)="switchUser()"
            >
              <app-icon name="switch" />
              <span class="hidden sm:inline">Switch user</span>
            </button>
            <button
              type="button"
              class="inline-flex min-h-11 min-w-11 items-center justify-center rounded-[var(--radius-control)] text-ink-muted hover:bg-surface-sunk hover:text-ink"
              [attr.aria-label]="theme.current() === 'dark' ? 'Use light theme' : 'Use dark theme'"
              (click)="theme.toggle()"
            >
              <app-icon [name]="theme.current() === 'dark' ? 'sun' : 'moon'" />
            </button>
          </div>
        </div>
      </header>

      <main id="main" class="mx-auto w-full max-w-[1200px] px-4 pt-6 pb-28 sm:px-8 lg:pt-10 lg:pb-12">
        <router-outlet />
      </main>
    </div>

    <!-- Bottom tabs (phone and tablet) -->
    <nav class="fixed inset-x-0 bottom-0 z-10 border-t border-rule bg-surface lg:hidden" [attr.aria-label]="data().title">
      <ul class="mx-auto flex max-w-xl justify-around">
        @for (item of data().nav; track item.path) {
          <li class="flex-1">
            <a
              [routerLink]="item.path"
              routerLinkActive
              #rla="routerLinkActive"
              [attr.aria-current]="rla.isActive ? 'page' : null"
              class="flex min-h-14 flex-col items-center justify-center gap-0.5 text-xs text-ink-muted"
              [class.text-advisor]="rla.isActive && isAdvisor()"
              [class.text-client]="rla.isActive && !isAdvisor()"
              [class.font-semibold]="rla.isActive"
            >
              <app-icon [name]="item.icon" [size]="20" />
              {{ item.label }}
            </a>
          </li>
        }
      </ul>
    </nav>
  `,
})
export class Shell {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly session = inject(Session);
  protected readonly theme = inject(Theme);

  protected readonly data = toSignal(this.route.data.pipe(map((d) => d as ShellData)), {
    initialValue: this.route.snapshot.data as ShellData,
  });
  protected readonly isAdvisor = computed(() => this.data().portal === 'advisor');
  protected readonly user = this.session.user;

  protected switchUser(): void {
    this.session.signOut();
    void this.router.navigateByUrl('/demo');
  }
}
