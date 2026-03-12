import {
  DestroyRef,
  Injectable,
  Signal,
  WritableSignal,
  signal
} from "@angular/core";
import { Observable, Subscription, tap } from "rxjs";

import { RuntimeApiService } from "./runtime-api.service";
import {
  RefreshReceiptViewModel,
  RuntimeInvalidationEvent,
  RuntimeIssueApiResponse,
  RuntimeLoadState,
  RuntimeStateApiResponse,
  RuntimeUiError
} from "../lib/runtime-types";

const FALLBACK_REFRESH_DELAY_MS = 5_000;
const EVENT_STREAM_RECONNECT_DELAY_MS = 1_000;
const RUNTIME_EVENTS_URL = "/api/v1/events";

type RuntimeManagedSnapshot = RuntimeStateApiResponse | RuntimeIssueApiResponse;

type RuntimeManagedResource<TSnapshot extends RuntimeManagedSnapshot> = {
  key: string;
  loadSnapshot: () => Observable<TSnapshot>;
  loadState: WritableSignal<RuntimeLoadState<TSnapshot>>;
  watchCount: number;
  timerHandle: ReturnType<typeof globalThis.setTimeout> | null;
  requestSubscription: Subscription | null;
  refreshQueued: boolean;
};

export interface RuntimeResourceHandle<
  TSnapshot extends RuntimeManagedSnapshot
> {
  loadState: Signal<RuntimeLoadState<TSnapshot>>;
  refresh: () => void;
}

export interface RuntimeResourceConnection<
  TSnapshot extends RuntimeManagedSnapshot
> extends RuntimeResourceHandle<TSnapshot> {
  destroy: () => void;
}

@Injectable({ providedIn: "root" })
export class RuntimeSessionService {
  private readonly stateResource: RuntimeManagedResource<RuntimeStateApiResponse>;
  private readonly issueResources = new Map<
    string,
    RuntimeManagedResource<RuntimeIssueApiResponse>
  >();
  private readonly focusListener = () => this.refreshActiveResources();
  private readonly visibilityListener = () => {
    const browserDocument = getBrowserDocument();
    if (!browserDocument || browserDocument.visibilityState === "visible") {
      this.refreshActiveResources();
    }
  };
  private readonly eventListener = (event: Event) => {
    const messageEvent = event as MessageEvent<string>;
    const invalidation = parseRuntimeInvalidationEvent(messageEvent.data);
    if (invalidation) {
      this.handleInvalidation(invalidation);
    }
  };
  private readonly eventErrorListener = () => this.handleEventStreamError();
  private browserListenersActive = false;
  private eventSource: EventSource | null = null;
  private eventSourceReconnectHandle: ReturnType<
    typeof globalThis.setTimeout
  > | null = null;

  constructor(private readonly api: RuntimeApiService) {
    this.stateResource = this.createResource("state", () =>
      this.api.loadStateSnapshot()
    );
  }

  watchState(
    destroyRef: Pick<DestroyRef, "onDestroy">
  ): RuntimeResourceHandle<RuntimeStateApiResponse> {
    return this.attachResource(this.stateResource, destroyRef);
  }

  watchIssue(
    issueIdentifier: string,
    destroyRef: Pick<DestroyRef, "onDestroy">
  ): RuntimeResourceHandle<RuntimeIssueApiResponse> {
    const connection = this.connectIssue(issueIdentifier);
    destroyRef.onDestroy(connection.destroy);
    return connection;
  }

  connectIssue(
    issueIdentifier: string
  ): RuntimeResourceConnection<RuntimeIssueApiResponse> {
    const existingResource = this.issueResources.get(issueIdentifier);
    const resource =
      existingResource ?? this.createIssueResource(issueIdentifier);
    return this.connectResource(resource);
  }

  requestRefresh(): Observable<RefreshReceiptViewModel> {
    return this.api
      .requestRefresh()
      .pipe(tap(() => this.refreshActiveResources()));
  }

  private createIssueResource(
    issueIdentifier: string
  ): RuntimeManagedResource<RuntimeIssueApiResponse> {
    const resource = this.createResource(issueIdentifier, () =>
      this.api.loadIssueSnapshot(issueIdentifier)
    );
    this.issueResources.set(issueIdentifier, resource);
    return resource;
  }

  private createResource<TSnapshot extends RuntimeManagedSnapshot>(
    key: string,
    loadSnapshot: () => Observable<TSnapshot>
  ): RuntimeManagedResource<TSnapshot> {
    return {
      key,
      loadSnapshot,
      loadState: signal<RuntimeLoadState<TSnapshot>>({
        snapshot: null,
        error: null,
        initialLoadPending: true,
        refreshPending: false
      }),
      watchCount: 0,
      timerHandle: null,
      requestSubscription: null,
      refreshQueued: false
    };
  }

