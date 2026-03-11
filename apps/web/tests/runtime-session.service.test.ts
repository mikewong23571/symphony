import { DestroyRef } from "@angular/core";
import { of, throwError } from "rxjs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RuntimeApiService } from "../src/app/shared/api/runtime-api.service";
import {
  computeRuntimeRefreshDelay,
  parseRuntimeInvalidationEvent,
  RuntimeSessionService
} from "../src/app/shared/api/runtime-session.service";
import {
  RefreshReceiptViewModel,
  RuntimeIssueApiResponse,
  RuntimeStateApiResponse
} from "../src/app/shared/lib/runtime-types";

class FakeEventTarget {
  private readonly listeners = new Map<string, Set<(event: Event) => void>>();

  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    const callback =
      typeof listener === "function"
        ? listener
        : (event: Event) => listener.handleEvent(event);
    const listeners = this.listeners.get(type) ?? new Set<(event: Event) => void>();
    listeners.add(callback);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    const listeners = this.listeners.get(type);
    if (!listeners) {
      return;
    }
    const callback =
      typeof listener === "function"
        ? listener
        : (event: Event) => listener.handleEvent(event);
    listeners.delete(callback);
    if (listeners.size === 0) {
      this.listeners.delete(type);
    }
  }

  dispatch(type: string): void {
    const listeners = this.listeners.get(type);
    if (!listeners) {
      return;
    }
    for (const listener of listeners) {
      listener(new Event(type));
    }
  }
}

class FakeDocument extends FakeEventTarget {
  visibilityState: DocumentVisibilityState = "visible";
}

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  private readonly listeners = new Map<string, Set<(event: Event) => void>>();
  closed = false;

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    const callback =
      typeof listener === "function"
        ? listener
        : (event: Event) => listener.handleEvent(event);
    const listeners = this.listeners.get(type) ?? new Set<(event: Event) => void>();
    listeners.add(callback);
    this.listeners.set(type, listeners);
  }

  emit(type: string, payload: object): void {
    const listeners = this.listeners.get(type);
    if (!listeners) {
      return;
    }
    const event = { data: JSON.stringify(payload) } as MessageEvent<string>;
    for (const listener of listeners) {
      listener(event);
    }
  }

  close(): void {
    this.closed = true;
  }
}

type TestDestroyRef = Pick<DestroyRef, "onDestroy"> & { destroy: () => void };

type FakeRuntimeApi = {
  loadStateSnapshot: ReturnType<typeof vi.fn>;
  loadIssueSnapshot: ReturnType<typeof vi.fn>;
  requestRefresh: ReturnType<typeof vi.fn>;
};

