import { bootstrapApplication } from "@angular/platform-browser";
import { Component } from "@angular/core";

@Component({
  selector: "app-root",
  standalone: true,
  template: `
    <main class="min-h-screen bg-bg text-fg">
      <section class="mx-auto max-w-5xl px-token-6 py-token-8">
        <div
          class="rounded-panel border border-line bg-surface p-token-6 shadow-panel"
        >
          <p class="mb-token-2 text-sm uppercase tracking-[0.18em] text-muted">
            Symphony
          </p>
          <h1 class="text-3xl font-semibold">Operator Dashboard Skeleton</h1>
          <p class="mt-token-3 max-w-2xl text-base text-muted">
            Angular, Tailwind CSS, and tokenized theming are wired in. Feature
            modules live under
            <code>src/app/features</code>.
          </p>
        </div>
      </section>
    </main>
  `
})
class AppComponent {}

bootstrapApplication(AppComponent).catch((error: unknown) => {
  console.error(error);
});
