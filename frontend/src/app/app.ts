import { Component } from '@angular/core';
import { RouterLink, RouterOutlet } from '@angular/router';

import { Icon } from './shared/icon';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, Icon],
  template: `
    <header class="topbar no-print">
      <a routerLink="/" class="brand">
        <span class="logo"><app-icon name="message" [size]="16" /></span>
        <span class="brand-name">Analyseur de verbatims</span>
      </a>
    </header>
    <router-outlet />
  `,
  styles: `
    :host {
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    .topbar {
      height: var(--toolbar-height);
      background: var(--color-surface);
      border-bottom: 1px solid var(--color-border);
      display: flex;
      align-items: center;
      padding: 0 var(--space-6);
      flex: none;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      text-decoration: none;
      color: var(--color-ink);
    }
    .logo {
      width: 28px;
      height: 28px;
      border-radius: var(--radius-md);
      background: var(--color-primary);
      color: #fff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    .brand-name {
      font-size: var(--text-md);
      font-weight: 600;
      letter-spacing: -0.01em;
    }
    @media (max-width: 768px) {
      .topbar {
        padding: 0 var(--space-4);
      }
    }
  `,
})
export class App {}