describe("RuntimeSessionService", () => {
  let fakeWindow: FakeEventTarget;
  let fakeDocument: FakeDocument;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-11T12:00:00Z"));
    FakeEventSource.instances = [];
    fakeWindow = new FakeEventTarget();
    fakeDocument = new FakeDocument();
    vi.stubGlobal("window", fakeWindow);
    vi.stubGlobal("document", fakeDocument);
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("computes the next refresh delay from expires_at", () => {
    expect(
      computeRuntimeRefreshDelay("2026-03-11T12:00:10Z")
    ).toBe(10_000);
    expect(computeRuntimeRefreshDelay("not-a-date")).toBe(5_000);
  });

  it("parses invalidation payloads and filters invalid identifiers", () => {
    expect(
      parseRuntimeInvalidationEvent(
        JSON.stringify({
          sequence: 3,
          event: "issue_changed",
          emitted_at: "2026-03-11T12:00:00Z",
          revision: 7,
          issue_identifiers: ["SYM-1", "", 42]
        })
      )
    ).toEqual({
      sequence: 3,
      event: "issue_changed",
      emitted_at: "2026-03-11T12:00:00Z",
      revision: 7,
      issue_identifiers: ["SYM-1"]
    });
    expect(parseRuntimeInvalidationEvent("bad json")).toBeNull();
  });

  it("loads state immediately and schedules the next refresh from expires_at", () => {
    const api = createRuntimeApi({
      stateSnapshots: [
        makeStateSnapshot({ revision: 1, expiresAt: "2026-03-11T12:00:10Z" }),
        makeStateSnapshot({ revision: 2, expiresAt: "2026-03-11T12:00:25Z" })
      ]
    });
    const service = new RuntimeSessionService(api as unknown as RuntimeApiService);
    const destroyRef = createDestroyRef();

    const resource = service.watchState(destroyRef);

    expect(api.loadStateSnapshot).toHaveBeenCalledTimes(1);
    expect(resource.loadState().snapshot?.revision).toBe(1);

    vi.advanceTimersByTime(10_000);

    expect(api.loadStateSnapshot).toHaveBeenCalledTimes(2);
    expect(resource.loadState().snapshot?.revision).toBe(2);

    destroyRef.destroy();
  });

  it("refreshes active resources on focus recovery", () => {
    const api = createRuntimeApi({
      stateSnapshots: [
        makeStateSnapshot({ revision: 1, expiresAt: "2026-03-11T12:10:00Z" }),
        makeStateSnapshot({ revision: 2, expiresAt: "2026-03-11T12:20:00Z" })
      ]
    });
    const service = new RuntimeSessionService(api as unknown as RuntimeApiService);
    const destroyRef = createDestroyRef();

    service.watchState(destroyRef);
    fakeWindow.dispatch("focus");

    expect(api.loadStateSnapshot).toHaveBeenCalledTimes(2);

    destroyRef.destroy();
  });

  it("refreshes active resources when the page becomes visible again", () => {
    const api = createRuntimeApi({
      stateSnapshots: [
        makeStateSnapshot({ revision: 1, expiresAt: "2026-03-11T12:10:00Z" }),
        makeStateSnapshot({ revision: 2, expiresAt: "2026-03-11T12:20:00Z" })
      ]
    });
    const service = new RuntimeSessionService(api as unknown as RuntimeApiService);
    const destroyRef = createDestroyRef();

    service.watchState(destroyRef);

    fakeDocument.visibilityState = "hidden";
    fakeDocument.dispatch("visibilitychange");
    expect(api.loadStateSnapshot).toHaveBeenCalledTimes(1);

    fakeDocument.visibilityState = "visible";
    fakeDocument.dispatch("visibilitychange");
    expect(api.loadStateSnapshot).toHaveBeenCalledTimes(2);

    destroyRef.destroy();
  });

  it("revalidates state only when SSE announces a newer revision", () => {
    const api = createRuntimeApi({
      stateSnapshots: [
        makeStateSnapshot({ revision: 2, expiresAt: "2026-03-11T12:10:00Z" }),
        makeStateSnapshot({ revision: 3, expiresAt: "2026-03-11T12:20:00Z" })
      ]
    });
    const service = new RuntimeSessionService(api as unknown as RuntimeApiService);
    const destroyRef = createDestroyRef();

    service.watchState(destroyRef);
    const eventSource = FakeEventSource.instances[0];

    eventSource.emit("snapshot_updated", {
      sequence: 1,
      event: "snapshot_updated",
      emitted_at: "2026-03-11T12:00:00Z",
      revision: 2
    });
    expect(api.loadStateSnapshot).toHaveBeenCalledTimes(1);

    eventSource.emit("snapshot_updated", {
      sequence: 2,
      event: "snapshot_updated",
      emitted_at: "2026-03-11T12:00:01Z",
      revision: 3
    });
    expect(api.loadStateSnapshot).toHaveBeenCalledTimes(2);

    destroyRef.destroy();
    expect(eventSource.closed).toBe(true);
  });

  it("refreshes active resources and reconnects when the SSE stream errors", () => {
    const api = createRuntimeApi({
      stateSnapshots: [
        makeStateSnapshot({ revision: 2, expiresAt: "2026-03-11T12:10:00Z" }),
        makeStateSnapshot({ revision: 2, expiresAt: "2026-03-11T12:10:00Z" }),
        makeStateSnapshot({ revision: 2, expiresAt: "2026-03-11T12:10:00Z" }),
        makeStateSnapshot({ revision: 3, expiresAt: "2026-03-11T12:20:00Z" })
      ]
    });
    const service = new RuntimeSessionService(api as unknown as RuntimeApiService);
    const destroyRef = createDestroyRef();

    const resource = service.watchState(destroyRef);
    const firstEventSource = FakeEventSource.instances[0];

    firstEventSource.emit("error", {});
    expect(api.loadStateSnapshot).toHaveBeenCalledTimes(2);
    expect(firstEventSource.closed).toBe(true);

    vi.advanceTimersByTime(1_000);
    expect(api.loadStateSnapshot).toHaveBeenCalledTimes(3);
    expect(FakeEventSource.instances).toHaveLength(2);

    const secondEventSource = FakeEventSource.instances[1];
    secondEventSource.emit("snapshot_updated", {
      sequence: 2,
      event: "snapshot_updated",
      emitted_at: "2026-03-11T12:00:01Z",
      revision: 3
    });
    expect(api.loadStateSnapshot).toHaveBeenCalledTimes(4);
    expect(resource.loadState().snapshot?.revision).toBe(3);

    destroyRef.destroy();
    expect(secondEventSource.closed).toBe(true);
  });

  it("recovers from failed refreshes and allows later triggers to fetch again", () => {
    let loadCount = 0;
    const api = {
      loadStateSnapshot: vi.fn(() => {
        loadCount += 1;
        if (loadCount === 1) {
          return of(makeStateSnapshot({ revision: 1, expiresAt: "2026-03-11T12:10:00Z" }));
        }
        if (loadCount === 2) {
          return throwError(() => ({
            kind: "http",
            code: "unavailable",
            message: "snapshot unavailable",
            status: 503
          }));
        }
        return of(makeStateSnapshot({ revision: 2, expiresAt: "2026-03-11T12:20:00Z" }));
      }),
      loadIssueSnapshot: vi.fn(),
      requestRefresh: vi.fn(() =>
        of({
          queuedLabel: "Refresh request queued.",
          requestedAt: "Mar 11, 2026, 12:00 PM",
          operationsLabel: "poll + reconcile"
        } satisfies RefreshReceiptViewModel)
      )
    };
    const service = new RuntimeSessionService(api as unknown as RuntimeApiService);
    const destroyRef = createDestroyRef();
    const resource = service.watchState(destroyRef);

    fakeWindow.dispatch("focus");
    expect(api.loadStateSnapshot).toHaveBeenCalledTimes(2);
    expect(resource.loadState().error?.message).toBe("snapshot unavailable");

    fakeWindow.dispatch("focus");
    expect(api.loadStateSnapshot).toHaveBeenCalledTimes(3);
    expect(resource.loadState().snapshot?.revision).toBe(2);
    expect(resource.loadState().error).toBeNull();

    destroyRef.destroy();
  });

  it("refreshes only matching issue resources for issue_changed events", () => {
    const api = createRuntimeApi({
      issueSnapshots: {
        "SYM-1": [
          makeIssueSnapshot({
            identifier: "SYM-1",
            revision: 1,
            expiresAt: "2026-03-11T12:10:00Z"
          })
        ],
        "SYM-2": [
          makeIssueSnapshot({
            identifier: "SYM-2",
            revision: 1,
            expiresAt: "2026-03-11T12:10:00Z"
          }),
          makeIssueSnapshot({
            identifier: "SYM-2",
            revision: 2,
            expiresAt: "2026-03-11T12:20:00Z"
          })
        ]
      }
    });
    const service = new RuntimeSessionService(api as unknown as RuntimeApiService);
    const issueOne = service.connectIssue("SYM-1");
    const issueTwo = service.connectIssue("SYM-2");
    const eventSource = FakeEventSource.instances[0];

    expect(api.loadIssueSnapshot).toHaveBeenCalledTimes(2);

    eventSource.emit("issue_changed", {
      sequence: 1,
      event: "issue_changed",
      emitted_at: "2026-03-11T12:00:00Z",
      revision: 2,
      issue_identifiers: ["SYM-2"]
    });

    expect(api.loadIssueSnapshot).toHaveBeenCalledTimes(3);
    expect(issueOne.loadState().snapshot?.revision).toBe(1);
    expect(issueTwo.loadState().snapshot?.revision).toBe(2);

    issueOne.destroy();
    issueTwo.destroy();
  });

  it("requests a backend refresh and then revalidates active resources", () => {
    const api = createRuntimeApi({
      stateSnapshots: [
        makeStateSnapshot({ revision: 1, expiresAt: "2026-03-11T12:10:00Z" }),
        makeStateSnapshot({ revision: 2, expiresAt: "2026-03-11T12:20:00Z" })
      ]
    });
    const service = new RuntimeSessionService(api as unknown as RuntimeApiService);
    const destroyRef = createDestroyRef();

    service.watchState(destroyRef);
    let receipt: RefreshReceiptViewModel | null = null;
    service.requestRefresh().subscribe((value) => {
      receipt = value;
    });

    expect(api.requestRefresh).toHaveBeenCalledTimes(1);
    expect(api.loadStateSnapshot).toHaveBeenCalledTimes(2);
    expect(receipt?.queuedLabel).toBe("Refresh request queued.");

    destroyRef.destroy();
  });
});

