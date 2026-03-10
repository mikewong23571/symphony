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
  RuntimeStatCardViewModel,
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
    <div class="space-y-token-5">
      @if (state().kind === "loading") {
        <p class="py-token-8 text-center text-sm text-muted">
          Loading snapshot...
        </p>
      } @else {
        @if (dashboardError(); as error) {
          <section
            class="overflow-hidden rounded-panel border border-line border-l-4 border-l-danger bg-danger-subtle shadow-panel"
          >
            <div class="p-token-6">
              <p
                class="text-sm uppercase tracking-ui"
                [class]="errorToneClass(error)"
              >
                {{ errorEyebrow(error) }}
              </p>
              <h3 class="mt-token-2 text-2xl font-semibold">
                {{ errorTitle(error) }}
              </h3>
              <p class="mt-token-3 max-w-2xl text-muted">
                {{ error.message }}
              </p>
              <button
                type="button"
                (click)="load()"
                class="mt-token-4 rounded border border-line px-token-3 py-token-1 text-sm text-muted transition-colors duration-fast ease-standard hover:border-accent hover:text-fg"
              >
                Retry
              </button>
            </div>
          </section>
        } @else {
          @if (dashboardData(); as data) {
            <!-- Snapshot panel -->
            <div
              class="overflow-hidden rounded-panel border border-line bg-surface shadow-panel"
            >
              <div
                class="flex items-center justify-between border-b border-line px-token-5 py-token-3"
              >
                <p class="text-xs uppercase tracking-ui text-muted">Snapshot</p>
                <div class="flex items-center gap-token-3">
                  @if (refreshReceipt(); as receipt) {
                    <span class="text-xs text-muted">{{
                      receipt.queuedLabel
                    }}</span>
                  }
                  @if (refreshError(); as err) {
                    <span class="text-xs text-danger"
                      >Refresh failed: {{ err.message }}</span
                    >
                  }
                  <button
                    type="button"
                    (click)="requestRefresh()"
                    [disabled]="refreshState().kind === 'pending'"
                    class="rounded border border-line px-token-3 py-token-1 text-xs text-muted transition-colors duration-fast ease-standard hover:border-accent hover:text-fg disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {{
                      refreshState().kind === "pending"
                        ? "Refreshing…"
                        : "Refresh"
                    }}
                  </button>
                </div>
              </div>

              <div
                class="flex flex-wrap divide-x divide-line border-b border-line"
              >
                @for (card of data.statCards; track card.label) {
                  <div class="min-w-[7rem] flex-1 px-token-5 py-token-4">
                    <p
                      class="text-2xl font-semibold tabular-nums"
                      [class]="statToneClass(card)"
                    >
                      {{ card.value }}
                    </p>
                    <p class="mt-token-1 text-xs text-muted">
                      {{ card.label }}
                    </p>
                  </div>
                }
              </div>

              <div
                class="flex flex-wrap items-center gap-x-token-4 gap-y-token-1 px-token-5 py-token-3"
              >
                <span
                  class="text-sm font-medium"
                  [class]="snapshotToneClass(data.snapshotStatus)"
                  >{{ data.snapshotStatus.label }}</span
                >
                <span class="text-xs text-muted">{{
                  data.snapshotStatus.detail
                }}</span>
              </div>
            </div>

            <!-- Active issues panel -->
            <div
              class="overflow-hidden rounded-panel border border-line bg-surface shadow-panel"
            >
              <div
                class="flex items-center justify-between border-b border-line px-token-5 py-token-3"
              >
                <p class="text-xs uppercase tracking-ui text-muted">
                  Active issues
                </p>
                @if (data.activeIssues.length > 0) {
                  <span class="text-xs font-medium text-positive">
                    {{ data.activeIssues.length }} running
                  </span>
                }
              </div>

              <div class="p-token-5">
                @if (data.activeIssues.length === 0) {
                  <app-empty-state
                    title="No active issues"
                    description="No issues are currently running."
                  />
                } @else {
                  <div class="space-y-token-3">
                    @for (issue of data.activeIssues; track issue.identifier) {
                      <a
                        [routerLink]="['/issues', issue.identifier]"
                        class="block rounded-panel border border-line bg-bg/70 p-token-4 transition-transform duration-base ease-standard hover:-translate-y-0.5 hover:border-accent"
                      >
                        <div class="flex flex-wrap items-center gap-token-2">
                          <span class="text-base font-semibold">{{
                            issue.identifier
                          }}</span>
                          <span
                            class="rounded px-token-2 py-0.5 text-xs uppercase tracking-ui"
                            [class]="stateBadgeClass(issue.state)"
                            >{{ issue.state }}</span
                          >
                          <span
                            class="rounded px-token-2 py-0.5 text-xs uppercase tracking-ui"
                            [class]="attemptBadgeClass(issue.attemptLabel)"
                            >{{ issue.attemptLabel }}</span
                          >
                        </div>
                        <p class="mt-token-2 text-sm text-muted">
                          {{ issue.lastEvent }} · {{ issue.lastMessage }}
                        </p>
                        <div
                          class="mt-token-3 grid gap-x-token-6 gap-y-token-1 text-sm text-muted sm:grid-cols-2"
                        >
                          <p>
                            <span class="font-medium text-fg">Session</span>
                            {{ issue.session }}
                          </p>
                          <p>
                            <span class="font-medium text-fg">Started</span>
                            {{ issue.startedAt }}
                          </p>
                          <p>
                            <span class="font-medium text-fg">Tokens</span>
                            {{ issue.tokenSummary }}
                          </p>
                          <p>
                            <span class="font-medium text-fg">Workspace</span>
                            {{ issue.workspacePath }}
                          </p>
                        </div>
                      </a>
                    }
                  </div>
                }
              </div>
            </div>

            <!-- Retry queue panel -->
            <div
              class="overflow-hidden rounded-panel border border-line bg-surface shadow-panel"
            >
              <div
                class="flex items-center justify-between border-b border-line px-token-5 py-token-3"
              >
                <p class="text-xs uppercase tracking-ui text-muted">
                  Retry queue
                </p>
                @if (data.retryQueue.length > 0) {
                  <span class="text-xs font-medium text-warning">
                    {{ data.retryQueue.length }} queued
                  </span>
                }
              </div>

              <div class="p-token-5">
                @if (data.retryQueue.length === 0) {
                  <app-empty-state
                    title="No retries waiting"
                    description="When a retry is scheduled, it will appear here."
                  />
                } @else {
                  <div class="space-y-token-3">
                    @for (retry of data.retryQueue; track retry.identifier) {
                      <a
                        [routerLink]="['/issues', retry.identifier]"
                        class="block rounded-panel border border-line bg-bg/70 p-token-4 transition-transform duration-base ease-standard hover:-translate-y-0.5 hover:border-accent"
                      >
                        <div class="flex flex-wrap items-center gap-token-2">
                          <span class="text-base font-semibold">{{
                            retry.identifier
                          }}</span>
                          <span
                            class="rounded px-token-2 py-0.5 text-xs uppercase tracking-ui bg-warning-subtle text-warning"
                            >{{ retry.attemptLabel }}</span
                          >
                        </div>
                        <div
                          class="mt-token-2 grid gap-x-token-6 gap-y-token-1 text-sm text-muted sm:grid-cols-2"
                        >
                          <p>
                            <span class="font-medium text-fg">Due</span>
                            {{ retry.dueAt }}
                          </p>
                          <p>
                            <span class="font-medium text-fg">Error</span>
                            {{ retry.error }}
                          </p>
                          <p class="sm:col-span-2">
                            <span class="font-medium text-fg">Workspace</span>
                            {{ retry.workspacePath }}
                          </p>
                        </div>
                      </a>
                    }
                  </div>
                }
              </div>
            </div>

            <!-- Rate limits -->
            @if (data.rateLimits.length > 0) {
              <section>
                <p class="text-xs uppercase tracking-ui text-muted">
                  Rate limits
                </p>
                <div
                  class="mt-token-3 grid gap-token-4 sm:grid-cols-2 lg:grid-cols-3"
                >
                  @for (entry of data.rateLimits; track entry.label) {
                    <div
                      class="rounded-panel border border-line bg-surface p-token-4 shadow-panel"
                    >
                      <p class="text-xs capitalize text-muted">
                        {{ entry.label }}
                      </p>
                      <p class="mt-token-2 text-lg font-semibold text-fg">
                        {{ entry.value }}
                      </p>
                    </div>
                  }
                </div>
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

  statToneClass(card: RuntimeStatCardViewModel): string {
    if (card.label === "Running" && card.value !== "0") return "text-positive";
    if (card.label === "Retrying" && card.value !== "0") return "text-warning";
    return "text-fg";
  }

  stateBadgeClass(state: string): string {
    if (state === "running") return "bg-positive-subtle text-positive";
    if (state === "retrying") return "bg-warning-subtle text-warning";
    return "border border-line text-muted";
  }

  attemptBadgeClass(label: string): string {
    if (label.startsWith("Retry")) return "bg-warning-subtle text-warning";
    return "bg-accent-subtle text-accent";
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
      return "text-warning";
    return "text-danger";
  }

  snapshotToneClass(status: SnapshotStatusViewModel): string {
    if (status.tone === "warning") return "text-warning";
    if (status.tone === "danger") return "text-danger";
    return "text-muted";
  }
}
