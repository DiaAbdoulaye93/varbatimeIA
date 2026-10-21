import { DOCUMENT } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import {
  catchError,
  distinctUntilChanged,
  filter,
  forkJoin,
  interval,
  map,
  of,
  startWith,
  switchMap,
} from 'rxjs';

import { ApiService } from '../../core/api.service';
import {
  formatDuration,
  formatInt,
  formatLaunched,
  formatPct,
  formatTime,
  shortRef,
  STEPS,
} from '../../core/format';
import { AnalysisDetail, Theme, Usage } from '../../core/models';
import { Icon } from '../../shared/icon';
import { ProgressStepper } from '../../shared/progress-stepper';
import { SentimentDonut } from '../../shared/sentiment-donut';
import { StatusBadge } from '../../shared/status-badge';
import { ThemeCard } from '../../shared/theme-card';
import { UsagePanel } from '../../shared/usage-panel';
import { SynthesisSheet } from './synthesis-sheet';
import { VerbatimsTable } from './verbatims-table';

const SECTIONS = [
  { id: 'chiffres', label: 'Chiffres clés' },
  { id: 'themes', label: 'Thèmes' },
  { id: 'synthese', label: 'Synthèse exécutive' },
  { id: 'verbatims', label: 'Verbatims' },
  { id: 'cout', label: "Coût de l'analyse" },
] as const;
const NO_QUOTE_THEMES = ['appréciation générale', 'autres remarques'];

type Loaded<T> = T | 'missing' | 'error';

interface Results {
  themes: Theme[];
  usage: Usage;
}

@Component({
  selector: 'app-analysis-detail',
  imports: [
    RouterLink,
    Icon,
    StatusBadge,
    ProgressStepper,
    SentimentDonut,
    ThemeCard,
    SynthesisSheet,
    VerbatimsTable,
    UsagePanel,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './analysis-detail.html',
  styleUrl: './analysis-detail.scss',
})
export class AnalysisDetailPage {
  private readonly api = inject(ApiService);
  private readonly document = inject(DOCUMENT);

  /** Route parameter, bound by withComponentInputBinding(). */
  readonly id = input.required<string>();

  /** Polled every 3 s until done or failed. */
  private readonly loaded = toSignal(
    toObservable(this.id).pipe(
      switchMap((id) =>
        this.api.pollAnalysis(id).pipe(
          map((a): Loaded<AnalysisDetail> => a),
          catchError((err: { status?: number }) =>
            of<Loaded<AnalysisDetail>>(err.status === 404 ? 'missing' : 'error'),
          ),
        ),
      ),
    ),
  );
  protected readonly analysis = computed(() => {
    const a = this.loaded();
    return a && typeof a === 'object' ? a : null;
  });
  protected readonly loadError = computed(() => {
    const a = this.loaded();
    return typeof a === 'string' ? a : null;
  });

  /** Themes and usage, fetched once the analysis is done. */
  protected readonly results = toSignal(
    toObservable(computed(() => (this.analysis()?.status === 'done' ? this.id() : null))).pipe(
      distinctUntilChanged(),
      filter((id): id is string => id !== null),
      switchMap((id) =>
        forkJoin({ themes: this.api.getThemes(id), usage: this.api.getUsage(id) }).pipe(
          catchError(() => of(null)),
        ),
      ),
    ),
  );

  protected readonly themeFilter = signal<number | null>(null);
  protected readonly activeSection = signal<string>(SECTIONS[0].id);
  protected readonly sections = SECTIONS;

  /** Ticks every second for the "elapsed" counter while the analysis runs. */
  private readonly now = toSignal(
    interval(1000).pipe(
      startWith(0),
      map(() => Date.now()),
    ),
    {
      initialValue: Date.now(),
    },
  );

  protected readonly int = formatInt;
  protected readonly launched = computed(() => {
    const a = this.analysis();
    return a ? formatLaunched(a.created_at) : '';
  });
  protected readonly startTime = computed(() => {
    const a = this.analysis();
    return a ? formatTime(a.created_at) : '';
  });
  protected readonly elapsed = computed(() => {
    const a = this.analysis();
    if (!a) return '';
    const end = a.finished_at ? new Date(a.finished_at).getTime() : this.now();
    return formatDuration(Math.max(0, end - new Date(a.created_at).getTime()));
  });
  protected readonly duration = computed(() => {
    const ms = this.analysis()?.duration_ms;
    return ms == null ? this.elapsed() : formatDuration(ms);
  });
  protected readonly generatedOn = computed(() => {
    const a = this.analysis();
    return a?.finished_at ? formatLaunched(a.finished_at).split(' à ')[0] : '';
  });
  protected readonly stepIndex = computed(() =>
    Math.max(
      0,
      STEPS.findIndex((s) => s.key === this.analysis()?.current_step),
    ),
  );
  protected readonly stepLabel = computed(() => STEPS[this.stepIndex()].label);
  protected readonly runningDetail = computed(() => {
    const a = this.analysis();
    if (!a || a.status === 'pending') return "En attente de démarrage de l'analyse";
    const info = a.progress_info ?? {};
    const prefix = `Étape ${this.stepIndex() + 1} sur 4`;
    switch (a.current_step) {
      case 'preprocess':
        return `${prefix} · Prétraitement des verbatims`;
      case 'extract':
        return info.batch_total
          ? `${prefix} · Extraction du sentiment et des thèmes, lot ${Math.min((info.batch_done ?? 0) + 1, info.batch_total)} sur ${info.batch_total}`
          : `${prefix} · Extraction du sentiment et des thèmes`;
      case 'cluster':
        return `${prefix} · Regroupement des thèmes`;
      default:
        return `${prefix} · Rédaction de la synthèse`;
    }
  });
  protected readonly reference = computed(() => shortRef(this.id()));
  protected readonly analysedPct = computed(() => {
    const s = this.analysis()?.stats;
    return s ? formatPct(s.n_used, s.n_received) : '';
  });
  protected readonly analysedWidth = computed(() => {
    const s = this.analysis()?.stats;
    return s && s.n_received ? (100 * s.n_used) / s.n_received : 0;
  });

  protected showQuotes(theme: Theme): boolean {
    return !NO_QUOTE_THEMES.includes(theme.label.toLowerCase());
  }

  protected pickTheme(themeId: number): void {
    this.themeFilter.set(themeId);
    this.scrollTo('verbatims');
  }

  protected scrollTo(sectionId: string): void {
    this.activeSection.set(sectionId);
    this.document.getElementById(sectionId)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  protected resultsOf(value: Results | null | undefined): Results | null {
    return value ?? null;
  }
}
