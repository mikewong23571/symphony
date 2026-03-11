import { ChangeDetectionStrategy, Component, input } from "@angular/core";
import { MatIconModule } from "@angular/material/icon";

@Component({
  selector: "app-empty-state",
  standalone: true,
  imports: [MatIconModule],
  template: `
    <div class="empty-state">
      <mat-icon class="empty-icon" aria-hidden="true">inbox</mat-icon>
      <p class="empty-title mat-subtitle-1">{{ title() }}</p>
      <p class="empty-description mat-body-2 tone-muted">{{ description() }}</p>
    </div>
  `,
  styles: [
    `
      .empty-state {
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 2rem;
        text-align: center;
        border: 2px dashed #d7d0c3;
        border-radius: 1rem;
        background: rgba(244, 242, 234, 0.5);
      }
      .empty-icon {
        font-size: 2.5rem;
        width: 2.5rem;
        height: 2.5rem;
        color: #6e6558;
        margin-bottom: 0.75rem;
      }
      .empty-title {
        font-weight: 500;
        margin: 0 0 0.5rem;
      }
      .empty-description {
        margin: 0;
      }
    `
  ],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class EmptyStateComponent {
  readonly title = input.required<string>();
  readonly description = input.required<string>();
}
