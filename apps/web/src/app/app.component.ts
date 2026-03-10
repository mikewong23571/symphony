import { ChangeDetectionStrategy, Component } from "@angular/core";
import { CommonModule } from "@angular/common";
import { RouterLink, RouterLinkActive, RouterOutlet } from "@angular/router";

@Component({
  selector: "app-root",
  standalone: true,
  imports: [CommonModule, RouterLink, RouterLinkActive, RouterOutlet],
  template: `
    <main
      class="min-h-screen bg-gradient-to-b from-surface via-bg to-bg text-fg"
    >
      <div
        class="mx-auto flex min-h-screen max-w-7xl flex-col px-token-4 py-token-6 lg:px-token-6"
      >
        <header
          class="rounded-panel border border-line bg-surface/95 p-token-6 shadow-panel backdrop-blur"
        >
          <div
            class="flex flex-col gap-token-4 lg:flex-row lg:items-end lg:justify-between"
          >
            <div class="max-w-3xl">
              <p class="text-xs uppercase tracking-ui text-accent">
                Symphony Runtime
              </p>
              <h1 class="mt-token-2 text-display font-semibold">
                Operator surface for live orchestration state
              </h1>
              <p class="mt-token-3 max-w-2xl text-body text-muted">
                Angular stays a consumer of the backend snapshot APIs. The
                Django HTML dashboard remains available as a fallback while this
                UI matures.
              </p>
            </div>
            <div
              class="rounded-panel border border-line bg-bg/75 px-token-4 py-token-3 text-sm text-muted"
            >
              <p class="font-medium text-fg">Data source</p>
              <p>/api/v1/state, /api/v1/refresh, /api/v1/:issue_identifier</p>
            </div>
          </div>
          <nav class="mt-token-6 flex flex-wrap gap-token-2 text-sm">
            <a
              routerLink="/"
              routerLinkActive="border-accent bg-accent text-surface"
              [routerLinkActiveOptions]="{ exact: true }"
              class="rounded-full border border-line px-token-4 py-token-2 transition-colors duration-base ease-standard"
            >
              Dashboard
            </a>
            <a
              routerLink="/runs"
              routerLinkActive="border-accent bg-accent text-surface"
              class="rounded-full border border-line px-token-4 py-token-2 transition-colors duration-base ease-standard"
            >
              Runs
            </a>
            <a
              [href]="fallbackUrl"
              class="rounded-full border border-line px-token-4 py-token-2 text-muted transition-colors duration-base ease-standard hover:border-accent hover:text-fg"
            >
              Django fallback
            </a>
          </nav>
        </header>

        <section class="flex-1 py-token-6">
          <router-outlet />
        </section>
      </div>
    </main>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class AppComponent {
  readonly fallbackUrl = resolveFallbackUrl();
}

function resolveFallbackUrl(): string {
  const origin = window.location.origin;

  if (origin.includes(":4200")) {
    return origin.replace(":4200", ":8000");
  }

  return `${origin}/`;
}
