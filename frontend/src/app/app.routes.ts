import { inject } from '@angular/core';
import { Router, Routes } from '@angular/router';
import { Auth } from './core/auth';
import { Session, portalGuard, signInPath } from './core/session';
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

const adminShell: ShellData = {
  portal: 'admin',
  title: 'Admin portal',
  nav: [
    { path: '/admin/users', label: 'Users', icon: 'users' },
    { path: '/admin/accounts', label: 'Accounts', icon: 'briefcase' },
    { path: '/admin/permissions', label: 'Permissions', icon: 'shield' },
    { path: '/admin/audit', label: 'Audit log', icon: 'table' },
    { path: '/admin/assistant', label: 'Assistant log', icon: 'chat' },
  ],
};

const profile = () => import('./pages/profile').then((m) => m.Profile);

export const routes: Routes = [
  {
    path: 'demo',
    title: 'Choose a demo user · AdvisorAgent',
    loadComponent: () => import('./pages/demo/demo').then((m) => m.Demo),
  },
  {
    path: 'login',
    title: 'Sign in · AdvisorAgent',
    loadComponent: () => import('./pages/login').then((m) => m.Login),
  },
  {
    path: 'auth/callback',
    title: 'Signing in · AdvisorAgent',
    loadComponent: () => import('./pages/login').then((m) => m.AuthCallback),
  },
  {
    path: 'client',
    canActivate: [portalGuard('client')],
    data: clientShell,
    loadComponent: () => import('./layout/shell').then((m) => m.Shell),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      {
        path: 'dashboard',
        title: 'Dashboard · Client portal',
        loadComponent: () => import('./pages/client/dashboard').then((m) => m.ClientDashboard),
      },
      {
        path: 'holdings',
        title: 'Holdings · Client portal',
        loadComponent: () => import('./pages/client/holdings').then((m) => m.ClientHoldings),
      },
      {
        path: 'transactions',
        title: 'Transactions · Client portal',
        loadComponent: () =>
          import('./pages/client/transactions').then((m) => m.ClientTransactions),
      },
      {
        path: 'performance',
        title: 'Performance · Client portal',
        loadComponent: () => import('./pages/client/performance').then((m) => m.ClientPerformance),
      },
      { path: 'profile', title: 'Profile · Client portal', loadComponent: profile },
    ],
  },
  {
    path: 'advisor',
    canActivate: [portalGuard('advisor')],
    data: advisorShell,
    loadComponent: () => import('./layout/shell').then((m) => m.Shell),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      {
        path: 'dashboard',
        title: 'Dashboard · Advisor portal',
        loadComponent: () => import('./pages/advisor/dashboard').then((m) => m.AdvisorDashboard),
      },
      {
        path: 'accounts',
        title: 'Accounts · Advisor portal',
        loadComponent: () => import('./pages/advisor/accounts').then((m) => m.AdvisorAccounts),
      },
      {
        path: 'assistant',
        title: 'Assistant · Advisor portal',
        loadComponent: () => import('./pages/advisor/assistant').then((m) => m.Assistant),
      },
      { path: 'profile', title: 'Profile · Advisor portal', loadComponent: profile },
    ],
  },
  {
    path: 'admin',
    canActivate: [portalGuard('admin')],
    data: adminShell,
    loadComponent: () => import('./layout/shell').then((m) => m.Shell),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'users' },
      {
        path: 'users',
        title: 'Users · Admin portal',
        loadComponent: () => import('./pages/admin/users').then((m) => m.AdminUsers),
      },
      {
        path: 'accounts',
        title: 'Accounts · Admin portal',
        loadComponent: () => import('./pages/admin/accounts').then((m) => m.AdminAccounts),
      },
      {
        path: 'permissions',
        title: 'Permissions · Admin portal',
        loadComponent: () => import('./pages/admin/permissions').then((m) => m.AdminPermissions),
      },
      {
        path: 'audit',
        title: 'Audit log · Admin portal',
        loadComponent: () => import('./pages/admin/logs').then((m) => m.AdminAudit),
      },
      {
        path: 'assistant',
        title: 'Assistant log · Admin portal',
        loadComponent: () => import('./pages/admin/logs').then((m) => m.AdminAssistantLog),
      },
    ],
  },
  {
    path: '**',
    // Signed in: go to your portal. Otherwise: choose a demo user.
    redirectTo: () => {
      const user = inject(Session).user();
      return inject(Router).parseUrl(user ? `/${user.kind}` : signInPath(inject(Auth)));
    },
  },
];
