import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { STEPS } from '../core/format';
import { AnalysisDetail } from '../core/models';
import { Icon } from './icon';

type StepState = 'done' | 'active' | 'failed' | 'upcoming';

interface StepView {
  label: string;
  state: StepState;
  sub: string;
}

/** The 4 pipeline steps, for a running or a failed analysis. */
@Component({
  selector: 'app-progress-stepper',
  imports: [Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <ol class="stepper">
      @for (step of steps(); track step.label; let i = $index; let last = $last) {
        <li
          [class]="'step-' + step.state"
          [attr.aria-current]="step.state === 'active' ? 'step' : null"
        >
          <span class="dot" aria-hidden="true">
            @switch (step.state) {
              @case ('done') {
                <app-icon name="check" [size]="14" [strokeWidth]="3" />
              }
              @case ('failed') {
                !
              }
              @default {
                {{ i + 1 }}
              }
            }
          </span>
          <span class="text">
            <span class="label">{{ step.label }}</span>
            <span class="sub">{{ step.sub }}</span>
          </span>
          @if (!last) {
            <span class="line" [class.line-done]="step.state === 'done'" aria-hidden="true"></span>
          }
        </li>
      }
    </ol>
  `,
  styles: `
    .stepper {
      display: flex;
      align-items: flex-start;
      list-style: none;
      margin: 0;
      padding: 0;
      gap: var(--space-3);
      flex-wrap: wrap;
    }
    li {
      flex: 1 1 180px;
      display: flex;
      align-items: center;
      gap: var(--space-3);
      min-width: 0;
    }
    .dot {
      width: 28px;
      height: 28px;
      border-radius: var(--radius-pill);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex: none;
      font-size: var(--text-xs);
      font-weight: 600;
      border: 2px solid var(--color-border-strong);
      color: var(--color-ink-muted);
      background: var(--color-surface);
    }
    .step-done .dot {
      background: var(--color-primary);
      border-color: var(--color-primary);
      color: #fff;
    }
    .step-active .dot {
      border-color: var(--color-primary);
      color: var(--color-primary);
      box-shadow: 0 0 0 4px var(--color-primary-soft);
    }
    .step-failed .dot {
      background: var(--color-negative);
      border-color: var(--color-negative);
      color: #fff;
    }
    .text {
      display: flex;
      flex-direction: column;
      min-width: 0;
    }
    .label {
      font-size: var(--text-base);
      font-weight: 600;
    }
    .sub {
      font-size: var(--text-xs);
      color: var(--color-ink-muted);
    }
    .step-upcoming .label {
      color: var(--color-ink-muted);
      font-weight: 500;
    }
    .step-failed .sub {
      color: var(--color-negative);
    }
    .line {
      flex: 1;
      height: 2px;
      background: var(--color-border);
      min-width: 16px;
    }
    .line-done {
      background: var(--color-primary);
    }
  `,
})
export class ProgressStepper {
  readonly analysis = input.required<AnalysisDetail>();

  protected readonly steps = computed<StepView[]>(() => {
    const a = this.analysis();
    const failed = a.status === 'failed';
    const current = Math.max(
      0,
      STEPS.findIndex((s) => s.key === a.current_step),
    );
    const info = a.progress_info ?? {};
    const batch =
      info.batch_total && info.batch_done != null
        ? `lot ${Math.min(info.batch_done + (failed ? 1 : 0), info.batch_total)} sur ${info.batch_total}`
        : '';
    return STEPS.map((step, i) => {
      let state: StepState = 'upcoming';
      if (a.status === 'done' || i < current) state = 'done';
      else if (i === current)
        state = failed ? 'failed' : a.status === 'pending' ? 'upcoming' : 'active';

      let sub = failed ? (step.key === 'synthesize' ? 'Non démarrée' : 'Non démarré') : 'À venir';
      if (state === 'done') {
        sub =
          step.key === 'preprocess' && info.n_kept != null
            ? `Terminé · ${(info.n_kept ?? 0) + (info.n_skipped ?? 0)} lus, ${info.n_skipped ?? 0} écartés`
            : 'Terminé';
      } else if (state === 'active') {
        sub = step.key === 'extract' && batch ? `En cours · ${batch}` : 'En cours';
      } else if (state === 'failed') {
        sub = step.key === 'extract' && batch ? `Échec · ${batch}` : 'Échec';
      }
      return { label: step.label, state, sub };
    });
  });
}
