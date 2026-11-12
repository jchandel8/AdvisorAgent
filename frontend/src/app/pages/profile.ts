import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { Observable } from 'rxjs';
import { Api } from '../core/api';
import { AdvisorProfile, ClientProfile } from '../core/models';
import { Session } from '../core/session';
import { Fields } from '../shared/filters';
import { ErrorState, Loading } from '../shared/ui';

/** Read-only profile for whichever portal is open. Editing arrives with the admin portal (build step 4). */
@Component({
  selector: 'app-profile',
  imports: [Fields, Loading, ErrorState],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="max-w-[62ch] space-y-2">
      <h1 class="text-[1.75rem] font-semibold">Profile</h1>
      <p class="text-ink-muted">To change these details, contact your firm's administrator.</p>
    </header>
    <div class="mt-8 max-w-3xl">
      @if (profile.isLoading()) {
        <app-loading what="your profile" [rows]="6" />
      } @else if (profile.error()) {
        <app-error (retry)="profile.reload()" />
      } @else {
        <app-fields [fields]="fields()" />
      }
    </div>
  `,
})
export class Profile {
  private readonly api = inject(Api);
  private readonly kind = inject(Session).user()?.kind ?? 'client';

  protected readonly profile = rxResource<AdvisorProfile | ClientProfile, void>({
    stream: (): Observable<AdvisorProfile | ClientProfile> =>
      this.kind === 'advisor' ? this.api.advisorProfile() : this.api.clientProfile(),
  });

  protected readonly fields = computed(() => {
    const p = this.profile.value();
    if (!p) return [];
    const common = [
      { label: 'Username', value: p.username },
      { label: 'First name', value: p.first_name },
      { label: 'Last name', value: p.last_name },
      { label: 'Email', value: p.email },
      { label: 'Phone', value: p.phone },
    ];
    if ('certifications' in p) {
      return [
        ...common,
        { label: 'Certifications', value: p.certifications.join(', ') },
        { label: 'City', value: p.city },
        { label: 'State', value: p.state },
      ];
    }
    return [
      ...common,
      { label: 'Address', value: [p.address, p.city, p.state].filter(Boolean).join(', ') },
    ];
  });
}
