export interface RuntimeSnapshotMetaApiResponse {
  revision: number;
  generated_at: string;
  expires_at: string;
}

export interface RuntimeCountsApiResponse {
  running: number;
  retrying: number;
}

export interface RuntimeTokensApiResponse {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface RuntimeRunningEntryApiResponse {
  issue_id: string;
  issue_identifier: string;
  attempt: number | null;
  state: string;
  session_id: string | null;
  turn_count: number | null;
  last_event: string | null;
  last_message: string | null;
  started_at: string | null;
  last_event_at: string | null;
  workspace_path: string | null;
  tokens: RuntimeTokensApiResponse | null;
}

export interface RuntimeRetryPriorSessionApiResponse {
  session_id?: string | null;
  thread_id?: string | null;
  turn_id?: string | null;
  turn_count?: number | null;
  last_event?: string | null;
  last_event_at?: string | null;
  tokens?: RuntimeTokensApiResponse | null;
}

export interface RuntimeRetryEntryApiResponse {
  issue_id: string;
  issue_identifier: string;
  attempt: number | null;
  due_at: string | null;
  error: string | null;
  workspace_path: string | null;
  prior_session?: RuntimeRetryPriorSessionApiResponse | null;
}

export interface RateLimitWindowApiResponse {
  resetsAt: number | null;
  usedPercent: number | null;
  windowDurationMins: number | null;
}

export interface RateLimitCreditsApiResponse {
  balance: number | null;
  hasCredits: boolean | null;
  unlimited: boolean | null;
}

export interface RateLimitsApiResponse {
  limitId?: string | null;
  limitName?: string | null;
  planType?: string | null;
  credits?: RateLimitCreditsApiResponse | null;
  primary?: RateLimitWindowApiResponse | null;
  secondary?: RateLimitWindowApiResponse | null;
  [key: string]: unknown;
}

export interface RuntimeStateApiResponse extends RuntimeSnapshotMetaApiResponse {
  counts: RuntimeCountsApiResponse;
  running: RuntimeRunningEntryApiResponse[];
  retrying: RuntimeRetryEntryApiResponse[];
  codex_totals: RuntimeTokensApiResponse & {
    seconds_running: number;
  };
  rate_limits: RateLimitsApiResponse | null;
}

export interface RuntimeIssueAttemptsApiResponse {
  restart_count: number | null;
  current_retry_attempt: number | null;
}

export interface RuntimeRecentEventApiResponse {
  at: string | null;
  event: string;
  message: string;
}

export interface RuntimeIssueRunningApiResponse {
  session_id: string | null;
  turn_count: number | null;
  state: string | null;
  started_at: string | null;
  last_event: string | null;
  last_message: string;
  last_event_at: string | null;
  tokens: RuntimeTokensApiResponse | null;
}

export interface RuntimeIssueRetryApiResponse {
  attempt: number | null;
  due_at: string | null;
  error: string | null;
  prior_session?: RuntimeRetryPriorSessionApiResponse | null;
}

export interface RuntimeIssueApiResponse extends RuntimeSnapshotMetaApiResponse {
  issue_identifier: string;
  issue_id: string | null;
  status: "running" | "retrying";
  workspace: {
    path: string;
  } | null;
  attempts: RuntimeIssueAttemptsApiResponse;
  running: RuntimeIssueRunningApiResponse | null;
  retry: RuntimeIssueRetryApiResponse | null;
  logs: {
    codex_session_logs: unknown[];
  };
  recent_events: RuntimeRecentEventApiResponse[];
  last_error: string | null;
  tracked: Record<string, unknown>;
}

export interface RuntimeRefreshApiResponse {
  queued: boolean;
  coalesced: boolean;
  requested_at: string;
  operations: string[];
}

export interface RuntimeInvalidationEvent {
  sequence: number;
  event: string;
  emitted_at: string;
  revision?: number;
  issue_identifiers?: string[];
}

export interface RuntimeApiErrorEnvelope {
  error: {
    code: string;
    message: string;
  };
}

export type RuntimeErrorKind =
  | "issue_not_found"
  | "stale"
  | "timeout"
  | "unavailable"
  | "unexpected";

export interface RuntimeUiError {
  kind: RuntimeErrorKind;
  code: string;
  message: string;
  status: number | null;
}

export interface SnapshotStatusViewModel {
  label: string;
  tone: "live" | "warning" | "danger";
  detail: string;
}

export interface RuntimeStatCardViewModel {
  label: string;
  value: string;
  detail: string;
}

export interface RuntimeActivityRowViewModel {
  identifier: string;
  issueId: string;
  state: string;
  session: string;
  lastEvent: string;
  lastMessage: string;
  lastMessageRaw: string;
  startedAt: string;
  updatedAt: string;
  workspacePath: string;
  attemptLabel: string;
  tokenSummary: string;
}

export interface RuntimeRetryRowViewModel {
  identifier: string;
  issueId: string;
  attemptLabel: string;
  dueAt: string;
  error: string;
  workspacePath: string;
  priorSessionLabel: string;
}

export interface DashboardViewModel {
  snapshotStatus: SnapshotStatusViewModel;
  generatedAt: string;
  expiresAt: string;
  statCards: RuntimeStatCardViewModel[];
  activeIssues: RuntimeActivityRowViewModel[];
  retryQueue: RuntimeRetryRowViewModel[];
  rateLimits: RuntimeStatCardViewModel[];
  rateLimitsRawJson: string | null;
  hasActivity: boolean;
}

export interface RunsViewModel {
  snapshotStatus: SnapshotStatusViewModel;
  activeRuns: RuntimeActivityRowViewModel[];
  retryQueue: RuntimeRetryRowViewModel[];
  emptyMessage: string;
}

export interface IssueSessionSummaryViewModel {
  title: string;
  sessionId: string;
  event: string;
  eventAt: string;
  turns: string;
  tokens: string;
}

export interface IssueDetailViewModel {
  identifier: string;
  issueId: string;
  statusLabel: string;
  workspacePath: string;
  attemptSummary: string;
  lastError: string;
  recentEvents: Array<{
    at: string;
    event: string;
    message: string;
  }>;
  currentSession: IssueSessionSummaryViewModel | null;
  previousSession: IssueSessionSummaryViewModel | null;
  retryWindow: string;
}

export interface RefreshReceiptViewModel {
  queuedLabel: string;
  requestedAt: string;
  operationsLabel: string;
}

export interface RuntimeLoadState<TSnapshot> {
  snapshot: TSnapshot | null;
  error: RuntimeUiError | null;
  initialLoadPending: boolean;
  refreshPending: boolean;
}
