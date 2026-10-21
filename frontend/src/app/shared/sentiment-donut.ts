import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { ChartConfiguration } from 'chart.js';
import { BaseChartDirective, provideCharts, withDefaultRegisterables } from 'ng2-charts';

import { formatPct, SENTIMENT_META } from '../core/format';
import { SENTIMENTS, SentimentCounts } from '../core/models';
import { SentimentBadge } from './sentiment-badge';

// Same values as the --color-* tokens: Chart.js draws on a canvas and cannot read CSS vars.
const COLORS = { positive: '#166534', mixed: '#D97706', neutral: '#6B7280', negative: '#B91C1C' };

/** Sentiment distribution: ng2-charts doughnut plus an accessible legend. */
@Component({
  selector: 'app-sentiment-donut',
  imports: [BaseChartDirective, SentimentBadge],
  providers: [provideCharts(withDefaultRegisterables())],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="donut-wrap">
      <div class="donut" role="img" [attr.aria-label]="ariaLabel()">
        <canvas baseChart type="doughnut" [data]="data()" [options]="options"></canvas>
        <div class="center" aria-hidden="true">
          <span class="total num">{{ total() }}</span
          ><span class="xs muted">analysés</span>
        </div>
      </div>
      <ul class="legend">
        @for (row of rows(); track row.key) {
          <li>
            <app-sentiment-badge [sentiment]="row.key" />
            <span class="num value"
              ><strong>{{ row.count }}</strong> <span class="muted">· {{ row.pct }}</span></span
            >
          </li>
        }
      </ul>
    </div>
  `,
  styles: `
    .donut-wrap {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-5);
    }
    .donut {
      position: relative;
      width: 168px;
      height: 168px;
      flex: none;
    }
    .center {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      pointer-events: none;
    }
    .total {
      font-size: 30px;
      font-weight: 600;
      line-height: 1;
    }
    .legend {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 10px;
      flex: 1 1 220px;
      min-width: 0;
      li {
        display: flex;
        align-items: center;
        gap: var(--space-3);
      }
    }
    .value {
      margin-left: auto;
    }
  `,
})
export class SentimentDonut {
  readonly counts = input.required<SentimentCounts>();

  protected readonly total = computed(() =>
    SENTIMENTS.reduce((sum, key) => sum + this.counts()[key], 0),
  );
  protected readonly rows = computed(() =>
    SENTIMENTS.map((key) => ({
      key,
      count: this.counts()[key],
      pct: formatPct(this.counts()[key], this.total()),
    })),
  );
  protected readonly ariaLabel = computed(
    () =>
      'Répartition des sentiments : ' +
      this.rows()
        .map((r) => `${r.pct} ${SENTIMENT_META[r.key].label.toLowerCase()}s (${r.count})`)
        .join(', '),
  );
  protected readonly data = computed<ChartConfiguration<'doughnut'>['data']>(() => ({
    labels: SENTIMENTS.map((key) => SENTIMENT_META[key].label),
    datasets: [
      {
        data: SENTIMENTS.map((key) => this.counts()[key]),
        backgroundColor: SENTIMENTS.map((key) => COLORS[key]),
        borderWidth: 2,
        borderColor: '#FFFFFF',
      },
    ],
  }));
  protected readonly options: ChartConfiguration<'doughnut'>['options'] = {
    responsive: true,
    maintainAspectRatio: false,
    cutout: '68%',
    plugins: { legend: { display: false } },
  };
}
