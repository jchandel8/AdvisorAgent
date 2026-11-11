import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

/** Temporary placeholder for screens built after the design checkpoint. */
@Component({
  selector: 'app-coming-next',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h1 class="text-[1.75rem] font-semibold">{{ title }}</h1>
    <p class="mt-2 text-ink-muted">This screen is built next, after the design direction is approved.</p>
  `,
})
export class ComingNext {
  protected readonly title = (inject(ActivatedRoute).snapshot.data['title'] as string) ?? 'Coming next';
}
