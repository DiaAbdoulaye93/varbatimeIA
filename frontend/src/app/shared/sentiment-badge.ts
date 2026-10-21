import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { SENTIMENT_META, SKIPPED_META } from '../core/format';
import { Sentiment } from '../core/models';

/** Sentiment pill with a glyph, so the meaning never relies on color alone. */
@Component({
  selector: 'app-sentiment-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span class="badge" [class]="meta().cls"
    ><span class="glyph" aria-hidden="true">{{ meta().glyph }}</span
    >{{ meta().label }}</span
  >`,
})
export class SentimentBadge {
  /** null renders the "Écarté" (skipped) variant. */
  readonly sentiment = input.required<Sentiment | null>();
  protected readonly meta = computed(() => {
    const s = this.sentiment();
    return s ? SENTIMENT_META[s] : SKIPPED_META;
  });
}
