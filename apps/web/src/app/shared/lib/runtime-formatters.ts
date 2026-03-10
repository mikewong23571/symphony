const dateTimeFormatter = new Intl.DateTimeFormat("en", {
  dateStyle: "medium",
  timeStyle: "short"
});

const integerFormatter = new Intl.NumberFormat("en");

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "Unavailable";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return dateTimeFormatter.format(parsed);
}

export function formatInteger(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "0";
  }

  return integerFormatter.format(value);
}

export function formatDurationSeconds(
  value: number | null | undefined
): string {
  if (typeof value !== "number" || Number.isNaN(value) || value <= 0) {
    return "0m";
  }

  if (value < 60) {
    return `${Math.round(value)}s`;
  }

  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);

  if (hours <= 0) {
    return `${minutes}m`;
  }

  return `${hours}h ${minutes}m`;
}

export function formatTokenSummary(
  tokens:
    | {
        input_tokens: number;
        output_tokens: number;
        total_tokens: number;
      }
    | null
    | undefined
): string {
  if (!tokens) {
    return "No token usage reported";
  }

  return `${formatInteger(tokens.total_tokens)} total (${formatInteger(tokens.input_tokens)} in / ${formatInteger(tokens.output_tokens)} out)`;
}

export function describeSnapshotStatus(
  generatedAt: string,
  expiresAt: string,
  now = Date.now()
): {
  label: string;
  tone: "live" | "warning" | "danger";
  detail: string;
} {
  const expires = new Date(expiresAt).getTime();
  const generated = new Date(generatedAt).getTime();

  if (Number.isNaN(expires) || Number.isNaN(generated)) {
    return {
      label: "Timestamp parsing failed",
      tone: "danger",
      detail:
        "The backend returned a snapshot without valid freshness timestamps."
    };
  }

  const remainingSeconds = Math.round((expires - now) / 1000);
  if (remainingSeconds <= 0) {
    return {
      label: "Snapshot expired",
      tone: "danger",
      detail: `Generated ${formatTimestamp(generatedAt)} and expired ${formatTimestamp(expiresAt)}.`
    };
  }

  if (remainingSeconds <= 60) {
    return {
      label: "Snapshot nearly stale",
      tone: "warning",
      detail: `Refresh due within ${remainingSeconds}s.`
    };
  }

  return {
    label: "Snapshot live",
    tone: "live",
    detail: `Generated ${formatTimestamp(generatedAt)} and valid until ${formatTimestamp(expiresAt)}.`
  };
}
