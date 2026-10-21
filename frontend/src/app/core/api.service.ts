import { HttpClient, HttpEvent, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, switchMap, takeWhile, timer } from 'rxjs';

import {
  AnalysisCreated,
  AnalysisDetail,
  AnalysisSummary,
  FINAL_STATUSES,
  Theme,
  Usage,
  VerbatimPage,
  VerbatimQuery,
} from './models';

const BASE = '/api/analyses';
export const POLL_INTERVAL_MS = 3000;

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  createAnalysis(
    file: File,
    context: string,
    name: string,
  ): Observable<HttpEvent<AnalysisCreated>> {
    const form = new FormData();
    form.append('file', file);
    form.append('context', context);
    if (name.trim()) {
      form.append('name', name.trim());
    }
    return this.http.post<AnalysisCreated>(BASE, form, { reportProgress: true, observe: 'events' });
  }

  listAnalyses(): Observable<AnalysisSummary[]> {
    return this.http.get<AnalysisSummary[]>(BASE);
  }

  getAnalysis(id: string): Observable<AnalysisDetail> {
    return this.http.get<AnalysisDetail>(`${BASE}/${id}`);
  }

  /** Emit the analysis every 3 s until it reaches a final status (included). */
  pollAnalysis(id: string): Observable<AnalysisDetail> {
    return timer(0, POLL_INTERVAL_MS).pipe(
      switchMap(() => this.getAnalysis(id)),
      takeWhile((a) => !FINAL_STATUSES.includes(a.status), true),
    );
  }

  getThemes(id: string): Observable<Theme[]> {
    return this.http.get<Theme[]>(`${BASE}/${id}/themes`);
  }

  getVerbatims(id: string, query: VerbatimQuery): Observable<VerbatimPage> {
    let params = new HttpParams().set('page', query.page).set('size', query.size);
    if (query.sentiment) params = params.set('sentiment', query.sentiment);
    if (query.theme_id != null) params = params.set('theme_id', query.theme_id);
    if (query.q?.trim()) params = params.set('q', query.q.trim());
    if (query.include_skipped) params = params.set('include_skipped', true);
    return this.http.get<VerbatimPage>(`${BASE}/${id}/verbatims`, { params });
  }

  getUsage(id: string): Observable<Usage> {
    return this.http.get<Usage>(`${BASE}/${id}/usage`);
  }
}
