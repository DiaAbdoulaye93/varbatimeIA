import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    title: 'Analyses · Analyseur de verbatims',
    loadComponent: () => import('./pages/analyses-list/analyses-list').then((m) => m.AnalysesList),
  },
  {
    path: 'analyses/nouvelle',
    title: 'Nouvelle analyse · Analyseur de verbatims',
    loadComponent: () => import('./pages/analysis-new/analysis-new').then((m) => m.AnalysisNew),
  },
  {
    path: 'analyses/:id',
    title: 'Analyse · Analyseur de verbatims',
    loadComponent: () =>
      import('./pages/analysis-detail/analysis-detail').then((m) => m.AnalysisDetailPage),
  },
  { path: '**', redirectTo: '' },
];
