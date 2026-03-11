import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input
} from "@angular/core";
import { MatListModule } from "@angular/material/list";
import { IssueSessionSummaryViewModel } from "../lib/runtime-types";

@Component({
  selector: "app-session-summary",
  standalone: true,
  imports: [MatListModule],
  template: `
    <h3 class="session-title">{{ session().title }}</h3>
    <mat-list>
      @for (row of rows(); track row.label) {
        <mat-list-item>
          <span matListItemTitle class="tone-muted">{{ row.label }}</span>
          <span matListItemLine class="val-mono">{{ row.value }}</span>
        </mat-list-item>
      }
    </mat-list>
  `,
  styles: [
    `
      .session-title {
        font-size: 1.125rem;
        font-weight: 600;
        margin: 0 0 0.25rem;
      }
      mat-list {
        padding: 0;
      }
    `
  ],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class SessionSummaryComponent {
  readonly session = input.required<IssueSessionSummaryViewModel>();
  readonly rows = computed(() => {
    const s = this.session();
    return [
      { label: "Session", value: s.sessionId },
      { label: "Last event", value: s.event },
      { label: "Event time", value: s.eventAt },
      { label: "Turns", value: s.turns },
      { label: "Tokens", value: s.tokens }
    ];
  });
}
