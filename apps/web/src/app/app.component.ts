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
        class="mx-auto flex min-h-screen max-w-7xl flex-col gap-token-8 px-token-4 py-token-6 lg:px-token-6"
      >
        <header
          class="rounded-panel border border-line bg-surface/95 p-token-6 shadow-panel backdrop-blur"
        >
          <p class="text-xs uppercase tracking-ui text-accent">
            Symphony Runtime
          </p>
          <h1 class="mt-token-2 text-display font-semibold">Runtime Monitor</h1>
        </header>

        <div class="flex flex-1 flex-col">
          <nav class="flex gap-token-6 border-b border-line">
            <a
              routerLink="/"
              routerLinkActive="border-accent text-fg"
              [routerLinkActiveOptions]="{ exact: true }"
              class="-mb-px border-b-2 border-transparent pb-token-3 text-sm text-muted transition-colors duration-fast ease-standard hover:text-fg"
            >
              Dashboard
            </a>
            <a
              [href]="fallbackUrl"
              class="-mb-px border-b-2 border-transparent pb-token-3 text-sm text-muted transition-colors duration-fast ease-standard hover:text-fg"
            >
              Django fallback
            </a>
          </nav>

          <div class="w-full max-w-4xl pt-token-6">
            <router-outlet />
          </div>
        </div>
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