  private attachResource<TSnapshot extends RuntimeManagedSnapshot>(
    resource: RuntimeManagedResource<TSnapshot>,
    destroyRef: Pick<DestroyRef, "onDestroy">
  ): RuntimeResourceHandle<TSnapshot> {
    const connection = this.connectResource(resource);
    destroyRef.onDestroy(connection.destroy);
    return connection;
  }

  private connectResource<TSnapshot extends RuntimeManagedSnapshot>(
    resource: RuntimeManagedResource<TSnapshot>
  ): RuntimeResourceConnection<TSnapshot> {
    resource.watchCount += 1;
    this.ensureBrowserSubscriptions();
    this.fetchResource(resource);
    return {
      loadState: resource.loadState.asReadonly(),
      refresh: () => this.fetchResource(resource),
      destroy: () => this.detachResource(resource)
    };
  }

  private detachResource<TSnapshot extends RuntimeManagedSnapshot>(
    resource: RuntimeManagedResource<TSnapshot>
  ): void {
    resource.watchCount = Math.max(resource.watchCount - 1, 0);
    if (resource.watchCount > 0) {
      return;
    }

    this.clearResourceTimer(resource);
    resource.requestSubscription?.unsubscribe();
    resource.requestSubscription = null;
    resource.refreshQueued = false;
    if (resource !== this.stateResource) {
      this.issueResources.delete(resource.key);
    }
    this.teardownBrowserSubscriptionsIfIdle();
  }

  private fetchResource<TSnapshot extends RuntimeManagedSnapshot>(
    resource: RuntimeManagedResource<TSnapshot>
  ): void {
    if (resource.watchCount <= 0) {
      return;
    }

    if (resource.requestSubscription) {
      resource.refreshQueued = true;
      return;
    }

    const current = resource.loadState();
    resource.loadState.set({
      snapshot: current.snapshot,
      error: null,
      initialLoadPending: current.snapshot === null,
      refreshPending: current.snapshot !== null
    });
    this.clearResourceTimer(resource);

    let requestSubscription: Subscription | null = null;
    requestSubscription = resource.loadSnapshot().subscribe({
      next: (snapshot) => {
        resource.loadState.set({
          snapshot,
          error: null,
          initialLoadPending: false,
          refreshPending: false
        });
        this.scheduleRefresh(resource, snapshot.expires_at);
      },
      error: (error) => {
        if (resource.requestSubscription === requestSubscription) {
          resource.requestSubscription = null;
        }
        resource.loadState.update((state) => ({
          snapshot: state.snapshot,
          error: error as RuntimeUiError,
          initialLoadPending: false,
          refreshPending: false
        }));
        this.scheduleRefresh(resource, null);
      },
      complete: () => {
        if (resource.requestSubscription === requestSubscription) {
          resource.requestSubscription = null;
        }
        if (resource.refreshQueued) {
          resource.refreshQueued = false;
          this.fetchResource(resource);
        }
      }
    });
    resource.requestSubscription = requestSubscription.closed
      ? null
      : requestSubscription;
  }

  private scheduleRefresh<TSnapshot extends RuntimeManagedSnapshot>(
    resource: RuntimeManagedResource<TSnapshot>,
    expiresAt: string | null
  ): void {
    if (resource.watchCount <= 0) {
      return;
    }

    const delayMs = computeRuntimeRefreshDelay(expiresAt);
    resource.timerHandle = globalThis.setTimeout(() => {
      resource.timerHandle = null;
      this.fetchResource(resource);
    }, delayMs);
  }

  private clearResourceTimer<TSnapshot extends RuntimeManagedSnapshot>(
    resource: RuntimeManagedResource<TSnapshot>
  ): void {
    if (resource.timerHandle !== null) {
      globalThis.clearTimeout(resource.timerHandle);
      resource.timerHandle = null;
    }
  }

  private refreshActiveResources(): void {
    if (this.stateResource.watchCount > 0) {
      this.fetchResource(this.stateResource);
    }
    for (const resource of this.issueResources.values()) {
      if (resource.watchCount > 0) {
        this.fetchResource(resource);
      }
    }
  }

  private ensureBrowserSubscriptions(): void {
    if (!this.browserListenersActive) {
      const browserWindow = getBrowserWindow();
      const browserDocument = getBrowserDocument();
      browserWindow?.addEventListener("focus", this.focusListener);
      browserDocument?.addEventListener(
        "visibilitychange",
        this.visibilityListener
      );
      this.browserListenersActive = true;
    }

    if (this.eventSource || this.activeWatcherCount() <= 0) {
      return;
    }

    const EventSourceCtor = getEventSourceConstructor();
    if (!EventSourceCtor) {
      return;
    }

    const eventSource = new EventSourceCtor(RUNTIME_EVENTS_URL);
    eventSource.addEventListener("snapshot_updated", this.eventListener);
    eventSource.addEventListener("issue_changed", this.eventListener);
    eventSource.addEventListener("refresh_queued", this.eventListener);
    eventSource.addEventListener("error", this.eventErrorListener);
    this.eventSource = eventSource;
  }

