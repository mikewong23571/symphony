import {
  DashboardViewModel,
  IssueDetailViewModel,
  IssueSessionSummaryViewModel,
  RefreshReceiptViewModel,
  RunsViewModel,
  RuntimeActivityRowViewModel,
  RuntimeIssueApiResponse,
  RuntimeRefreshApiResponse,
  RuntimeRetryEntryApiResponse,
  RuntimeRetryRowViewModel,
  RuntimeRunningEntryApiResponse,
  RuntimeStateApiResponse,
  RuntimeStatCardViewModel
} from "./runtime-types";
import {
  describeSnapshotStatus,
  formatDurationSeconds,
  formatInteger,
  formatTimestamp,
  formatTokenSummary
} from "./runtime-formatters";

export function presentDashboardSnapshot(
  snapshot: RuntimeStateApiResponse
): DashboardViewModel {
  const snapshotStatus = describeSnapshotStatus(
    snapshot.generated_at,
    snapshot.expires_at
  );

  return {
    snapshotStatus,
    generatedAt: formatTimestamp(snapshot.generated_at),
    expiresAt: formatTimestamp(snapshot.expires_at),
    statCards: buildDashboardStatCards(snapshot),
    activeIssues: snapshot.running.map(presentRunningRow),
    retryQueue: snapshot.retrying.map(presentRetryRow),
    rateLimits: presentRateLimits(snapshot.rate_limits),
    rateLimitsRawJson: snapshot.rate_limits
      ? JSON.stringify(snapshot.rate_limits, null, 2)
      : null,
    hasActivity: snapshot.running.length > 0 || snapshot.retrying.length > 0
  };
}

export function presentRunsSnapshot(
  snapshot: RuntimeStateApiResponse
): RunsViewModel {
  return {
    snapshotStatus: describeSnapshotStatus(
      snapshot.generated_at,
      snapshot.expires_at
    ),
    activeRuns: snapshot.running.map(presentRunningRow),
    retryQueue: snapshot.retrying.map(presentRetryRow),
    emptyMessage:
      snapshot.running.length === 0 && snapshot.retrying.length === 0
        ? "No active runs or queued retries are present in the current snapshot."
        : ""
  };
}

export function presentIssueSnapshot(
  snapshot: RuntimeIssueApiResponse
): IssueDetailViewModel {
  const retryWindow = snapshot.retry
    ? snapshot.retry.attempt === null
      ? `Retry pending, scheduled for ${formatTimestamp(snapshot.retry.due_at)}.`
      : `Retry ${formatInteger(snapshot.retry.attempt)} scheduled for ${formatTimestamp(snapshot.retry.due_at)}.`
    : "No retry is currently scheduled.";

  return {
    identifier: snapshot.issue_identifier,
    issueId: snapshot.issue_id ?? "Unavailable",
    statusLabel:
      snapshot.status === "running" ? "Running now" : "Queued for retry",
    workspacePath: snapshot.workspace?.path ?? "Unavailable",
    attemptSummary: formatAttemptSummary(snapshot),
    lastError: snapshot.last_error ?? "No recorded error.",
    recentEvents: snapshot.recent_events.map((event) => ({
      at: formatTimestamp(event.at),
      event: event.event,
      message: event.message || "No event message recorded."
    })),
    currentSession: snapshot.running
      ? presentSessionSummary({
          title: "Current session",
          sessionId: snapshot.running.session_id,
          turnCount: snapshot.running.turn_count,
          lastEvent: snapshot.running.last_event,
          lastEventAt: snapshot.running.last_event_at,
          tokens: snapshot.running.tokens
        })
      : null,
    previousSession: snapshot.retry?.prior_session
      ? presentSessionSummary({
          title: "Previous session",
          sessionId: snapshot.retry.prior_session.session_id,
          turnCount: snapshot.retry.prior_session.turn_count,
          lastEvent: snapshot.retry.prior_session.last_event,
          lastEventAt: snapshot.retry.prior_session.last_event_at,
          tokens: snapshot.retry.prior_session.tokens ?? null
        })
      : null,
    retryWindow
  };
}

export function presentRefreshReceipt(
  receipt: RuntimeRefreshApiResponse
): RefreshReceiptViewModel {
  return {
    queuedLabel: receipt.coalesced
      ? "Refresh request reused an existing queue entry."
      : "Refresh request queued.",
    requestedAt: formatTimestamp(receipt.requested_at),
    operationsLabel: receipt.operations.join(" + ")
  };
}

function buildDashboardStatCards(
  snapshot: RuntimeStateApiResponse
): RuntimeStatCardViewModel[] {
  return [
    {
      label: "Running",
      value: formatInteger(snapshot.counts.running),
      detail:
        snapshot.counts.running > 0
          ? "Live orchestrator sessions"
          : "No issues are running."
    },
    {
      label: "Retrying",
      value: formatInteger(snapshot.counts.retrying),
      detail:
        snapshot.counts.retrying > 0
          ? "Issues waiting for another attempt"
          : "Retry queue is empty."
    },
    {
      label: "Codex tokens",
      value: formatInteger(snapshot.codex_totals.total_tokens),
      detail: `${formatInteger(snapshot.codex_totals.input_tokens)} input / ${formatInteger(snapshot.codex_totals.output_tokens)} output`
    },
    {
      label: "Runtime",
      value: formatDurationSeconds(snapshot.codex_totals.seconds_running),
      detail: `Snapshot generated ${formatTimestamp(snapshot.generated_at)}`
    }
  ];
}

