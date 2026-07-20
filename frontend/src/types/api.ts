/** Stable API envelopes mirrored from backend/api_models.py. */
export type ReportState = "queued" | "processing" | "ready" | "error";

export interface AnalysisProgress {
  stage: string;
  pct: number;
  message: string;
  nodes_discovered: number;
  files_processed: number;
  log_lines_indexed: number;
}

export interface UploadResponse {
  id: string;
  status: "processing";
  file_size: number;
  detected_format: string;
  anonymized: boolean;
  message: string;
}

export interface ReportStatusResponse {
  id?: string;
  status: ReportState;
  progress?: AnalysisProgress | null;
  error?: string | null;
  detected_format?: string | null;
  file_size?: number | null;
  deployment_method?: string | null;
  deployment_confidence?: string | null;
  deployment_signals?: string | null;
}

export interface LogMatch {
  timestamp?: string;
  severity?: string;
  hostname?: string;
  source?: string;
  message?: string;
  line?: string;
  line_number?: number;
  context_before?: string[];
  context_after?: string[];
}

export interface LogSearchResponse {
  matches: LogMatch[];
  total: number;
  nodes_searched: number;
  truncated: boolean;
  search_mode: "raw" | "parsed";
  search_params: {
    keyword: string;
    regex: boolean;
    severity?: string | null;
    case_sensitive: boolean;
  };
}

export interface ReportOverview {
  id?: string;
  health_score?: number | string | null;
  health_grade?: string | null;
  cluster_risk_score?: number | null;
  cluster_overview?: Record<string, unknown>;
  recommendations?: unknown[];
  capabilities?: Record<string, unknown>;
  privacy?: Record<string, unknown>;
  parse_warnings?: unknown[];
  [key: string]: unknown;
}
