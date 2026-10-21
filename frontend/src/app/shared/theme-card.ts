import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';

import { formatPct, SENTIMENT_META } from '../core/format';
import { SENTIMENTS, Theme } from '../core/models';
import { Icon } from './icon';

/** One canonical theme: count, stacked sentiment bar, quotes, filter action. */
@Component({
  selector: 'app-theme-card',
  imports: [Icon],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <article class="card theme-card" [class.selected]="selected()">
      <div class="head">
        <div class="title">
          <span class="rank num">{{ theme().rank }}</span>
          <h3>{{ theme().label }}</h3>
        </div>
        <div class="count">
          <div class="num value">{{ theme().count }}</div>
          <div class="xs muted nowrap">mentions · {{ pct() }}</div>
        </div>
      </div>
      <p class="small muted desc">{{ theme().description }}</p>
      <div class="stack bars">
        <div class="stacked-bar" role="img" [attr.aria-label]="barLabel()">
          @for (part of parts(); track part.key) {
            @if (part.count > 0) {
              <div
                [class]="'bg-' + part.key"
                [style.width.%]="part.width"
                [title]="part.label + ' : ' + part.count"
              ></div>
            }
          }
        </div>
        <div class="legend num xs">
          @for (part of parts(); track part.key) {
            <span
              ><span class="legend-dot" [class]="'bg-' + part.key"></span>{{ part.label }}
              {{ part.count }}</span
            >
          }
        </div>
      </div>
      @if (showQuotes() && theme().representatives.length) {
        <div class="quotes">
          @for (q of theme().representatives; track q.idx) {
            <p class="quote">
              « {{ q.text }} » <span class="muted nowrap">— n° {{ q.idx }}</span>
            </p>
          }
        </div>
      }
      <button type="button" class="btn btn-text cta" (click)="pick.emit(theme().id)">
        <app-icon name="filter" />{{ cta() }}
      </button>
    </article>
  `,
  styles: `
    .theme-card {
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
      transition: box-shadow 0.15s;
      height: 100%;
    }
    .selected {
      border-color: var(--color-primary);
      box-shadow: 0 0 0 2px var(--color-primary);
    }
    .head {
      display: flex;
      justify-content: space-between;
      gap: var(--space-3);
      align-items: flex-start;
    }
    .title {
      display: flex;
      gap: 10px;
      align-items: baseline;
      min-width: 0;
    }
    .rank {
      font-size: var(--text-xs);
      font-weight: 600;
      color: var(--color-ink-muted);
    }
    h3 {
      font-size: var(--text-md);
      font-weight: 600;
      line-height: 1.3;
    }
    .count {
      text-align: right;
      flex: none;
    }
    .value {
      font-size: 18px;
      font-weight: 600;
      line-height: 1.1;
    }
    .nowrap {
      white-space: nowrap;
    }
    .desc {
      line-height: 1.45;
    }
    .bars {
      gap: 6px;
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 4px 12px;
      color: var(--color-ink-secondary);
    }
    .quotes {
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
      border-top: 1px solid var(--color-border-subtle);
      padding-top: var(--space-3);
    }
    .quote {
      font-size: var(--text-sm);
      line-height: 1.5;
      color: var(--color-ink-secondary);
    }
    .cta {
      align-self: flex-start;
      margin-left: calc(-1 * var(--space-3));
      margin-top: auto;
    }
  `,
})
export class ThemeCard {
  readonly theme = input.required<Theme>();
  readonly nUsed = input.required<number>();
  readonly selected = input(false);
  readonly showQuotes = input(true);
  readonly pick = output<number>();

  protected readonly pct = computed(() => formatPct(this.theme().count, this.nUsed()));
  protected readonly parts = computed(() => {
    const t = this.theme();
    return SENTIMENTS.map((key) => ({
      key,
      label: SENTIMENT_META[key].label,
      count: t.sentiment_breakdown[key],
      width: t.count ? (100 * t.sentiment_breakdown[key]) / t.count : 0,
    }));
  });
  protected readonly barLabel = computed(
    () =>
      'Répartition des sentiments : ' +
      this.parts()
        .map((p) => `${p.count} ${p.label.toLowerCase()}`)
        .join(', '),
  );
  protected readonly cta = computed(() => {
    if (this.selected()) return 'Filtre actif sur le tableau';
    const n = this.theme().count;
    return n === 1 ? 'Voir le verbatim' : `Voir les ${n} verbatims`;
  });
}
