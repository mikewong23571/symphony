import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal
} from "@angular/core";
import { RouterLink } from "@angular/router";
import { takeUntilDestroyed } from "@angular/core/rxjs-interop";
import { MatCardModule } from "@angular/material/card";
import { MatButtonModule } from "@angular/material/button";
import { MatChipsModule } from "@angular/material/chips";
import { MatProgressBarModule } from "@angular/material/progress-bar";
import { MatIconModule } from "@angular/material/icon";
import { MatRippleModule } from "@angular/material/core";

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
  imports: [
    RouterLink,
    EmptyStateComponent,
    MatCardModule,
    MatButtonModule,
    MatChipsModule,
    MatProgressBarModule,
    MatIconModule,
    MatRippleModule
  ],
  template: `
    <div class="dashboard">
      @if (state().kind === "loading") {
        <mat-progress-bar mode="indeterminate" />
      } @else {
        @if (dashboardError(); as error) {
          <mat-card appearance="outlined" class="error-card">
            <mat-card-header>
              <mat-card-subtitle [class]="errorToneClass(error)">{{
                errorEyebrow(error)
              }}</mat-card-subtitle>
              <mat-card-title>{{ errorTitle(error) }}</mat-card-title>
            </mat-card-header>
            <mat-card-content>
              <p class="tone-muted">{{ error.message }}</p>
            </mat-card-content>
            <mat-card-actions>
              <button mat-stroked-button (click)="load()">Retry</button>
            </mat-card-actions>
          </mat-card>
        } @else {
          @if (dashboardData(); as data) {
            <!-- Snapshot panel -->
            <mat-card appearance="outlined">
              <mat-card-header>
                <mat-card-subtitle>Snapshot</mat-card-subtitle>
                <span class="spacer"></span>
                @if (refreshReceipt(); as receipt) {
                  <span class="tone-muted refresh-hint">{{
                    receipt.queuedLabel
                  }}</span>
                }
                @if (refreshError(); as err) {
                  <span class="tone-danger refresh-hint"
                    >Refresh failed: {{ err.message }}</span
                  >
                }
                <button
                  mat-stroked-button
                  (click)="requestRefresh()"
                  [disabled]="refreshState().kind === 'pending'"
                >
                  {{
                    refreshState().kind === "pending"
                      ? "Refreshing…"
                      : "Refresh"
                  }}
                </button>
              </mat-card-header>
              <mat-card-content class="stat-grid">
                @for (card of data.statCards; track card.label) {
                  <div class="stat-cell">
                    <p class="stat-value" [class]="statToneClass(card)">
                      {{ card.value }}
                    </p>
                    <p class="stat-label tone-muted">{{ card.label }}</p>
                  </div>
                }
              </mat-card-content>
              <mat-card-footer class="snapshot-status">
                <span [class]="snapshotToneClass(data.snapshotStatus)">
                  {{ data.snapshotStatus.label }}
                </span>
                <span class="tone-muted">{{ data.snapshotStatus.detail }}</span>
              </mat-card-footer>
            </mat-card>

            <!-- Active issues panel -->
            <mat-card appearance="outlined">
              <mat-card-header>
                <div class="panel-header">
                  <mat-card-subtitle>Active issues</mat-card-subtitle>
                  @if (data.activeIssues.length > 0) {
                    <mat-chip-set>
                      <mat-chip class="chip-positive" disableRipple>
                        {{ data.activeIssues.length }} running
                      </mat-chip>
                    </mat-chip-set>
                  }
                </div>
              </mat-card-header>
              <mat-card-content>
                @if (data.activeIssues.length === 0) {
                  <app-empty-state
                    title="No active issues"
                    description="No issues are currently running."
                  />
                } @else {
                  <div class="issue-list">
                    @for (issue of data.activeIssues; track issue.identifier) {
                      <mat-card appearance="outlined" class="issue-card">
                        <mat-card-content>
                          <div class="issue-header">
                            <a
                              class="issue-id card-link"
                              [routerLink]="['/issues', issue.identifier]"
                              >{{ issue.identifier }}</a
                            >
                            <mat-chip-set>
                              <mat-chip
                                [class]="stateBadgeClass(issue.state)"
                                disableRipple
                              >
                                {{ issue.state }}
                              </mat-chip>
                              <mat-chip
                                [class]="attemptBadgeClass(issue.attemptLabel)"
                                disableRipple
                              >
                                {{ issue.attemptLabel }}
                              </mat-chip>
                            </mat-chip-set>
                            <button
                              class="expand-btn"
                              (click)="toggleIssue(issue.identifier)"
                              [attr.aria-expanded]="
                                isIssueExpanded(issue.identifier)
                              "
                              [attr.aria-label]="
                                isIssueExpanded(issue.identifier)
                                  ? 'Collapse'
                                  : 'Expand'
                              "
                            >
                              <mat-icon>{{
                                isIssueExpanded(issue.identifier)
                                  ? "expand_less"
                                  : "expand_more"
                              }}</mat-icon>
                            </button>
                          </div>
                          <p class="issue-event tone-muted">
                            {{ issue.lastEvent }}
                          </p>
                          @if (isIssueExpanded(issue.identifier)) {
                            <div class="issue-meta">
                              <p>
                                <strong>Session</strong> {{ issue.session }}
                              </p>
                              <p>
                                <strong>Started</strong> {{ issue.startedAt }}
                              </p>
                              <p>
                                <strong>Tokens</strong> {{ issue.tokenSummary }}
                              </p>
                              <p>
                                <strong>Workspace</strong>
                                {{ issue.workspacePath }}
                              </p>
                            </div>
                            @if (issue.lastMessageRaw) {
                              <pre class="issue-message-raw">{{
                                tryFormatJson(issue.lastMessageRaw)
                              }}</pre>
                            }
                          }
                        </mat-card-content>
                      </mat-card>
                    }
                  </div>
                }
              </mat-card-content>
            </mat-card>

            <!-- Retry queue panel -->
            <mat-card appearance="outlined">
              <mat-card-header>
                <div class="panel-header">
                  <mat-card-subtitle>Retry queue</mat-card-subtitle>
                  @if (data.retryQueue.length > 0) {
                    <mat-chip-set>
                      <mat-chip class="chip-warning" disableRipple>
                        {{ data.retryQueue.length }} queued
                      </mat-chip>
                    </mat-chip-set>
                  }
                </div>
              </mat-card-header>
              <mat-card-content>
                @if (data.retryQueue.length === 0) {
                  <app-empty-state
                    title="No retries waiting"
                    description="When a retry is scheduled, it will appear here."
                  />
                } @else {
                  <div class="issue-list">
                    @for (retry of data.retryQueue; track retry.identifier) {
                      <mat-card
                        appearance="outlined"
                        matRipple
                        class="card-link issue-card"
                        [routerLink]="['/issues', retry.identifier]"
                      >
                        <mat-card-content>
                          <div class="issue-header">
                            <span class="issue-id">{{ retry.identifier }}</span>
                            <mat-chip-set>
                              <mat-chip class="chip-warning" disableRipple>
                                {{ retry.attemptLabel }}
                              </mat-chip>
                            </mat-chip-set>
                          </div>
                          <div class="issue-meta">
                            <p><strong>Due</strong> {{ retry.dueAt }}</p>
                            <p><strong>Error</strong> {{ retry.error }}</p>
                            <p class="meta-full">
                              <strong>Workspace</strong>
                              {{ retry.workspacePath }}
                            </p>
                          </div>
                        </mat-card-content>
                      </mat-card>
                    }
                  </div>
                }
              </mat-card-content>
            </mat-card>

            <!-- Rate limits -->
            @if (data.rateLimits.length > 0 || data.rateLimitsRawJson) {
              <div class="section-label tone-muted">Rate limits</div>
              @if (data.rateLimits.length > 0) {
                <div class="rate-grid">
                  @for (entry of data.rateLimits; track entry.label) {
                    <mat-card appearance="outlined" class="rate-card">
                      <mat-card-content>
                        <p class="rate-label tone-muted">{{ entry.label }}</p>
                        <p class="rate-value">{{ entry.value }}</p>
                      </mat-card-content>
                    </mat-card>
                  }
                </div>
              }
              @if (data.rateLimitsRawJson) {
                <details class="rate-raw">
                  <summary class="rate-raw-summary tone-muted">
                    Raw data
                  </summary>
                  <pre class="rate-raw-content">{{
                    data.rateLimitsRawJson
                  }}</pre>
                </details>
              }
            }
          }
        }
      }
    </div>
  `,
  styles: [
    `
      .dashboard {
        display: flex;
        flex-direction: column;
        gap: 1.25rem;
      }

      .spacer {
        flex: 1;
      }
      .panel-header {
        display: flex;
        align-items: center;
        gap: 0.5rem;
      }
      .refresh-hint {
        font-size: 0.75rem;
      }
      /* Snapshot stats */
      .stat-grid {
        display: flex;
        flex-wrap: wrap;
        gap: 0;
        padding: 0;
      }
      .stat-cell {
        flex: 1;
        min-width: 7rem;
        padding: 1rem 1.25rem;
        border-right: 1px solid #d7d0c3;
      }
      .stat-cell:last-child {
        border-right: none;
      }
      .stat-value {
        font-size: 1.5rem;
        font-weight: 600;
        font-variant-numeric: tabular-nums;
        margin: 0;
      }
      .stat-label {
        font-size: 0.75rem;
        margin: 0.25rem 0 0;
      }

      .snapshot-status {
        display: flex;
        flex-wrap: wrap;
        gap: 1rem;
        padding: 0.75rem 1.25rem;
        align-items: center;
        font-size: 0.875rem;
      }

      /* Issue cards */
      .issue-list {
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
      }
      .issue-card {
        margin: 0;
      }
      .issue-header {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 0.5rem;
      }
      .issue-id {
        font-size: 1rem;
        font-weight: 600;
        text-decoration: none;
        color: inherit;
      }
      .issue-id:hover {
        text-decoration: underline;
      }
      .expand-btn {
        margin-left: auto;
        background: none;
        border: none;
        cursor: pointer;
        padding: 0;
        display: flex;
        align-items: center;
        color: #6e6558;
      }
      .expand-btn:hover {
        color: #1f1b16;
      }
      .issue-event {
        font-size: 0.875rem;
        margin: 0.375rem 0 0;
      }
      .issue-message-raw {
        margin: 0.75rem 0 0;
        padding: 0.75rem 1rem;
        font-size: 0.75rem;
        line-height: 1.5;
        overflow-x: auto;
        border: 1px solid #d7d0c3;
        border-radius: 4px;
        background: #faf7f2;
        white-space: pre-wrap;
        word-break: break-word;
      }
      .issue-meta {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 0.25rem 1.5rem;
        font-size: 0.875rem;
        color: #6e6558;
        margin-top: 0.75rem;
      }
      .issue-meta p {
        margin: 0;
      }
      .issue-meta strong {
        color: #1f1b16;
        font-weight: 500;
        margin-right: 0.25rem;
      }
      .meta-full {
        grid-column: 1 / -1;
      }

      /* Rate limits */
      .section-label {
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.18em;
      }
      .rate-grid {
        display: grid;
        gap: 1rem;
        grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr));
      }
      .rate-label {
        font-size: 0.75rem;
        text-transform: capitalize;
        margin: 0;
      }
      .rate-value {
        font-size: 1.125rem;
        font-weight: 600;
        margin: 0.5rem 0 0;
      }

      .rate-raw {
        border: 1px solid #d7d0c3;
        border-radius: 4px;
        padding: 0;
        overflow: hidden;
      }
      .rate-raw-summary {
        cursor: pointer;
        font-size: 0.75rem;
        padding: 0.5rem 0.75rem;
        user-select: none;
      }
      .rate-raw-summary:hover {
        background: #f5f0e8;
      }
      .rate-raw-content {
        margin: 0;
        padding: 0.75rem 1rem;
        font-size: 0.75rem;
        line-height: 1.5;
        overflow-x: auto;
        border-top: 1px solid #d7d0c3;
        background: #faf7f2;
      }
    `
  ],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class DashboardPageComponent {
  private readonly runtimeApi = inject(RuntimeApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly state = signal<DashboardState>({ kind: "loading" });
  readonly expandedIssues = signal(new Set<string>());
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

  toggleIssue(identifier: string): void {
    this.expandedIssues.update((set) => {
      const next = new Set(set);
      if (next.has(identifier)) next.delete(identifier);
      else next.add(identifier);
      return next;
    });
  }

  isIssueExpanded(identifier: string): boolean {
    return this.expandedIssues().has(identifier);
  }

  tryFormatJson(raw: string): string {
    try {
      return JSON.stringify(JSON.parse(raw), null, 2);
    } catch {
      return raw;
    }
  }

  statToneClass(card: RuntimeStatCardViewModel): string {
    if (card.label === "Running" && card.value !== "0")
      return "stat-value tone-positive";
    if (card.label === "Retrying" && card.value !== "0")
      return "stat-value tone-warning";
    return "stat-value";
  }

  stateBadgeClass(state: string): string {
    if (state === "running") return "chip-positive";
    if (state === "retrying") return "chip-warning";
    return "chip-neutral";
  }

  attemptBadgeClass(label: string): string {
    if (label.startsWith("Retry")) return "chip-warning";
    return "chip-accent";
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
      return "tone-warning";
    return "tone-danger";
  }

  snapshotToneClass(status: SnapshotStatusViewModel): string {
    if (status.tone === "warning") return "tone-warning";
    if (status.tone === "danger") return "tone-danger";
    return "tone-muted";
  }
}