  private teardownBrowserSubscriptionsIfIdle(): void {
    if (this.activeWatcherCount() > 0) {
      return;
    }

    if (this.browserListenersActive) {
      const browserWindow = getBrowserWindow();
      const browserDocument = getBrowserDocument();
      browserWindow?.removeEventListener("focus", this.focusListener);
      browserDocument?.removeEventListener(
        "visibilitychange",
        this.visibilityListener
      );
      this.browserListenersActive = false;
    }

    if (this.eventSourceReconnectHandle !== null) {
      globalThis.clearTimeout(this.eventSourceReconnectHandle);
      this.eventSourceReconnectHandle = null;
    }
    this.eventSource?.close();
    this.eventSource = null;
  }

  private activeWatcherCount(): number {
    let watcherCount = this.stateResource.watchCount;
    for (const resource of this.issueResources.values()) {
      watcherCount += resource.watchCount;
    }
    return watcherCount;
  }

  private handleInvalidation(event: RuntimeInvalidationEvent): void {
    const issueIdentifiers = event.issue_identifiers ?? [];
    const revision = typeof event.revision === "number" ? event.revision : null;
    const stateRevision = getSnapshotRevision(
      this.stateResource.loadState().snapshot
    );

    if (
      this.stateResource.watchCount > 0 &&
      shouldRefreshForRevision(stateRevision, revision)
    ) {
      this.fetchResource(this.stateResource);
    }

    if (issueIdentifiers.length === 0) {
      for (const resource of this.issueResources.values()) {
        const issueRevision = getSnapshotRevision(
          resource.loadState().snapshot
        );
        if (
          resource.watchCount > 0 &&
          shouldRefreshForRevision(issueRevision, revision)
        ) {
          this.fetchResource(resource);
        }
      }
      return;
    }

    for (const issueIdentifier of issueIdentifiers) {
      const resource = this.issueResources.get(issueIdentifier);
      if (!resource || resource.watchCount <= 0) {
        continue;
      }
      const issueRevision = getSnapshotRevision(resource.loadState().snapshot);
      if (shouldRefreshForRevision(issueRevision, revision)) {
        this.fetchResource(resource);
      }
    }
  }

  private handleEventStreamError(): void {
    if (this.activeWatcherCount() <= 0) {
      return;
    }

    this.eventSource?.close();
    this.eventSource = null;
    this.refreshActiveResources();
    if (this.eventSourceReconnectHandle !== null) {
      return;
    }

    this.eventSourceReconnectHandle = globalThis.setTimeout(() => {
      this.eventSourceReconnectHandle = null;
      this.refreshActiveResources();
      this.ensureBrowserSubscriptions();
    }, EVENT_STREAM_RECONNECT_DELAY_MS);
  }
}

export function computeRuntimeRefreshDelay(expiresAt: string | null): number {
  if (!expiresAt) {
    return FALLBACK_REFRESH_DELAY_MS;
  }

  const expiresAtMs = new Date(expiresAt).getTime();
  if (Number.isNaN(expiresAtMs)) {
    return FALLBACK_REFRESH_DELAY_MS;
  }

  return Math.max(expiresAtMs - Date.now(), 0);
}

export function parseRuntimeInvalidationEvent(
  rawValue: string
): RuntimeInvalidationEvent | null {
  try {
    const parsed = JSON.parse(rawValue) as Partial<RuntimeInvalidationEvent>;
    if (
      typeof parsed.sequence !== "number" ||
      typeof parsed.event !== "string" ||
      typeof parsed.emitted_at !== "string"
    ) {
      return null;
    }

    return {
      sequence: parsed.sequence,
      event: parsed.event,
      emitted_at: parsed.emitted_at,
      revision:
        typeof parsed.revision === "number" ? parsed.revision : undefined,
      issue_identifiers: Array.isArray(parsed.issue_identifiers)
        ? parsed.issue_identifiers.filter(
            (value): value is string =>
              typeof value === "string" && value.length > 0
          )
        : undefined
    };
  } catch {
    return null;
  }
}

function getSnapshotRevision(
  snapshot: RuntimeManagedSnapshot | null
): number | null {
  if (!snapshot || typeof snapshot.revision !== "number") {
    return null;
  }
  return snapshot.revision;
}

function shouldRefreshForRevision(
  currentRevision: number | null,
  nextRevision: number | null
): boolean {
  if (nextRevision === null) {
    return true;
  }
  if (currentRevision === null) {
    return true;
  }
  return nextRevision > currentRevision;
}

function getBrowserWindow(): Window | null {
  return typeof window === "undefined" ? null : window;
}

function getBrowserDocument(): Document | null {
  return typeof document === "undefined" ? null : document;
}

function getEventSourceConstructor():
  | (new (url: string) => EventSource)
  | null {
  if (typeof EventSource === "undefined") {
    return null;
  }
  return EventSource;
}
