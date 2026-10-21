import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { formatDuration, formatInt, formatUsd, formatXof, USAGE_STEP_LABELS } from '../core/format';
import { StepUsage, Usage } from '../core/models';

/** "Coût de l'analyse": the sales argument, measured on the real calls. */
@Component({
  selector: 'app-usage-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="card panel">
      <div class="kpi-grid">
        <div class="stack kpi">
          <span class="kpi-label">Coût total</span>
          <span class="kpi-value">{{ usd(usage().total.cost_usd) }}</span>
          <span class="xs muted num">≈ {{ xof(usage().total.cost_usd) }} FCFA</span>
        </div>
        <div class="stack kpi">
          <span class="kpi-label">Par verbatim analysé</span>
          <span class="kpi-value">{{ perVerbatimXof() }} <span class="unit">FCFA</span></span>
          <span class="xs muted num">{{ perVerbatimUsd() }}</span>
        </div>
        <div class="stack kpi">
          <span class="kpi-label">Durée</span>
          <span class="kpi-value">{{ durationSeconds() }}</span>
          <span class="xs muted num">{{ durationLabel() }}, pour {{ nUsed() }} verbatims</span>
        </div>
        <div class="stack kpi">
          <span class="kpi-label">Appels au modèle</span>
          <span class="kpi-value">{{ usage().total.calls }}</span>
          <span class="xs muted">sur {{ usage().steps.length }} étapes</span>
        </div>
      </div>
      <p class="summary num">{{ summary() }}</p>
      <div class="table-scroll bordered">
        <table class="tbl">
          <thead>
            <tr>
              <th>Étape</th>
              <th class="right">Appels</th>
              <th>Modèle</th>
              <th class="right">Tokens en entrée</th>
              <th class="right">Relus depuis le cache</th>
              <th class="right">Tokens en sortie</th>
              <th class="right">Coût</th>
              <th class="right">En FCFA</th>
            </tr>
          </thead>
          <tbody>
            @for (step of usage().steps; track step.step) {
              <tr>
                <td class="strong">{{ stepLabel(step) }}</td>
                <td class="num right">{{ step.calls }}</td>
                <td>
                  @for (model of step.models; track model) {
                    <code>{{ model }}</code>
                  }
                </td>
                <td class="num right">{{ int(inputTokens(step)) }}</td>
                <td class="num right">{{ int(step.cache_read_tokens) }}</td>
                <td class="num right">{{ int(step.output_tokens) }}</td>
                <td class="num right">{{ usd(step.cost_usd) }}</td>
                <td class="num right">{{ xof(step.cost_usd) }}</td>
              </tr>
            }
          </tbody>
          <tfoot>
            <tr>
              <td>Total</td>
              <td class="num right">{{ usage().total.calls }}</td>
              <td class="muted">—</td>
              <td class="num right">{{ int(inputTokens(usage().total)) }}</td>
              <td class="num right">{{ int(usage().total.cache_read_tokens) }}</td>
              <td class="num right">{{ int(usage().total.output_tokens) }}</td>
              <td class="num right">{{ usd(usage().total.cost_usd) }}</td>
              <td class="num right">{{ xof(usage().total.cost_usd) }}</td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p class="xs muted note">
        Conversion indicative : 1 $ = {{ int(usage().usd_to_xof) }} FCFA. Les tokens relus depuis le
        cache sont facturés à tarif réduit. Tokens en entrée : hors cache, écriture du cache
        incluse.
      </p>
    </div>
  `,
  styles: `
    .panel {
      padding: var(--space-5);
      display: flex;
      flex-direction: column;
      gap: 20px;
    }
    .kpi {
      gap: 6px;
    }
    .unit {
      font-size: 18px;
      font-weight: 500;
      color: var(--color-ink-muted);
    }
    .summary {
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      line-height: 1.6;
      color: var(--color-ink-secondary);
      background: var(--color-surface-alt);
      border: 1px solid var(--color-border);
      border-radius: var(--radius-md);
      padding: 10px 14px;
    }
    .bordered {
      border: 1px solid var(--color-border);
      border-radius: var(--radius-md);
    }
    .strong {
      font-weight: 500;
    }
    code + code {
      margin-left: 4px;
    }
    .note {
      line-height: 1.5;
    }
  `,
})
export class UsagePanel {
  readonly usage = input.required<Usage>();
  readonly nUsed = input.required<number>();

  protected readonly int = formatInt;

  protected usd(value: number | null): string {
    return value == null ? '—' : formatUsd(value);
  }

  protected xof(value: number | null): string {
    return value == null ? '—' : formatXof(value * this.usage().usd_to_xof);
  }

  protected stepLabel(step: StepUsage): string {
    return USAGE_STEP_LABELS[step.step] ?? step.step;
  }

  /** Uncached input, including the tokens written to the cache. */
  protected inputTokens(step: StepUsage): number {
    return step.input_tokens + step.cache_creation_tokens;
  }

  private readonly durationMs = computed(() => this.usage().analysis_duration_ms ?? 0);
  protected readonly durationSeconds = computed(() => `${Math.round(this.durationMs() / 1000)} s`);
  protected readonly durationLabel = computed(() => formatDuration(this.durationMs()));

  private readonly perVerbatim = computed(() => {
    const cost = this.usage().total.cost_usd;
    return cost == null || !this.nUsed() ? null : cost / this.nUsed();
  });
  protected readonly perVerbatimXof = computed(() => {
    const v = this.perVerbatim();
    return v == null ? '—' : formatXof(v * this.usage().usd_to_xof, 2);
  });
  protected readonly perVerbatimUsd = computed(() => {
    const v = this.perVerbatim();
    return v == null ? '' : formatUsd(v, 5);
  });

  protected readonly summary = computed(() => {
    const u = this.usage();
    const parts = [
      `${this.nUsed()} verbatims analysés`,
      `${u.total.calls} appels`,
      `${formatInt(this.inputTokens(u.total))} tokens en entrée + ${formatInt(u.total.cache_read_tokens)} relus depuis le cache`,
      `${formatInt(u.total.output_tokens)} en sortie`,
      `${this.usd(u.total.cost_usd)} (~${this.xof(u.total.cost_usd)} FCFA)`,
      this.durationSeconds(),
    ];
    return parts.join(' · ');
  });
}
