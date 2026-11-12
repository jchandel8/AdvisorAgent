import { provideHttpClient, withInterceptors } from '@angular/common/http';
import {
  ApplicationConfig,
  inject,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
  provideZonelessChangeDetection,
} from '@angular/core';
import { provideRouter, withComponentInputBinding, withInMemoryScrolling } from '@angular/router';
import { provideEchartsCore } from 'ngx-echarts';
import { routes } from './app.routes';
import { Auth } from './core/auth';
import { sessionInterceptor } from './core/session';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideZonelessChangeDetection(),
    // Learn the sign-in mode (demo or Cognito) and restore a Cognito session before the first route.
    provideAppInitializer(() => inject(Auth).init()),
    provideRouter(
      routes,
      withComponentInputBinding(),
      withInMemoryScrolling({ scrollPositionRestoration: 'top' }),
    ),
    provideHttpClient(withInterceptors([sessionInterceptor])),
    // ECharts is loaded on demand, the first time a chart is shown.
    provideEchartsCore({ echarts: () => import('./shared/echarts-setup').then((m) => m.default) }),
  ],
};
