import { describe, expect, it } from "vitest";

import {
  presentDashboardSnapshot,
  presentIssueSnapshot,
  presentRefreshReceipt,
  presentRunsSnapshot
} from "../src/app/shared/lib/runtime-presenters";
import { describeSnapshotStatus, formatTokenSummary } from "../src/app/shared/lib/runtime-formatters";
import { RuntimeIssueApiResponse, RuntimeStateApiResponse } from "../src/app/shared/lib/runtime-types";

describe("runtime presenters", () => {
  it("presents dashboard state with activity and rate limits", () => {
    const snapshot: RuntimeStateApiResponse = {
      generated_at: "2099-03-10T10:00:00Z",
      expires_at: "2099-03-10T10:05:00Z",
      counts: { running: 1, retrying: 1 },
      running: [
        {
          issue_id: "issue-1",
          issue_identifier: "SYM-1",
          attempt: 2,
          state: "In Progress",
          session_id: "thread-1-turn-2",
          turn_count: 4,
          last_event: "notification",
          last_message: "Implementing tests",
          started_at: "2026-03-10T09:55:00Z",
          last_event_at: "2026-03-10T09:59:00Z",
          workspace_path: "/tmp/SYM-1",
          tokens: {
            input_tokens: 10,
            output_tokens: 5,
            total_tokens: 15
          }
        }
      ],
      retrying: [
        {
          issue_id: "issue-2",
          issue_identifier: "SYM-2",
          attempt: 3,
          due_at: "2026-03-10T10:03:00Z",
          error: "capacity",
          workspace_path: "/tmp/SYM-2",
          prior_session: {
            session_id: "thread-9-turn-1"
          }
        }
      ],
      codex_totals: {
        input_tokens: 10,
        output_tokens: 5,
        total_tokens: 15,
        seconds_running: 120
      },
      rate_limits: {
        requests_remaining: 7
      }
    };

    const result = presentDashboardSnapshot(snapshot);

    expect(result.hasActivity).toBe(true);
    expect(result.activeIssues[0]?.identifier).toBe("SYM-1");
    expect(result.retryQueue[0]?.priorSessionLabel).toBe("thread-9-turn-1");
    expect(result.rateLimits[0]?.value).toBe("7");
    expect(result.statCards).toHaveLength(4);
    expect(result.snapshotStatus).toEqual(
      expect.objectContaining({
        label: "Snapshot live"
      })
    );
  });

  it("presents runs state empty message when nothing is active", () => {
    const snapshot: RuntimeStateApiResponse = {
      generated_at: "2026-03-10T10:00:00Z",
      expires_at: "2026-03-10T10:05:00Z",
      counts: { running: 0, retrying: 0 },
      running: [],
      retrying: [],
      codex_totals: {
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
        seconds_running: 0
      },
      rate_limits: null
    };

    const result = presentRunsSnapshot(snapshot);

    expect(result.activeRuns).toHaveLength(0);
    expect(result.retryQueue).toHaveLength(0);
    expect(result.emptyMessage).toContain("No active runs");
  });

  it("presents issue detail with prior session data", () => {
    const snapshot: RuntimeIssueApiResponse = {
      issue_identifier: "SYM-9",
      issue_id: "issue-9",
      status: "retrying",
      workspace: {
        path: "/tmp/SYM-9"
      },
      attempts: {
        restart_count: 2,
        current_retry_attempt: 3
      },
      running: null,
      retry: {
        attempt: 3,
        due_at: "2026-03-10T10:03:00Z",
        error: "capacity",
        prior_session: {
          session_id: "thread-3-turn-4",
          turn_count: 8,
          last_event: "turn_completed",
          last_event_at: "2026-03-10T09:58:00Z",
          tokens: {
            input_tokens: 30,
            output_tokens: 12,
            total_tokens: 42
          }
        }
      },
      logs: {
        codex_session_logs: []
      },
      recent_events: [],
      last_error: "capacity",
      tracked: {}
    };

    const result = presentIssueSnapshot(snapshot);

    expect(result.identifier).toBe("SYM-9");
    expect(result.previousSession?.sessionId).toBe("thread-3-turn-4");
    expect(result.lastError).toBe("capacity");
  });

  it("presents issue detail without inventing a retry attempt for initial runs", () => {
    const snapshot: RuntimeIssueApiResponse = {
      issue_identifier: "SYM-10",
      issue_id: "issue-10",
      status: "running",
      workspace: {
        path: "/tmp/SYM-10"
      },
      attempts: {
        restart_count: 0,
        current_retry_attempt: null
      },
      running: {
        session_id: "thread-10-turn-1",
        turn_count: 1,
        state: "In Progress",
        started_at: "2026-03-10T10:00:00Z",
        last_event: "turn_started",
        last_message: "Beginning work",
        last_event_at: "2026-03-10T10:00:00Z",
        tokens: {
          input_tokens: 5,
          output_tokens: 0,
          total_tokens: 5
        }
      },
      retry: null,
      logs: {
        codex_session_logs: []
      },
      recent_events: [],
      last_error: null,
      tracked: {}
    };

    const result = presentIssueSnapshot(snapshot);

    expect(result.attemptSummary).toBe("Initial run; no retry has been scheduled.");
  });

  describe("rate limits presenter", () => {
    function makeSnapshot(
      rate_limits: RuntimeStateApiResponse["rate_limits"]
    ): ReturnType<typeof presentDashboardSnapshot> {
      return presentDashboardSnapshot({
        generated_at: "2099-03-10T10:00:00Z",
        expires_at: "2099-03-10T10:05:00Z",
        counts: { running: 0, retrying: 0 },
        running: [],
        retrying: [],
        codex_totals: { input_tokens: 0, output_tokens: 0, total_tokens: 0, seconds_running: 0 },
        rate_limits
      });
    }

    it("returns empty array when rate_limits is null", () => {
      expect(makeSnapshot(null).rateLimits).toHaveLength(0);
      expect(makeSnapshot(null).rateLimitsRawJson).toBeNull();
    });

    it("renders limitName as a stat card", () => {
      const { rateLimits } = makeSnapshot({ limitName: "GPT-5.3-Codex-Spark" });
      const card = rateLimits.find((c) => c.label === "limit name");
      expect(card?.value).toBe("GPT-5.3-Codex-Spark");
    });

    it("renders primary window with usage percent and duration label", () => {
      const { rateLimits } = makeSnapshot({
        primary: { usedPercent: 42, windowDurationMins: 300, resetsAt: null }
      });
      const card = rateLimits.find((c) => c.label === "primary window (5h)");
      expect(card?.value).toBe("42% used");
    });

    it("renders secondary window with usage percent and duration label", () => {
      const { rateLimits } = makeSnapshot({
        secondary: { usedPercent: 10, windowDurationMins: 10080, resetsAt: null }
      });
      const card = rateLimits.find((c) => c.label === "secondary window (7d)");
      expect(card?.value).toBe("10% used");
    });

    it("renders credits as None when hasCredits is false and balance is null", () => {
      const { rateLimits } = makeSnapshot({
        credits: { balance: null, hasCredits: false, unlimited: false }
      });
      expect(rateLimits.find((c) => c.label === "credits")?.value).toBe("None");
    });

    it("renders credits as Unlimited when unlimited is true", () => {
      const { rateLimits } = makeSnapshot({
        credits: { balance: null, hasCredits: true, unlimited: true }
      });
      expect(rateLimits.find((c) => c.label === "credits")?.value).toBe("Unlimited");
    });

    it("renders credits balance as formatted number", () => {
      const { rateLimits } = makeSnapshot({
        credits: { balance: 5000, hasCredits: true, unlimited: false }
      });
      expect(rateLimits.find((c) => c.label === "credits")?.value).toBe("5,000");
    });

    it("never produces [object Object] for nested fields", () => {
      const { rateLimits } = makeSnapshot({
        primary: { usedPercent: 2, windowDurationMins: 300, resetsAt: 1773208408 },
        secondary: { usedPercent: 31, windowDurationMins: 10080, resetsAt: 1773632680 },
        credits: { balance: null, hasCredits: false, unlimited: false }
      });
      for (const card of rateLimits) {
        expect(card.value).not.toContain("[object Object]");
      }
    });

    it("falls back to flat scalar fields not in the known set", () => {
      const { rateLimits } = makeSnapshot({ requests_remaining: 7 });
      expect(rateLimits.find((c) => c.label === "requests remaining")?.value).toBe("7");
    });

    it("skips unknown nested objects in fallback path", () => {
      const { rateLimits } = makeSnapshot({ someObj: { nested: true } } as RuntimeStateApiResponse["rate_limits"]);
      const bad = rateLimits.find((c) => c.value.includes("[object Object]"));
      expect(bad).toBeUndefined();
    });

    it("populates rateLimitsRawJson with formatted JSON string", () => {
      const { rateLimitsRawJson } = makeSnapshot({ limitName: "Test", primary: { usedPercent: 5, windowDurationMins: 60, resetsAt: null } });
      expect(rateLimitsRawJson).not.toBeNull();
      expect(() => JSON.parse(rateLimitsRawJson!)).not.toThrow();
      expect(JSON.parse(rateLimitsRawJson!)).toMatchObject({ limitName: "Test" });
    });
  });

  describe("running row presenter", () => {
    it("populates lastMessageRaw from last_message", () => {
      const raw = JSON.stringify({ method: "item/started", params: { threadId: "abc" } });
      const result = presentDashboardSnapshot({
        generated_at: "2099-03-10T10:00:00Z",
        expires_at: "2099-03-10T10:05:00Z",
        counts: { running: 1, retrying: 0 },
        running: [
          {
            issue_id: "issue-1",
            issue_identifier: "SYM-1",
            attempt: null,
            state: "running",
            session_id: "s1",
            turn_count: 1,
            last_event: "item/started",
            last_message: raw,
            started_at: "2099-03-10T10:00:00Z",
            last_event_at: "2099-03-10T10:00:00Z",
            workspace_path: "/tmp/SYM-1",
            tokens: null
          }
        ],
        retrying: [],
        codex_totals: { input_tokens: 0, output_tokens: 0, total_tokens: 0, seconds_running: 0 },
        rate_limits: null
      });

      expect(result.activeIssues[0]?.lastMessageRaw).toBe(raw);
      expect(result.activeIssues[0]?.lastEvent).toBe("item/started");
    });

    it("sets lastMessageRaw to empty string when last_message is null", () => {
      const result = presentDashboardSnapshot({
        generated_at: "2099-03-10T10:00:00Z",
        expires_at: "2099-03-10T10:05:00Z",
        counts: { running: 1, retrying: 0 },
        running: [
          {
            issue_id: "issue-1",
            issue_identifier: "SYM-1",
            attempt: null,
            state: "running",
            session_id: null,
            turn_count: null,
            last_event: null,
            last_message: null,
            started_at: null,
            last_event_at: null,
            workspace_path: null,
            tokens: null
          }
        ],
        retrying: [],
        codex_totals: { input_tokens: 0, output_tokens: 0, total_tokens: 0, seconds_running: 0 },
        rate_limits: null
      });

      expect(result.activeIssues[0]?.lastMessageRaw).toBe("");
    });
  });

  it("presents refresh receipts and freshness states", () => {
    expect(
      presentRefreshReceipt({
        queued: true,
        coalesced: false,
        requested_at: "2026-03-10T10:01:00Z",
        operations: ["poll", "reconcile"]
      }).operationsLabel
    ).toBe("poll + reconcile");

    expect(
      describeSnapshotStatus("2026-03-10T10:00:00Z", "2026-03-10T10:05:00Z", Date.parse("2026-03-10T10:02:00Z")).label
    ).toBe("Snapshot live");
    expect(
      describeSnapshotStatus("2026-03-10T10:00:00Z", "2026-03-10T10:00:30Z", Date.parse("2026-03-10T10:00:10Z")).tone
    ).toBe("warning");
    expect(formatTokenSummary(null)).toContain("No token usage");
  });
});