function createRuntimeApi(input: {
  stateSnapshots?: RuntimeStateApiResponse[];
  issueSnapshots?: Record<string, RuntimeIssueApiResponse[]>;
}): FakeRuntimeApi {
  const stateSnapshots = [...(input.stateSnapshots ?? [])];
  const issueSnapshots = new Map(
    Object.entries(input.issueSnapshots ?? {}).map(([key, value]) => [key, [...value]])
  );

  return {
    loadStateSnapshot: vi.fn(() => of(stateSnapshots.shift() ?? stateSnapshots.at(-1)!)),
    loadIssueSnapshot: vi.fn((issueIdentifier: string) =>
      of(
        issueSnapshots.get(issueIdentifier)?.shift() ??
          issueSnapshots.get(issueIdentifier)?.at(-1)!
      )
    ),
    requestRefresh: vi.fn(() =>
      of({
        queuedLabel: "Refresh request queued.",
        requestedAt: "Mar 11, 2026, 12:00 PM",
        operationsLabel: "poll + reconcile"
      } satisfies RefreshReceiptViewModel)
    )
  };
}

function createDestroyRef(): TestDestroyRef {
  const callbacks: Array<() => void> = [];
  return {
    onDestroy(callback: () => void) {
      callbacks.push(callback);
    },
    destroy() {
      while (callbacks.length > 0) {
        callbacks.pop()?.();
      }
    }
  };
}

