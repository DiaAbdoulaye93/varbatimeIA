// Mirror of the Pydantic I/O schemas in backend/app/schemas.py (section "API I/O").

export type Sentiment = 'positive' | 'neutral' | 'negative' | 'mixed';
export type AnalysisStatus = 'pending' | 'processing' | 'done' | 'failed';
export type PipelineStep = 'preprocess' | 'extract' | 'cluster' | 'synthesize' | 'done';
export type SentimentCounts = Record<Sentiment, number>;

export const SENTIMENTS: readonly Sentiment[] = ['positive', 'mixed', 'neutral', 'negative'];
export const FINAL_STATUSES: readonly AnalysisStatus[] = ['done', 'failed'];

export interface AnalysisCreated {
  id: string;
  status: AnalysisStatus;
  cached: boolean;
}

export interface AnalysisSummary {
  id: string;
  name: string;
  context: string;
  status: AnalysisStatus;
  progress: number;
  created_at: string;
  total_verbatims: number;
}

export interface ProgressInfo {
  n_kept?: number | null;
  n_skipped?: number | null;
  batch_done?: number | null;
  batch_total?: number | null;
}

export interface AnalysisStats {
  n_received: number;
  n_used: number;
  n_skipped: number;
  n_failed: number;
  n_flagged: number;
  sentiment_counts: SentimentCounts;
}

export interface AnalysisDetail extends AnalysisSummary {
  source_filename: string | null;
  source_format: string | null;
  source_column: string | null;
  has_source_file: boolean;
  current_step: PipelineStep;
  progress_info: ProgressInfo | null;
  error: string | null;
  stats: AnalysisStats | null;
  synthesis_md: string | null;
  duration_ms: number | null;
  finished_at: string | null;
}

export interface RepresentativeVerbatim {
  idx: number;
  text: string;
}

export interface Theme {
  id: number;
  rank: number;
  label: string;
  description: string;
  count: number;
  pct: number;
  sentiment_breakdown: SentimentCounts;
  raw_labels: string[];
  representatives: RepresentativeVerbatim[];
}

export interface Verbatim {
  idx: number;
  text: string;
  sentiment: Sentiment | null;
  themes_raw: string[];
  key_phrase: string | null;
  skipped_reason: string | null;
  theme_ids: number[];
}

export interface VerbatimPage {
  items: Verbatim[];
  total: number;
  page: number;
  size: number;
}

export interface VerbatimQuery {
  page: number;
  size: number;
  sentiment?: Sentiment | null;
  theme_id?: number | null;
  q?: string | null;
  include_skipped?: boolean;
}

export interface StepUsage {
  step: string;
  calls: number;
  models: string[];
  input_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  output_tokens: number;
  duration_ms: number;
  cost_usd: number | null;
}

export interface Usage {
  steps: StepUsage[];
  total: StepUsage;
  analysis_duration_ms: number | null;
  usd_to_xof: number;
}

export interface ApiError {
  detail: string;
}
