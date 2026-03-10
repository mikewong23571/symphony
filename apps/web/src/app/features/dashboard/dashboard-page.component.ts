import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal
} from "@angular/core";
import { CommonModule } from "@angular/common";
import { RouterLink } from "@angular/router";
import { takeUntilDestroyed } from "@angular/core/rxjs-interop";

import { RuntimeApiService } from "../../shared/api/runtime-api.service";
import {
  DashboardViewModel,
  RefreshReceiptViewModel,
  RuntimeUiError,
  SnapshotStatusViewModel
} from "../../shared/lib/runtime-types";
import { EmptyStateComponent } from "../../shared/ui/empty-state.component";

type DashboardState =
  | { kind: "loading" }
  | { kind: "ready"; data: DashboardViewModel }
  | { kind: "error"; error: RuntimeUiError };

type RefreshState =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "done"; receipt: RefreshReceiptViewModel }
  | { kind: "error"; error: RuntimeUiError };

@Component({
  selector: "app-dashboard-page",
  standalone: true,
  imports: [CommonModule, RouterLink, EmptyStateComponent],
  template: `
    <div class="space-y-token-6">
      <section
        class="grid gap-token-4 lg:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]"
      >
        <article
          class="rounded-panel border border-line bg-surface p-token-6 shadow-panel"
        >
          <p class="text-xs uppercase tracking-ui text-accent">Dashboard</p>
          <h2 class="mt-token-2 text-3xl font-semibold">
            Live orchestration snapshot
          </h2>
          <p class="mt-token-3 max-w-2xl text-body text-muted">
            Aggregate counts, token totals, and active issue rows come straight
            from the backend runtime snapshot. Refresh asks Django to enqueue a
            reconcile cycle instead of reimplementing orchestration in the
            browser.
          </p>
        </article>

        <aside
          class="rounded-panel border border-line bg-surface p-token-6 shadow-panel"
        >
          <div class="flex items-center justify-between gap-token-3">
            <div>
              <p class="text-xs uppercase tracking-ui text-muted">
                Refresh control
              </p>
              <p class="mt-token-2 text-lg font-semibold text-fg">
                Trigger a backend refresh
              </p>
            </div>
            <button
              type="button"
              (click)="requestRefresh()"
              [disabled]="refreshState().kind === 'pending'"
              class="rounded-full bg-accent px-token-4 py-token-2 text-sm font-medium text-surface transition-opacity duration-base ease-standard disabled:cursor-not-allowed disabled:opacity-60"
            >
              {{
                refreshState().kind === "pending"
                  ? "Refreshing..."
                  : "Refresh now"
              }}
            </button>
          </div>

          @if (refreshReceipt(); as receipt) {
            <div
              class="mt-token-4 rounded-panel border border-line bg-bg/80 p-token-4 text-sm"
            >
              <p class="font-medium text-fg">{{ receipt.queuedLabel }}</p>
              <p class="mt-token-2 text-muted">
                {{ receipt.operationsLabel }} at {{ receipt.requestedAt }}
              </p>
            </div>
          }

          @if (refreshError(); as refreshError) {
            <div
              class="mt-token-4 rounded-panel border border-accent bg-bg/80 p-token-4 text-sm"
            >
              <p class="font-medium text-fg">Refresh failed</p>
              <p class="mt-token-2 text-muted">{{ refreshError.message }}</p>
            </div>
          }
        </aside>
      </section>

      @if (state().kind === "loading") {
        <section
          class="rounded-panel border border-dashed border-line bg-surface/80 p-token-6 shadow-panel"
        >
          <p class="text-sm uppercase tracking-ui text-muted">Loading</p>
          <h3 class="mt-token-2 text-2xl font-semibold">
            Waiting for /api/v1/state
          </h3>
          <p class="mt-token-3 text-muted">
            The dashboard will populate once the current runtime snapshot is
            available.
          </p>
        </section>
      } @else {
        @if (dashboardError(); as error) {
          <section
            class="rounded-panel border border-line border-l-4 border-l-danger bg-danger-subtle p-token-6 shadow-panel"
          >
            <p
              class="text-sm uppercase tracking-ui"
              [class]="errorToneClass(error)"
            >
              {{ errorEyebrow(error) }}
            </p>
            <h3 class="mt-token-2 text-2xl font-semibold">
              {{ errorTitle(error) }}
            </h3>
            <p class="mt-token-3 max-w-2xl text-muted">{{ error.message }}</p>
            <button
              type="button"
              (click)="load()"
              class="mt-token-4 rounded-full border border-line px-token-4 py-token-2 text-sm transition-colors duration-base ease-standard hover:border-accent hover:text-fg"
            >
              Retry snapshot load
            </button>
          </section>
        } @else {
          @if (dashboardData(); as data) {
            <section class="grid gap-token-4 md:grid-cols-2 xl:grid-cols-4">
              @for (card of data.statCards; track card.label) {
                <article
                  class="rounded-panel border border-line bg-surface p-token-5 shadow-panel"
                >
                  <p class="text-xs uppercase tracking-ui text-muted">
                    {{ card.label }}
                  </p>
                  <p class="mt-token-3 text-3xl font-semibold">
                    {{ card.value }}
                  </p>
                  <p class="mt-token-2 text-sm text-muted">{{ card.detail }}</p>
                </article>
              }
            </section>

            <section
              class="grid gap-token-4 lg:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]"
            >
              <article
                class="rounded-panel border border-line bg-surface p-token-6 shadow-panel"
              >
                <div
                  class="flex flex-col gap-token-2 border-b border-line pb-token-4 md:flex-row md:items-end md:justify-between"
                >
                  <div>
                    <p class="text-xs uppercase tracking-ui text-muted">
                      Active issues
                    </p>
                    <h3 class="mt-token-2 text-2xl font-semibold">
                      Dispatches in flight
                    </h3>
                  </div>
                  <a
                    routerLink="/runs"
                    class="text-sm text-muted transition-colors duration-base ease-standard hover:text-accent"
                  >
                    Open runs view
                  </a>
                </div>

                @if (data.activeIssues.length === 0) {
                  <app-empty-state
                    title="No active issue runs"
                    description="The backend snapshot currently reports zero running issues. Retry entries still appear in the adjacent queue panel."
                  />
                } @else {
                  <div class="mt-token-5 space-y-token-4">
                    @for (issue of data.activeIssues; track issue.identifier) {
                      <a
                        [routerLink]="['/issues', issue.identifier]"
                        class="block rounded-panel border border-line bg-bg/70 p-token-4 transition-transform duration-base ease-standard hover:-translate-y-0.5 hover:border-accent"
                      >
                        <div
                          class="flex flex-col gap-token-3 xl:flex-row xl:items-start xl:justify-between"
                        >
                          <div>
                            <div
                              class="flex flex-wrap items-center gap-token-2"
                            >
                              <h4 class="text-xl font-semibold">
                                {{ issue.identifier }}
                              </h4>
                              <span
                                class="rounded-full border border-line px-token-3 py-token-1 text-xs uppercase tracking-ui text-muted"
                              >
                                {{ issue.state }}
                              </span>
                              <span
                                class="rounded-full bg-accent px-token-3 py-token-1 text-xs uppercase tracking-ui text-surface"
                              >
                                {{ issue.attemptLabel }}
                              </span>
                            </div>
                            <p class="mt-token-2 text-sm text-muted">
                              {{ issue.lastEvent }} • {{ issue.lastMessage }}
                            </p>
                          </div>
                          <div
                            class="grid gap-token-3 text-sm text-muted md:grid-cols-2"
                          >
                            <p>
                              <span class="font-medium text-fg">Session:</span>
                              {{ issue.session }}
                            </p>
                            <p>
                              <span class="font-medium text-fg">Started:</span>
                              {{ issue.startedAt }}
                            </p>
                            <p>
                              <span class="font-medium text-fg">Updated:</span>
                              {{ issue.updatedAt }}
                            </p>
                            <p>
                              <span class="font-medium text-fg">Tokens:</span>
                              {{ issue.tokenSummary }}
                            </p>
                          </div>
                        </div>
                        <p class="mt-token-3 text-sm text-muted">
                          <span class="font-medium text-fg">Workspace:</span>
                          {{ issue.workspacePath }}
                        </p>
                      </a>
                    }
                  </div>
                }
              </article>

              <article
                class="rounded-panel border border-line bg-surface p-token-6 shadow-panel"
              >
                <div class="border-b border-line pb-token-4">
                  <p class="text-xs uppercase tracking-ui text-muted">
                    Snapshot health
                  </p>
                  <h3
                    class="mt-token-2 text-2xl font-semibold"
                    [class]="snapshotToneClass(data.snapshotStatus)"
                  >
                    {{ data.snapshotStatus.label }}
                  </h3>
                  <p class="mt-token-2 text-sm text-muted">
                    {{ data.snapshotStatus.detail }}
                  </p>
                </div>

                <dl class="mt-token-5 space-y-token-3 text-sm">
                  <div class="flex items-start justify-between gap-token-4">
                    <dt class="text-muted">Generated</dt>
                    <dd class="text-right font-medium text-fg">
                      {{ data.generatedAt }}
                    </dd>
                  </div>
                  <div class="flex items-start justify-between gap-token-4">
                    <dt class="text-muted">Expires</dt>
                    <dd class="text-right font-medium text-fg">
                      {{ data.expiresAt }}
                    </dd>
                  </div>
                </dl>
              </article>
            </section>

            <section class="grid gap-token-4 sm:grid-cols-2 lg:grid-cols-3">
              @for (entry of data.rateLimits; track entry.label) {
                <div
                  class="rounded-panel border border-line bg-surface p-token-4 shadow-panel"
                >
                  <p class="text-xs uppercase tracking-ui text-muted">
                    Rate limits
                  </p>
                  <p class="mt-token-2 font-medium capitalize text-fg">
                    {{ entry.label }}
                  </p>
                  <p class="mt-token-2 text-lg font-semibold">
                    {{ entry.value }}
                  </p>
                  <p class="mt-token-1 text-sm text-muted">
                    {{ entry.detail }}
                  </p>
                </div>
              }
            </section>

            @if (!data.hasActivity) {
              <section
                class="rounded-panel border border-dashed border-line bg-surface/80 p-token-6 shadow-panel"
              >
                <p class="text-sm uppercase tracking-ui text-muted">
                  Empty snapshot
                </p>
                <h3 class="mt-token-2 text-2xl font-semibold">
                  Nothing is running right now
                </h3>
                <p class="mt-token-3 max-w-2xl text-muted">
                  This is a valid empty state: no active runs and no queued
                  retries were present when the snapshot was generated.
                </p>
              </section>
            }
          }
        }
      }
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class DashboardPageComponent {
  private readonly runtimeApi = inject(RuntimeApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly state = signal<DashboardState>({ kind: "loading" });
  readonly refreshState = signal<RefreshState>({ kind: "idle" });
  readonly dashboardData = computed(() => {
    const state = this.state();
    return state.kind === "ready" ? state.data : null;
  });
  readonly dashboardError = computed(() => {
    const state = this.state();
    return state.kind === "error" ? state.error : null;
  });
  readonly refreshReceipt = computed(() => {
    const refreshState = this.refreshState();
    return refreshState.kind === "done" ? refreshState.receipt : null;
  });
  readonly refreshError = computed(() => {
    const refreshState = this.refreshState();
    return refreshState.kind === "error" ? refreshState.error : null;
  });

  constructor() {
    this.load();
  }

  load(): void {
    this.state.set({ kind: "loading" });
    this.runtimeApi
      .loadDashboard()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (data) => this.state.set({ kind: "ready", data }),
        error: (error: RuntimeUiError) =>
          this.state.set({ kind: "error", error })
      });
  }

  requestRefresh(): void {
    this.refreshState.set({ kind: "pending" });
    this.runtimeApi
      .requestRefresh()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (receipt) => {
          this.refreshState.set({ kind: "done", receipt });
          this.load();
        },
        error: (error: RuntimeUiError) =>
          this.refreshState.set({ kind: "error", error })
      });
  }

  errorEyebrow(error: RuntimeUiError): string {
    switch (error.kind) {
      case "stale":
        return "Stale snapshot";
      case "timeout":
        return "Timeout";
      case "unavailable":
        return "Unavailable";
      default:
        return "Error";
    }
  }

  errorTitle(error: RuntimeUiError): string {
    switch (error.kind) {
      case "stale":
        return "The runtime snapshot expired before the UI could use it";
      case "timeout":
        return "The backend timed out while reading runtime state";
      case "unavailable":
        return "Runtime state is currently unavailable";
      default:
        return "The dashboard could not load";
    }
  }

  errorToneClass(error: RuntimeUiError): string {
    if (error.kind === "stale" || error.kind === "timeout")
      return "text-accent";
    return "text-danger";
  }

  snapshotToneClass(status: SnapshotStatusViewModel): string {
    if (status.tone === "warning") return "text-accent";
    if (status.tone === "danger") return "text-danger";
    return "text-fg";
  }
}
