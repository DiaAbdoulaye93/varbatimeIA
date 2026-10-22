import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { catchError, forkJoin, map, of, switchMap } from 'rxjs';

import { ApiService } from '../../core/api.service';
import { formatInt, formatLaunched, skippedMotif } from '../../core/format';
import { AnalysisDetail, Verbatim } from '../../core/models';
import { Icon } from '../../shared/icon';
import { SentimentBadge } from '../../shared/sentiment-badge';

/** Matches MAX_ROWS of the backend: one request returns every answer of the file. */
const ALL_ROWS = 2000;

interface Loaded {
  analysis: AnalysisDetail;
  answers: Verbatim[];
}

/** Every answer as the tool read it from the file, with its status: printable. */
@Component({
  selector: 'app-answers-print',
  imports: [RouterLink, Icon, SentimentBadge],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './answers-print.html',
  styleUrl: './answers-print.scss',
})
export class AnswersPrint {
  private readonly api = inject(ApiService);

  /** Route parameter, bound by withComponentInputBinding(). */
  readonly id = input.required<string>();

  protected readonly loaded = toSignal(
    toObservable(this.id).pipe(
      switchMap((id) =>
        forkJoin({
          analysis: this.api.getAnalysis(id),
          answers: this.api
            .getVerbatims(id, { page: 1, size: ALL_ROWS, include_skipped: true })
            .pipe(map((page) => page.items)),
        }).pipe(catchError(() => of('error' as const))),
      ),
    ),
  );
  protected readonly data = computed<Loaded | null>(() => {
    const value = this.loaded();
    return value && value !== 'error' ? value : null;
  });
  protected readonly failed = computed(() => this.loaded() === 'error');
  protected readonly launched = computed(() => {
    const a = this.data()?.analysis;
    return a ? formatLaunched(a.created_at) : '';
  });
  protected readonly skippedCount = computed(
    () => this.data()?.answers.filter((v) => v.skipped_reason !== null).length ?? 0,
  );

  protected readonly int = formatInt;

  protected sourceUrl(id: string): string {
    return this.api.sourceUrl(id);
  }

  protected motif(reason: string): string {
    return skippedMotif(reason);
  }

  protected print(): void {
    window.print();
  }
}
