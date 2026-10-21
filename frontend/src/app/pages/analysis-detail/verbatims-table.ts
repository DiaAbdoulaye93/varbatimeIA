import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  linkedSignal,
  model,
  signal,
} from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { catchError, debounceTime, map, of, switchMap } from 'rxjs';

import { ApiService } from '../../core/api.service';
import { formatInt, SENTIMENT_META, skippedMotif } from '../../core/format';
import { Sentiment, SENTIMENTS, Theme, Verbatim, VerbatimPage } from '../../core/models';
import { Icon } from '../../shared/icon';
import { SentimentBadge } from '../../shared/sentiment-badge';

const PAGE_SIZES = [10, 25, 50] as const;
const SEARCH_DEBOUNCE_MS = 300;

interface Row {
  idx: number;
  off: boolean;
  offText: string;
  motif: string;
  before: string;
  key: string;
  after: string;
  sentiment: Sentiment | null;
  themes: { id: number; label: string }[];
}

/** Split the text around its key phrase (case-insensitive) for highlighting. */
function splitKeyPhrase(text: string, key: string | null): [string, string, string] {
  const at = key ? text.toLowerCase().indexOf(key.toLowerCase()) : -1;
  if (!key || at < 0) return [text, '', ''];
  return [text.slice(0, at), text.slice(at, at + key.length), text.slice(at + key.length)];
}

@Component({
  selector: 'app-verbatims-table',
  imports: [Icon, SentimentBadge],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './verbatims-table.html',
  styleUrl: './verbatims-table.scss',
})
export class VerbatimsTable {
  private readonly api = inject(ApiService);

  readonly analysisId = input.required<string>();
  readonly themes = input.required<Theme[]>();
  readonly nSkipped = input.required<number>();
  /** Two-way bound with the theme cards of the parent page. */
  readonly themeId = model<number | null>(null);

  protected readonly sentimentOptions = SENTIMENTS.map((s) => ({
    value: s,
    label: SENTIMENT_META[s].label,
  }));
  protected readonly pageSizes = PAGE_SIZES;
  protected readonly sentiment = signal<Sentiment | null>(null);
  protected readonly search = signal('');
  protected readonly includeSkipped = signal(true);
  protected readonly size = signal<number>(PAGE_SIZES[0]);

  private readonly debouncedSearch = toSignal(
    toObservable(this.search).pipe(debounceTime(SEARCH_DEBOUNCE_MS)),
    { initialValue: '' },
  );
  private readonly filters = computed(() => ({
    sentiment: this.sentiment(),
    theme_id: this.themeId(),
    q: this.debouncedSearch(),
    include_skipped: this.includeSkipped(),
    size: this.size(),
  }));
  /** Back to page 1 whenever a filter changes. */
  protected readonly page = linkedSignal({ source: this.filters, computation: () => 1 });

  private readonly result = toSignal(
    toObservable(
      computed(() => ({ id: this.analysisId(), ...this.filters(), page: this.page() })),
    ).pipe(
      switchMap(({ id, ...query }) =>
        this.api.getVerbatims(id, query).pipe(
          map((data): VerbatimPage | 'error' => data),
          catchError(() => of('error' as const)),
        ),
      ),
    ),
  );

  protected readonly failed = computed(() => this.result() === 'error');
  protected readonly loading = computed(() => this.result() === undefined);
  private readonly data = computed(() => {
    const r = this.result();
    return r && r !== 'error' ? r : null;
  });
  protected readonly total = computed(() => this.data()?.total ?? 0);
  protected readonly pageCount = computed(() => Math.max(1, Math.ceil(this.total() / this.size())));
  private readonly themeLabels = computed(
    () => new Map(this.themes().map((t) => [t.id, t.label] as const)),
  );

  protected readonly rows = computed<Row[]>(() =>
    (this.data()?.items ?? []).map((v: Verbatim) => {
      const off = v.skipped_reason !== null;
      const [before, key, after] = splitKeyPhrase(v.text, off ? null : v.key_phrase);
      return {
        idx: v.idx,
        off,
        offText: v.skipped_reason === 'empty' ? '(réponse vide)' : v.text,
        motif: off ? `Motif : ${skippedMotif(v.skipped_reason ?? '')}` : '',
        before,
        key,
        after,
        sentiment: off ? null : v.sentiment,
        themes: v.theme_ids
          .filter((id) => this.themeLabels().has(id))
          .map((id) => ({ id, label: this.themeLabels().get(id) ?? '' })),
      };
    }),
  );

  protected readonly rangeLabel = computed(() => {
    const total = this.total();
    if (!total) return '0 sur 0';
    const start = (this.page() - 1) * this.size() + 1;
    return `${start} – ${Math.min(start + this.size() - 1, total)} sur ${formatInt(total)}`;
  });
  protected readonly themeLabel = computed(() => {
    const id = this.themeId();
    return id === null ? '' : (this.themeLabels().get(id) ?? '');
  });
  protected readonly sentimentLabel = computed(() => {
    const s = this.sentiment();
    return s ? SENTIMENT_META[s].label : '';
  });
  protected readonly anyFilter = computed(
    () => this.themeId() !== null || this.sentiment() !== null || this.search().trim() !== '',
  );

  protected onSentiment(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.sentiment.set(value ? (value as Sentiment) : null);
  }

  protected onTheme(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.themeId.set(value ? Number(value) : null);
  }

  protected onSearch(event: Event): void {
    this.search.set((event.target as HTMLInputElement).value);
  }

  protected onIncludeSkipped(event: Event): void {
    this.includeSkipped.set((event.target as HTMLInputElement).checked);
  }

  protected onSize(event: Event): void {
    this.size.set(Number((event.target as HTMLSelectElement).value));
  }

  protected reset(): void {
    this.themeId.set(null);
    this.sentiment.set(null);
    this.search.set('');
  }

  protected goTo(page: number): void {
    this.page.set(Math.min(Math.max(page, 1), this.pageCount()));
  }
}