function makeStateSnapshot(input: {
  revision: number;
  expiresAt: string;
}): RuntimeStateApiResponse {
  return {
    revision: input.revision,
    generated_at: "2026-03-11T12:00:00Z",
    expires_at: input.expiresAt,
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
}

function makeIssueSnapshot(input: {
  identifier: string;
  revision: number;
  expiresAt: string;
}): RuntimeIssueApiResponse {
  return {
    revision: input.revision,
    generated_at: "2026-03-11T12:00:00Z",
    expires_at: input.expiresAt,
    issue_identifier: input.identifier,
    issue_id: `${input.identifier}-id`,
    status: "running",
    workspace: { path: `/tmp/${input.identifier}` },
    attempts: {
      restart_count: 0,
      current_retry_attempt: null
    },
    running: {
      session_id: `${input.identifier}-session`,
      turn_count: 1,
      state: "In Progress",
      started_at: "2026-03-11T11:59:00Z",
      last_event: "notification",
      last_message: "Working",
      last_event_at: "2026-03-11T12:00:00Z",
      tokens: {
        input_tokens: 1,
        output_tokens: 2,
        total_tokens: 3
      }
    },
    retry: null,
    logs: { codex_session_logs: [] },
    recent_events: [],
    last_error: null,
    tracked: {}
  };
}
