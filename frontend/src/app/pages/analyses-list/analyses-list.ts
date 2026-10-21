import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { catchError, map, of, switchMap, takeWhile, timer } from 'rxjs';

import { ApiService, POLL_INTERVAL_MS } from '../../core/api.service';
import { formatDateTime, formatInt } from '../../core/format';
import { AnalysisSummary, FINAL_STATUSES } from '../../core/models';
import { Icon } from '../../shared/icon';
import { StatusBadge } from '../../shared/status-badge';

const PAGE_SIZE = 10;

interface ListState {
  analyses: AnalysisSummary[];
  error: boolean;
}

@Component({
  selector: 'app-analyses-list',
  imports: [RouterLink, Icon, StatusBadge],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './analyses-list.html',
  styleUrl: './analyses-list.scss',
})
export class AnalysesList {
  private readonly api = inject(ApiService);

  /** Refreshed every 3 s while at least one analysis is pending or running. */
  protected readonly state = toSignal(
    timer(0, POLL_INTERVAL_MS).pipe(
      switchMap(() =>
        this.api.listAnalyses().pipe(
          map((analyses): ListState => ({ analyses, error: false })),
          catchError(() => of<ListState>({ analyses: [], error: true })),
        ),
      ),
      takeWhile(
        (s) => !s.error && s.analyses.some((a) => !FINAL_STATUSES.includes(a.status)),
        true,
      ),
    ),
  );

  protected readonly page = signal(0);
  protected readonly analyses = computed(() => this.state()?.analyses ?? []);
  protected readonly pageCount = computed(() =>
    Math.max(1, Math.ceil(this.analyses().length / PAGE_SIZE)),
  );
  protected readonly rows = computed(() =>
    this.analyses().slice(this.page() * PAGE_SIZE, (this.page() + 1) * PAGE_SIZE),
  );
  protected readonly rangeLabel = computed(() => {
    const total = this.analyses().length;
    const start = this.page() * PAGE_SIZE;
    return total ? `${start + 1} – ${Math.min(start + PAGE_SIZE, total)} sur ${total}` : '0 sur 0';
  });

  protected readonly date = formatDateTime;
  protected readonly int = formatInt;

  protected goTo(page: number): void {
    this.page.set(Math.min(Math.max(page, 0), this.pageCount() - 1));
  }
}
