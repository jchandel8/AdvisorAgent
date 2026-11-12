import { Injectable, signal } from '@angular/core';

export type ThemeName = 'light' | 'dark';
const KEY = 'advisoragent.theme';

/** Light by default; the dark choice is remembered per browser. index.html applies it before first paint. */
@Injectable({ providedIn: 'root' })
export class Theme {
  readonly current = signal<ThemeName>(
    document.documentElement.dataset['theme'] === 'dark' ? 'dark' : 'light',
  );

  toggle(): void {
    const next: ThemeName = this.current() === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset['theme'] = next;
    this.current.set(next);
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* storage blocked: the choice lasts until reload */
    }
  }

  /** Current value of a CSS custom property, for libraries (ECharts) that need concrete colors. */
  token(name: string): string {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
}