function presentRateLimits(
  rateLimits: RuntimeStateApiResponse["rate_limits"]
): RuntimeStatCardViewModel[] {
  if (!rateLimits) return [];

  const cards: RuntimeStatCardViewModel[] = [];

  if (rateLimits.limitName) {
    cards.push({
      label: "limit name",
      value: String(rateLimits.limitName),
      detail: ""
    });
  }

  if (rateLimits.planType) {
    cards.push({
      label: "plan type",
      value: String(rateLimits.planType),
      detail: ""
    });
  }

  if (rateLimits.primary && typeof rateLimits.primary === "object") {
    const p = rateLimits.primary;
    const duration = formatWindowMins(p.windowDurationMins);
    const resetsAt =
      p.resetsAt != null
        ? formatTimestamp(new Date(p.resetsAt * 1000).toISOString())
        : "";
    cards.push({
      label: duration ? `primary window (${duration})` : "primary window",
      value: p.usedPercent != null ? `${p.usedPercent}% used` : "—",
      detail: resetsAt ? `Resets ${resetsAt}` : ""
    });
  }

  if (rateLimits.secondary && typeof rateLimits.secondary === "object") {
    const s = rateLimits.secondary;
    const duration = formatWindowMins(s.windowDurationMins);
    const resetsAt =
      s.resetsAt != null
        ? formatTimestamp(new Date(s.resetsAt * 1000).toISOString())
        : "";
    cards.push({
      label: duration ? `secondary window (${duration})` : "secondary window",
      value: s.usedPercent != null ? `${s.usedPercent}% used` : "—",
      detail: resetsAt ? `Resets ${resetsAt}` : ""
    });
  }

  if (rateLimits.credits && typeof rateLimits.credits === "object") {
    const c = rateLimits.credits;
    let creditValue: string;
    if (c.unlimited) {
      creditValue = "Unlimited";
    } else if (c.balance != null) {
      creditValue = formatInteger(c.balance);
    } else if (c.hasCredits === false) {
      creditValue = "None";
    } else {
      creditValue = "—";
    }
    cards.push({ label: "credits", value: creditValue, detail: "" });
  }

  // Fallback: any additional flat scalar fields not already handled
  const handled = new Set([
    "credits",
    "limitId",
    "limitName",
    "planType",
    "primary",
    "secondary"
  ]);
  for (const [key, value] of Object.entries(rateLimits)) {
    if (
      handled.has(key) ||
      value === null ||
      value === undefined ||
      typeof value === "object"
    )
      continue;
    cards.push({
      label: key.replaceAll("_", " "),
      value: typeof value === "number" ? formatInteger(value) : String(value),
      detail: ""
    });
  }

  return cards;
}

function formatWindowMins(mins: number | null | undefined): string {
  if (mins == null) return "";
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function presentRunningRow(
  row: RuntimeRunningEntryApiResponse
): RuntimeActivityRowViewModel {
  return {
    identifier: row.issue_identifier,
    issueId: row.issue_id,
    state: row.state,
    session: row.session_id ?? "Session pending",
    lastEvent: row.last_event ?? "No event yet",
    lastMessage: row.last_message ?? "No message yet",
    lastMessageRaw: row.last_message ?? "",
    startedAt: formatTimestamp(row.started_at),
    updatedAt: formatTimestamp(row.last_event_at),
    workspacePath: row.workspace_path ?? "Unavailable",
    attemptLabel:
      row.attempt === null
        ? "Initial run"
        : `Retry ${formatInteger(row.attempt)}`,
    tokenSummary: formatTokenSummary(row.tokens)
  };
}

function formatAttemptSummary(snapshot: RuntimeIssueApiResponse): string {
  const restartCount = snapshot.attempts.restart_count ?? 0;
  const currentRetryAttempt = snapshot.attempts.current_retry_attempt;

  if (currentRetryAttempt === null) {
    if (restartCount <= 0) {
      return "Initial run; no retry has been scheduled.";
    }

    return `Restarted ${formatInteger(restartCount)} times; no retry is currently scheduled.`;
  }

  return `Restarted ${formatInteger(restartCount)} times; current retry attempt ${formatInteger(currentRetryAttempt)}.`;
}

function presentRetryRow(
  row: RuntimeRetryEntryApiResponse
): RuntimeRetryRowViewModel {
  return {
    identifier: row.issue_identifier,
    issueId: row.issue_id,
    attemptLabel:
      row.attempt === null
        ? "Retry pending"
        : `Retry ${formatInteger(row.attempt)}`,
    dueAt: formatTimestamp(row.due_at),
    error: row.error ?? "No retry error recorded.",
    workspacePath: row.workspace_path ?? "Unavailable",
    priorSessionLabel:
      row.prior_session?.session_id ?? "No prior session summary"
  };
}

function presentSessionSummary(input: {
  title: string;
  sessionId: string | null | undefined;
  turnCount: number | null | undefined;
  lastEvent: string | null | undefined;
  lastEventAt: string | null | undefined;
  tokens:
    | {
        input_tokens: number;
        output_tokens: number;
        total_tokens: number;
      }
    | null
    | undefined;
}): IssueSessionSummaryViewModel {
  return {
    title: input.title,
    sessionId: input.sessionId ?? "Unavailable",
    event: input.lastEvent ?? "No event recorded",
    eventAt: formatTimestamp(input.lastEventAt),
    turns:
      input.turnCount === null || input.turnCount === undefined
        ? "Unavailable"
        : formatInteger(input.turnCount),
    tokens: formatTokenSummary(input.tokens)
  };
}
