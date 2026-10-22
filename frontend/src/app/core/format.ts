// French display helpers shared by the pages.

import { AnalysisStatus, PipelineStep, Sentiment } from './models';

const NUMBER = new Intl.NumberFormat('fr-FR');
const DATE_TIME = new Intl.DateTimeFormat('fr-FR', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});
const DATE = new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });
const TIME = new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit' });

export interface SentimentMeta {
  label: string;
  glyph: string;
  cls: string;
}

export const SENTIMENT_META: Record<Sentiment, SentimentMeta> = {
  positive: { label: 'Positif', glyph: '+', cls: 'sent-positive' },
  mixed: { label: 'Mixte', glyph: '±', cls: 'sent-mixed' },
  neutral: { label: 'Neutre', glyph: '=', cls: 'sent-neutral' },
  negative: { label: 'Négatif', glyph: '−', cls: 'sent-negative' },
};
export const SKIPPED_META: SentimentMeta = { label: 'Écarté', glyph: '×', cls: 'sent-off' };

export const STATUS_LABELS: Record<AnalysisStatus, string> = {
  pending: 'En attente',
  processing: 'En cours',
  done: 'Terminée',
  failed: 'Échec',
};

export const STEPS: readonly { key: PipelineStep; label: string }[] = [
  { key: 'preprocess', label: 'Prétraitement' },
  { key: 'extract', label: 'Extraction' },
  { key: 'cluster', label: 'Regroupement des thèmes' },
  { key: 'synthesize', label: 'Synthèse' },
];

export const USAGE_STEP_LABELS: Record<string, string> = {
  check: 'Vérification du fichier',
  extract: 'Extraction',
  cluster: 'Regroupement',
  synthesize: 'Synthèse',
};

export function formatInt(value: number): string {
  return NUMBER.format(value);
}

/** Percentage rounded to the unit; "< 1 %" for small non-zero shares. */
export function formatPct(part: number, whole: number): string {
  if (!whole) return '0 %';
  const pct = (100 * part) / whole;
  return pct > 0 && pct < 1 ? '< 1 %' : `${Math.round(pct)} %`;
}

export function formatDateTime(iso: string): string {
  return DATE_TIME.format(new Date(iso));
}

/** "21 oct. 2026 à 10:42" */
export function formatLaunched(iso: string): string {
  const date = new Date(iso);
  return `${DATE.format(date)} à ${TIME.format(date)}`;
}

export function formatTime(iso: string): string {
  return TIME.format(new Date(iso));
}

/** "93 s", "1 min 33 s" */
export function formatDuration(ms: number): string {
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
}

export function formatUsd(value: number, digits = 3): string {
  return `${value.toLocaleString('fr-FR', { minimumFractionDigits: digits, maximumFractionDigits: digits })} $`;
}

export function formatXof(value: number, digits = 0): string {
  return value.toLocaleString('fr-FR', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** Human label for a skipped verbatim: "vide", "doublon du n° 9", ... */
export function skippedMotif(reason: string): string {
  if (reason === 'empty') return 'vide';
  if (reason.startsWith('duplicate_of:')) return `doublon du n° ${reason.split(':')[1]}`;
  if (reason === 'extraction_failed') return 'analyse impossible';
  if (reason === 'off_topic') return "hors-sujet (signalé par l'IA)";
  if (reason === 'manipulation') return "tentative de manipulation de l'IA";
  return reason;
}

/** "Post-achat agence Dakar" from "post_achat_agence_dakar.csv". */
export function nameFromFilename(filename: string): string {
  const stem = filename
    .replace(/\.[^.]+$/, '')
    .replace(/[_]+/g, ' ')
    .trim();
  return stem ? stem.charAt(0).toUpperCase() + stem.slice(1) : '';
}

export function shortRef(id: string): string {
  return `ANL-${id.slice(0, 8).toUpperCase()}`;
}
