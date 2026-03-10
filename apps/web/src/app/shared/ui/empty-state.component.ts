import { ChangeDetectionStrategy, Component, input } from "@angular/core";

@Component({
  selector: "app-empty-state",
  standalone: true,
  template: `
    <div
      class="mt-token-5 rounded-panel border border-dashed border-line bg-bg/70 p-token-5"
    >
      <p class="font-medium text-fg">{{ title() }}</p>
      <p class="mt-token-2 text-sm text-muted">{{ description() }}</p>
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class EmptyStateComponent {
  readonly title = input.required<string>();
  readonly description = input.required<string>();
}
