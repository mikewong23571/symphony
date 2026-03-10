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
  RunsViewModel,
  RuntimeUiError,
  SnapshotStatusViewModel
} from "../../shared/lib/runtime-types";
import { EmptyStateComponent } from "../../shared/ui/empty-state.component";

type RunsState =
  | { kind: "loading" }
  | { kind: "ready"; data: RunsViewModel }
  | { kind: "error"; error: RuntimeUiError };

@Component({
  selector: "app-runs-page",
  standalone: true,
  imports: [CommonModule, RouterLink, EmptyStateComponent],
  template: `
    <div class="space-y-token-6">
      <section
        class="rounded-panel border border-line bg-surface p-token-6 shadow-panel"
      >
        <p class="text-xs uppercase tracking-ui text-accent">
          Runs and retries
        </p>
        <h2 class="mt-token-2 text-3xl font-semibold">
          Active workers and queued attempts
        </h2>
        <p class="mt-token-3 max-w-2xl text-body text-muted">
          This route reorganizes the same backend state feed into
          operator-focused run and retry slices. It does not maintain any
          browser-side orchestration state.
        </p>
      </section>

      @if (state().kind === "loading") {
        <section
          class="rounded-panel border border-dashed border-line bg-surface/80 p-token-6 shadow-panel"
        >
          <p class="text-sm uppercase tracking-ui text-muted">Loading</p>
          <h3 class="mt-token-2 text-2xl font-semibold">
            Reading the current runtime snapshot
          </h3>
          <p class="mt-token-3 text-muted">
            The runs view depends on the same /api/v1/state snapshot as the
            dashboard.
          </p>
        </section>
      } @else {
        @if (runsError(); as error) {
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
              Retry
            </button>
          </section>
        } @else {
          @if (runsData(); as data) {
            <section
              class="grid gap-token-4 lg:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]"
            >
              <article
                class="rounded-panel border border-line bg-surface p-token-6 shadow-panel"
              >
                <div
                  class="flex items-end justify-between gap-token-3 border-b border-line pb-token-4"
                >
                  <div>
                    <p class="text-xs uppercase tracking-ui text-muted">
                      Live workers
                    </p>
                    <h3 class="mt-token-2 text-2xl font-semibold">
                      {{ data.activeRuns.length }} active
                    </h3>
                  </div>
                  <a
                    routerLink="/"
                    class="text-sm text-muted transition-colors duration-base ease-standard hover:text-accent"
                  >
                    Back to dashboard
                  </a>
                </div>

                @if (data.activeRuns.length === 0) {
                  <app-empty-state
                    title="No active runs"
                    [description]="data.emptyMessage"
                  />
                } @else {
                  <div class="mt-token-5 space-y-token-3">
                    @for (run of data.activeRuns; track run.identifier) {
                      <div
                        class="rounded-panel border border-line bg-bg/70 p-token-4"
                      >
                        <div class="flex flex-wrap items-center gap-token-2">
                          <a
                            [routerLink]="['/issues', run.identifier]"
                            class="text-xl font-semibold transition-colors duration-base ease-standard hover:text-accent"
                          >
                            {{ run.identifier }}
                          </a>
                          <span
                            class="rounded-full border border-line px-token-3 py-token-1 text-xs uppercase tracking-ui text-muted"
                          >
                            {{ run.state }}
                          </span>
                          <span
                            class="rounded-full bg-accent px-token-3 py-token-1 text-xs uppercase tracking-ui text-surface"
                          >
                            {{ run.attemptLabel }}
                          </span>
                        </div>
                        <div
                          class="mt-token-3 grid gap-token-3 text-sm text-muted md:grid-cols-2"
                        >
                          <p>
                            <span class="font-medium text-fg">Session:</span>
                            {{ run.session }}
                          </p>
                          <p>
                            <span class="font-medium text-fg">Started:</span>
                            {{ run.startedAt }}
                          </p>
                          <p>
                            <span class="font-medium text-fg">Last event:</span>
                            {{ run.lastEvent }}
                          </p>
                          <p>
                            <span class="font-medium text-fg">Updated:</span>
                            {{ run.updatedAt }}
                          </p>
                        </div>
                        <p class="mt-token-3 text-sm text-muted">
                          {{ run.tokenSummary }}
                        </p>
                      </div>
                    }
                  </div>
                }
              </article>

              <article
                class="rounded-panel border border-line bg-surface p-token-6 shadow-panel"
              >
                <div class="border-b border-line pb-token-4">
                  <p class="text-xs uppercase tracking-ui text-muted">
                    Retry queue
                  </p>
                  <h3 class="mt-token-2 text-2xl font-semibold">
                    {{ data.retryQueue.length }} queued
                  </h3>
                  <p
                    class="mt-token-2 text-sm"
                    [class]="snapshotToneClass(data.snapshotStatus)"
                  >
                    {{ data.snapshotStatus.detail }}
                  </p>
                </div>

                @if (data.retryQueue.length === 0) {
                  <app-empty-state
                    title="No retries are waiting"
                    description="When the orchestrator schedules another attempt, it will appear here."
                  />
                } @else {
                  <div class="mt-token-5 space-y-token-3">
                    @for (retry of data.retryQueue; track retry.identifier) {
                      <div
                        class="rounded-panel border border-line bg-bg/70 p-token-4"
                      >
                        <div class="flex flex-wrap items-center gap-token-2">
                          <a
                            [routerLink]="['/issues', retry.identifier]"
                            class="text-lg font-semibold transition-colors duration-base ease-standard hover:text-accent"
                          >
                            {{ retry.identifier }}
                          </a>
                          <span
                            class="rounded-full border border-line px-token-3 py-token-1 text-xs uppercase tracking-ui text-muted"
                          >
                            {{ retry.attemptLabel }}
                          </span>
                        </div>
                        <p class="mt-token-2 text-sm text-muted">
                          <span class="font-medium text-fg">Due:</span>
                          {{ retry.dueAt }}
                        </p>
                        <p class="mt-token-2 text-sm text-muted">
                          <span class="font-medium text-fg">Error:</span>
                          {{ retry.error }}
                        </p>
                        <p class="mt-token-2 text-sm text-muted">
                          <span class="font-medium text-fg"
                            >Prior session:</span
                          >
                          {{ retry.priorSessionLabel }}
                        </p>
                        <p class="mt-token-2 text-sm text-muted">
                          <span class="font-medium text-fg">Workspace:</span>
                          {{ retry.workspacePath }}
                        </p>
                      </div>
                    }
                  </div>
                }
              </article>
            </section>
          }
        }
      }
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class RunsPageComponent {
  private readonly runtimeApi = inject(RuntimeApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly state = signal<RunsState>({ kind: "loading" });
  readonly runsData = computed(() => {
    const state = this.state();
    return state.kind === "ready" ? state.data : null;
  });
  readonly runsError = computed(() => {
    const state = this.state();
    return state.kind === "error" ? state.error : null;
  });

  constructor() {
    this.load();
  }

  load(): void {
    this.state.set({ kind: "loading" });
    this.runtimeApi
      .loadRuns()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (data) => this.state.set({ kind: "ready", data }),
        error: (error: RuntimeUiError) =>
          this.state.set({ kind: "error", error })
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
        return "Runs unavailable";
    }
  }

  errorTitle(error: RuntimeUiError): string {
    switch (error.kind) {
      case "stale":
        return "The runs snapshot expired before this view could use it";
      case "timeout":
        return "The backend timed out while loading the runs view";
      case "unavailable":
        return "Runtime state is currently unavailable";
      default:
        return "The runs view could not load";
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
    return "text-muted";
  }
}
