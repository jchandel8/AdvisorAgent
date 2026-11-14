import { Injectable, inject, signal } from '@angular/core';
import { Api } from './api';

/** How many shared documents wait for the signed-in advisor or client: the number on the Documents menu. */
@Injectable({ providedIn: 'root' })
export class DocCount {
  private readonly api = inject(Api);
  readonly count = signal(0);

  refresh(): void {
    this.api.documentsNewCount().subscribe({
      next: (r) => this.count.set(r.new_count),
      error: () => this.count.set(0), // a missing number is never worth an error message
    });
  }
}
