import { HttpClient, HttpErrorResponse } from "@angular/common/http";
import { Injectable, inject } from "@angular/core";
import { Observable, catchError, map, throwError } from "rxjs";

import {
  DashboardViewModel,
  IssueDetailViewModel,
  RefreshReceiptViewModel,
  RunsViewModel,
  RuntimeApiErrorEnvelope,
  RuntimeIssueApiResponse,
  RuntimeRefreshApiResponse,
  RuntimeStateApiResponse,
  RuntimeUiError
} from "../lib/runtime-types";
import {
  presentDashboardSnapshot,
  presentIssueSnapshot,
  presentRefreshReceipt,
  presentRunsSnapshot
} from "../lib/runtime-presenters";

@Injectable({ providedIn: "root" })
export class RuntimeApiService {
  private readonly http = inject(HttpClient);

  loadStateSnapshot(): Observable<RuntimeStateApiResponse> {
    return this.http
      .get<RuntimeStateApiResponse>("/api/v1/state")
      .pipe(
        catchError((error: unknown) =>
          throwError(() => toRuntimeUiError(error))
        )
      );
  }

  loadDashboard(): Observable<DashboardViewModel> {
    return this.loadStateSnapshot().pipe(
      map((response) => presentDashboardSnapshot(response))
    );
  }

  loadRuns(): Observable<RunsViewModel> {
    return this.loadStateSnapshot().pipe(
      map((response) => presentRunsSnapshot(response))
    );
  }

  loadIssueSnapshot(
    issueIdentifier: string
  ): Observable<RuntimeIssueApiResponse> {
    return this.http
      .get<RuntimeIssueApiResponse>(
        `/api/v1/${encodeURIComponent(issueIdentifier)}`
      )
      .pipe(
        catchError((error: unknown) =>
          throwError(() => toRuntimeUiError(error))
        )
      );
  }

  loadIssue(issueIdentifier: string): Observable<IssueDetailViewModel> {
    return this.loadIssueSnapshot(issueIdentifier).pipe(
      map((response) => presentIssueSnapshot(response))
    );
  }

  requestRefresh(): Observable<RefreshReceiptViewModel> {
    return this.http
      .post<RuntimeRefreshApiResponse>("/api/v1/refresh", {})
      .pipe(
        map((response) => presentRefreshReceipt(response)),
        catchError((error: unknown) =>
          throwError(() => toRuntimeUiError(error))
        )
      );
  }
}

export function toRuntimeUiError(error: unknown): RuntimeUiError {
  if (!(error instanceof HttpErrorResponse)) {
    return {
      kind: "unexpected",
      code: "unexpected",
      message:
        "An unexpected frontend error prevented the runtime view from loading.",
      status: null
    };
  }

  const envelope = isRuntimeApiErrorEnvelope(error.error) ? error.error : null;
  const code = envelope?.error.code ?? "unexpected";
  const message =
    envelope?.error.message ?? error.message ?? "Unknown API failure.";

  if (code === "issue_not_found") {
    return {
      kind: "issue_not_found",
      code,
      message,
      status: error.status || null
    };
  }

  if (code === "timeout") {
    return {
      kind: "timeout",
      code,
      message,
      status: error.status || null
    };
  }

  if (code === "unavailable" && message.toLowerCase().includes("stale")) {
    return {
      kind: "stale",
      code,
      message,
      status: error.status || null
    };
  }

  if (code === "unavailable" || error.status === 0 || error.status >= 500) {
    return {
      kind: "unavailable",
      code,
      message,
      status: error.status || null
    };
  }

  return {
    kind: "unexpected",
    code,
    message,
    status: error.status || null
  };
}

function isRuntimeApiErrorEnvelope(
  value: unknown
): value is RuntimeApiErrorEnvelope {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Partial<RuntimeApiErrorEnvelope>;
  return (
    !!candidate.error &&
    typeof candidate.error.code === "string" &&
    typeof candidate.error.message === "string"
  );
}
