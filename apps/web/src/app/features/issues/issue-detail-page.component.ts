import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal
} from "@angular/core";
import { CommonModule } from "@angular/common";
import { ActivatedRoute, RouterLink } from "@angular/router";
import { takeUntilDestroyed } from "@angular/core/rxjs-interop";

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
    CommonModule,
    RouterLink,
    EmptyStateComponent,
    SessionSummaryComponent
  ],
  template: `
    <div class="space-y-token-6">
      <div class="flex items-center justify-between gap-token-4">
        <div>
          <a
            routerLink="/"
            class="text-sm text-muted transition-colors duration-base ease-standard hover:text-accent"
          >
            Back to dashboard
          </a>
          <h2 class="mt-token-1 text-2xl font-semibold">
            {{ issueIdentifier() }}
          </h2>
        </div>
        <p class="text-xs uppercase tracking-ui text-accent">Issue detail</p>
      </div>

      @if (state().kind === "loading") {
        <p class="py-token-8 text-center text-sm text-muted">
          Loading issue snapshot...
        </p>
      } @else {
        @if (issueError(); as error) {
          <section
            class="rounded-panel border border-line bg-surface p-token-6 shadow-panel"
          >
            <p class="text-sm uppercase tracking-ui text-muted">
              {{ errorEyebrow(error) }}
            </p>
            <h3 class="mt-token-2 text-2xl font-semibold">
              {{ errorTitle(error) }}
            </h3>
            <p class="mt-token-3 max-w-2xl text-muted">{{ error.message }}</p>
            <div class="mt-token-4 flex flex-wrap gap-token-2">
              <button
                type="button"
                (click)="load(issueIdentifier())"
                class="rounded-full border border-line px-token-4 py-token-2 text-sm transition-colors duration-base ease-standard hover:border-accent hover:text-fg"
              >
                Retry
              </button>
              <a
                routerLink="/runs"
                class="rounded-full border border-line px-token-4 py-token-2 text-sm transition-colors duration-base ease-standard hover:border-accent hover:text-fg"
              >
                Open runs view
              </a>
            </div>
          </section>
        } @else {
          @if (issueDetail(); as detail) {
            <section
              class="rounded-panel border border-line bg-surface p-token-6 shadow-panel"
            >
              <div class="flex flex-wrap items-center gap-token-3">
                <h3 class="text-3xl font-semibold">{{ detail.identifier }}</h3>
                <span
                  class="rounded-full bg-accent px-token-3 py-token-1 text-xs uppercase tracking-ui text-surface"
                >
                  {{ detail.statusLabel }}
                </span>
              </div>
              <dl
                class="mt-token-4 grid gap-x-token-8 gap-y-token-3 text-sm sm:grid-cols-2 lg:grid-cols-4"
              >
                <div>
                  <dt class="text-xs uppercase tracking-ui text-muted">
                    Issue ID
                  </dt>
                  <dd class="mt-token-1 font-semibold text-fg">
                    {{ detail.issueId }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs uppercase tracking-ui text-muted">
                    Workspace
                  </dt>
                  <dd class="mt-token-1 font-mono text-fg break-all">
                    {{ detail.workspacePath }}
                  </dd>
                </div>
                <div>
                  <dt class="text-xs uppercase tracking-ui text-muted">
                    Attempts
                  </dt>
                  <dd class="mt-token-1 font-semibold text-fg">
                    {{ detail.attemptSummary }}
                  </dd>
                  <dd class="text-xs text-muted">{{ detail.retryWindow }}</dd>
                </div>
                <div>
                  <dt class="text-xs uppercase tracking-ui text-muted">
                    Last error
                  </dt>
                  <dd class="mt-token-1 text-fg break-words">
                    {{ detail.lastError }}
                  </dd>
                </div>
              </dl>
            </section>

            <section class="grid gap-token-4 xl:grid-cols-2">
              <article
                class="rounded-panel border border-line bg-surface p-token-6 shadow-panel"
              >
                <p class="text-xs uppercase tracking-ui text-muted">
                  Current session
                </p>
                @if (detail.currentSession; as currentSession) {
                  <app-session-summary [session]="currentSession" />
                } @else {
                  <p class="mt-token-3 text-sm text-muted">
                    No active session.
                  </p>
                }
              </article>

              <article
                class="rounded-panel border border-line bg-surface p-token-6 shadow-panel"
              >
                <p class="text-xs uppercase tracking-ui text-muted">
                  Last session summary
                </p>
                @if (detail.previousSession; as previousSession) {
                  <app-session-summary [session]="previousSession" />
                } @else {
                  <p class="mt-token-3 text-sm text-muted">
                    No prior session recorded.
                  </p>
                }
              </article>
            </section>

            <section
              class="rounded-panel border border-line bg-surface p-token-6 shadow-panel"
            >
              <div
                class="flex flex-col gap-token-2 border-b border-line pb-token-4 md:flex-row md:items-end md:justify-between"
              >
                <div>
                  <p class="text-xs uppercase tracking-ui text-muted">
                    Recent events
                  </p>
                  <h3 class="mt-token-2 text-2xl font-semibold">
                    Recent activity
                  </h3>
                </div>
                <a
                  routerLink="/"
                  class="text-sm text-muted transition-colors duration-base ease-standard hover:text-accent"
                >
                  Return to dashboard
                </a>
              </div>

              @if (detail.recentEvents.length === 0) {
                <app-empty-state
                  title="No recent events recorded"
                  description="This is expected for retry-only entries or issues that have not streamed a recent codex event."
                />
              } @else {
                <div class="mt-token-5 space-y-token-3">
                  @for (
                    event of detail.recentEvents;
                    track event.at + "|" + event.event
                  ) {
                    <div
                      class="rounded-panel border border-line bg-bg/70 p-token-4"
                    >
                      <div class="flex flex-wrap items-center gap-token-2">
                        <p class="text-lg font-semibold">{{ event.event }}</p>
                        <span
                          class="rounded-full border border-line px-token-3 py-token-1 text-xs uppercase tracking-ui text-muted"
                        >
                          {{ event.at }}
                        </span>
                      </div>
                      <p class="mt-token-2 text-sm text-muted">
                        {{ event.message }}
                      </p>
                    </div>
                  }
                </div>
              }
            </section>
          }
        }
      }
    </div>
  `,
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
