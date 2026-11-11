import { inject } from '@angular/core';
import { Router, Routes } from '@angular/router';
import { Session, portalGuard } from './core/session';
import { ShellData } from './layout/shell';

const clientShell: ShellData = {
  portal: 'client',
  title: 'Client portal',
  nav: [
    { path: '/client/dashboard', label: 'Dashboard', icon: 'home' },
    { path: '/client/holdings', label: 'Holdings', icon: 'layers' },
    { path: '/client/transactions', label: 'Transactions', icon: 'transfer' },
    { path: '/client/performance', label: 'Performance', icon: 'trend' },
    { path: '/client/profile', label: 'Profile', icon: 'user' },
  ],
};

const advisorShell: ShellData = {
  portal: 'advisor',
  title: 'Advisor portal',
  nav: [
    { path: '/advisor/dashboard', label: 'Dashboard', icon: 'users' },
    { path: '/advisor/accounts', label: 'Accounts', icon: 'briefcase' },
    { path: '/advisor/assistant', label: 'Assistant', icon: 'chat' },
    { path: '/advisor/profile', label: 'Profile', icon: 'user' },
  ],
};

const comingNext = () => import('./pages/coming-next').then((m) => m.ComingNext);

export const routes: Routes = [
  { path: 'demo', title: 'Choose a demo user · AdvisorAgent', loadComponent: () => import('./pages/demo/demo').then((m) => m.Demo) },
  {
    path: 'client',
    canActivate: [portalGuard('client')],
    data: clientShell,
    loadComponent: () => import('./layout/shell').then((m) => m.Shell),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      { path: 'dashboard', title: 'Dashboard · Client portal', loadComponent: () => import('./pages/client/dashboard').then((m) => m.ClientDashboard) },
      { path: 'holdings', title: 'Holdings · Client portal', data: { title: 'Holdings' }, loadComponent: comingNext },
      { path: 'transactions', title: 'Transactions · Client portal', data: { title: 'Transactions' }, loadComponent: comingNext },
      { path: 'performance', title: 'Performance · Client portal', data: { title: 'Performance' }, loadComponent: comingNext },
      { path: 'profile', title: 'Profile · Client portal', data: { title: 'Profile' }, loadComponent: comingNext },
    ],
  },
  {
    path: 'advisor',
    canActivate: [portalGuard('advisor')],
    data: advisorShell,
    loadComponent: () => import('./layout/shell').then((m) => m.Shell),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      { path: 'dashboard', title: 'Dashboard · Advisor portal', data: { title: 'Dashboard' }, loadComponent: comingNext },
      { path: 'accounts', title: 'Accounts · Advisor portal', data: { title: 'Accounts' }, loadComponent: comingNext },
      { path: 'assistant', title: 'Assistant · Advisor portal', data: { title: 'Assistant' }, loadComponent: comingNext },
      { path: 'profile', title: 'Profile · Advisor portal', data: { title: 'Profile' }, loadComponent: comingNext },
    ],
  },
  {
    path: '**',
    // Signed in: go to your portal. Otherwise: choose a demo user.
    redirectTo: () => {
      const user = inject(Session).user();
      return inject(Router).parseUrl(user ? `/${user.kind}` : '/demo');
    },
  },
];
