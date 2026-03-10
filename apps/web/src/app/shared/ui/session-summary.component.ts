import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input
} from "@angular/core";
import { IssueSessionSummaryViewModel } from "../lib/runtime-types";

@Component({
  selector: "app-session-summary",
  standalone: true,
  template: `
    <h3 class="mt-token-2 text-2xl font-semibold">{{ session().title }}</h3>
    <dl class="mt-token-4 space-y-token-3 text-sm">
      @for (row of rows(); track row.label) {
        <div class="flex items-start justify-between gap-token-4">
          <dt class="text-muted">{{ row.label }}</dt>
          <dd class="text-right font-mono font-medium text-fg">
            {{ row.value }}
          </dd>
        </div>
      }
    </dl>
  `,
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
