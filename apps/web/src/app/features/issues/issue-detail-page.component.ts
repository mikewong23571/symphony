import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal
} from "@angular/core";
import { ActivatedRoute, RouterLink } from "@angular/router";
import { takeUntilDestroyed } from "@angular/core/rxjs-interop";
import { MatCardModule } from "@angular/material/card";
import { MatButtonModule } from "@angular/material/button";
import { MatChipsModule } from "@angular/material/chips";
import { MatProgressBarModule } from "@angular/material/progress-bar";
import { MatIconModule } from "@angular/material/icon";
import { MatDividerModule } from "@angular/material/divider";

import { RuntimeApiService } from "../../shared/api/runtime-api.service";
import {
  IssueDetailViewModel,
  RuntimeUiError
} from "../../shared/lib/runtime-types";
import { EmptyStateComponent } from "../../shared/ui/empty-state.component";
import { SessionSummaryComponent } from "../../shared/ui/session-summary.component";

type IssueState =
  | { kind: "loading" }
  | { kind: "ready"; data: IssueDetailViewModel }
  | { kind: "error"; error: RuntimeUiError };

@Component({
  selector: "app-issue-detail-page",
  standalone: true,
  imports: [
    RouterLink,
    EmptyStateComponent,
    SessionSummaryComponent,
    MatCardModule,
    MatButtonModule,
    MatChipsModule,
    MatProgressBarModule,
    MatIconModule,
    MatDividerModule
  ],
  template: `
    <div class="detail-layout">
      <!-- Page header -->
      <div class="detail-header">
        <div>
          <a mat-button routerLink="/">
            <mat-icon>arrow_back</mat-icon> Back to dashboard
          </a>
          <h2 class="detail-title">{{ issueIdentifier() }}</h2>
        </div>
        <span class="section-eyebrow tone-accent">Issue detail</span>
      </div>

      @if (state().kind === "loading") {
        <mat-progress-bar mode="indeterminate" />
      } @else {
        @if (issueError(); as error) {
          <mat-card appearance="outlined">
            <mat-card-header>
              <mat-card-subtitle>{{ errorEyebrow(error) }}</mat-card-subtitle>
              <mat-card-title>{{ errorTitle(error) }}</mat-card-title>
            </mat-card-header>
            <mat-card-content class="tone-muted">{{
              error.message
            }}</mat-card-content>
            <mat-card-actions>
              <button mat-stroked-button (click)="load(issueIdentifier())">
                Retry
              </button>
              <a mat-stroked-button routerLink="/runs">Open runs view</a>
            </mat-card-actions>
          </mat-card>
        } @else {
          @if (issueDetail(); as detail) {
            <!-- Identity card -->
            <mat-card appearance="outlined">
              <mat-card-content>
                <div class="identity-header">
                  <h3 class="identity-title">{{ detail.identifier }}</h3>
                  <mat-chip-set>
                    <mat-chip class="chip-accent" disableRipple>{{
                      detail.statusLabel
                    }}</mat-chip>
                  </mat-chip-set>
                </div>
                <dl class="detail-grid">
                  <div>
                    <dt class="detail-dt">Issue ID</dt>
                    <dd class="detail-dd">{{ detail.issueId }}</dd>
                  </div>
                  <div>
                    <dt class="detail-dt">Workspace</dt>
                    <dd class="detail-dd val-mono break-all">
                      {{ detail.workspacePath }}
                    </dd>
                  </div>
                  <div>
                    <dt class="detail-dt">Attempts</dt>
                    <dd class="detail-dd">{{ detail.attemptSummary }}</dd>
                    <dd class="detail-dd-sub tone-muted">
                      {{ detail.retryWindow }}
                    </dd>
                  </div>
                  <div>
                    <dt class="detail-dt">Last error</dt>
                    <dd class="detail-dd">{{ detail.lastError }}</dd>
                  </div>
                </dl>
              </mat-card-content>
            </mat-card>

            <!-- Sessions grid -->
            <div class="sessions-grid">
              <mat-card appearance="outlined">
                <mat-card-header>
                  <mat-card-subtitle>Current session</mat-card-subtitle>
                </mat-card-header>
                <mat-card-content>
                  @if (detail.currentSession; as s) {
                    <app-session-summary [session]="s" />
                  } @else {
                    <p class="tone-muted">No active session.</p>
                  }
                </mat-card-content>
              </mat-card>

              <mat-card appearance="outlined">
                <mat-card-header>
                  <mat-card-subtitle>Last session summary</mat-card-subtitle>
                </mat-card-header>
                <mat-card-content>
                  @if (detail.previousSession; as s) {
                    <app-session-summary [session]="s" />
                  } @else {
                    <p class="tone-muted">No prior session recorded.</p>
                  }
                </mat-card-content>
              </mat-card>
            </div>

            <!-- Events card -->
            <mat-card appearance="outlined">
              <mat-card-header>
                <mat-card-subtitle>Recent events</mat-card-subtitle>
                <mat-card-title>Recent activity</mat-card-title>
                <span class="spacer"></span>
                <a mat-button routerLink="/">Return to dashboard</a>
              </mat-card-header>
              <mat-divider />
              <mat-card-content>
                @if (detail.recentEvents.length === 0) {
                  <app-empty-state
                    title="No recent events recorded"
                    description="This is expected for retry-only entries or issues that have not streamed a recent codex event."
                  />
                } @else {
                  @for (
                    event of detail.recentEvents;
                    track event.at + "|" + event.event
                  ) {
                    <div class="event-item">
                      <div class="event-header">
                        <span class="event-name">{{ event.event }}</span>
                        <mat-chip-set>
                          <mat-chip class="chip-neutral" disableRipple>{{
                            event.at
                          }}</mat-chip>
                        </mat-chip-set>
                      </div>
                      <p class="tone-muted event-message">
                        {{ event.message }}
                      </p>
                    </div>
                    <mat-divider />
                  }
                }
              </mat-card-content>
            </mat-card>
          }
        }
      }
    </div>
  `,
  styles: [
    `
      .detail-layout {
        display: flex;
        flex-direction: column;
        gap: 1.5rem;
      }

      .detail-header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 1rem;
      }
      .detail-title {
        font-size: 1.5rem;
        font-weight: 600;
        margin: 0.25rem 0 0 0.5rem;
      }
      .section-eyebrow {
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.18em;
      }

      /* Identity card */
      .identity-header {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 0.75rem;
        margin-bottom: 1rem;
      }
      .identity-title {
        font-size: 1.875rem;
        font-weight: 600;
        margin: 0;
      }
      .detail-grid {
        display: grid;
        gap: 1rem 2rem;
        font-size: 0.875rem;
        grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr));
        margin: 0;
      }
      .detail-dt {
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.18em;
        color: #6e6558;
      }
      .detail-dd {
        font-weight: 600;
        color: #1f1b16;
        margin: 0.25rem 0 0;
      }
      .detail-dd-sub {
        font-size: 0.75rem;
        color: #6e6558;
        margin: 0;
      }
      .break-all {
        word-break: break-all;
      }

      /* Sessions */
      .sessions-grid {
        display: grid;
        gap: 1rem;
      }
      @media (min-width: 1280px) {
        .sessions-grid {
          grid-template-columns: 1fr 1fr;
        }
      }

      /* Events */
      .spacer {
        flex: 1;
      }
      .event-item {
        padding: 1rem 0;
      }
      .event-header {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 0.5rem;
      }
      .event-name {
        font-size: 1.125rem;
        font-weight: 600;
      }
      .event-message {
        margin: 0.5rem 0 0;
        font-size: 0.875rem;
      }
    `
  ],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class IssueDetailPageComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly runtimeApi = inject(RuntimeApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly state = signal<IssueState>({ kind: "loading" });
  readonly issueIdentifier = signal("unknown");
  readonly issueDetail = computed(() => {
    const state = this.state();
    return state.kind === "ready" ? state.data : null;
  });
  readonly issueError = computed(() => {
    const state = this.state();
    return state.kind === "error" ? state.error : null;
  });

  constructor() {
    this.route.paramMap
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((params) => {
        const identifier = params.get("id") ?? "unknown";
        this.issueIdentifier.set(identifier);
        this.load(identifier);
      });
  }

  load(issueIdentifier: string): void {
    this.state.set({ kind: "loading" });
    this.runtimeApi
      .loadIssue(issueIdentifier)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (data) => this.state.set({ kind: "ready", data }),
        error: (error: RuntimeUiError) =>
          this.state.set({ kind: "error", error })
      });
  }

  errorEyebrow(error: RuntimeUiError): string {
    return error.kind === "issue_not_found"
      ? "Missing issue"
      : "Issue snapshot error";
  }

  errorTitle(error: RuntimeUiError): string {
    switch (error.kind) {
      case "issue_not_found":
        return "This issue is not present in the current runtime snapshot";
      case "stale":
        return "The issue snapshot went stale before it could be rendered";
      case "timeout":
        return "The backend timed out while loading issue detail";
      case "unavailable":
        return "Issue detail is temporarily unavailable";
      default:
        return "Issue detail failed to load";
    }
  }
}
