import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { STATUS_LABELS } from '../core/format';
import { AnalysisStatus } from '../core/models';
import { Icon, IconName } from './icon';

const ICONS: Record<AnalysisStatus, IconName> = {
  pending: 'clock',
  processing: 'spinner',
  done: 'check',
  failed: 'warning',
};

@Component({
  selector: 'app-status-badge',
  imports: [Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="status" [class]="'st-' + status()">
      <app-icon [name]="icon()" [size]="14" [strokeWidth]="2.5" />
      {{ label() }}
    </span>
  `,
  styles: `
    .status {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 26px;
      padding: 0 10px 0 8px;
      border-radius: var(--radius-pill);
      font-size: var(--text-xs);
      font-weight: 600;
      line-height: 1;
      border: 1px solid;
      white-space: nowrap;
    }
    .st-pending {
      color: var(--color-neutral-ink);
      border-color: var(--color-border-strong);
      background: var(--color-surface);
    }
    .st-processing {
      color: var(--color-primary-ink);
      border-color: var(--color-primary);
      background: var(--color-primary-soft);
    }
    .st-done {
      color: var(--color-positive-ink);
      border-color: var(--color-positive);
      background: var(--color-positive-soft);
    }
    .st-failed {
      color: var(--color-negative-ink);
      border-color: var(--color-negative);
      background: var(--color-negative-soft);
    }
  `,
})
export class StatusBadge {
  readonly status = input.required<AnalysisStatus>();
  readonly progress = input(0);
  protected readonly icon = computed(() => ICONS[this.status()]);
  protected readonly label = computed(() =>
    this.status() === 'processing'
      ? `${STATUS_LABELS.processing} · ${this.progress()} %`
      : STATUS_LABELS[this.status()],
  );
}
