import { ChangeDetectionStrategy, Component } from "@angular/core";
import { RouterLink, RouterLinkActive, RouterOutlet } from "@angular/router";
import { MatToolbarModule } from "@angular/material/toolbar";
import { MatTabNav, MatTabLink, MatTabNavPanel } from "@angular/material/tabs";
import { MatIconModule } from "@angular/material/icon";
import { MatTooltipModule } from "@angular/material/tooltip";

@Component({
  selector: "app-root",
  standalone: true,
  imports: [
    RouterLink,
    RouterLinkActive,
    RouterOutlet,
    MatToolbarModule,
    MatTabNav,
    MatTabLink,
    MatTabNavPanel,
    MatIconModule,
    MatTooltipModule
  ],
  template: `
    <mat-toolbar class="app-header">
      <div class="header-inner">
        <span class="header-eyebrow">Symphony Runtime</span>
        <h1 class="header-title">Runtime Monitor</h1>
      </div>
      <span class="toolbar-spacer"></span>
      <a
        class="fallback-link"
        [href]="fallbackUrl"
        target="_blank"
        rel="noopener"
        matTooltip="Open Django admin"
        matTooltipPosition="left"
      >
        <mat-icon>open_in_new</mat-icon>
      </a>
    </mat-toolbar>

    <div class="app-body">
      <nav mat-tab-nav-bar [tabPanel]="tabPanel" class="app-nav">
        <a
          mat-tab-link
          routerLink="/"
          routerLinkActive
          #dashRla="routerLinkActive"
          [active]="dashRla.isActive"
          [routerLinkActiveOptions]="{ exact: true }"
        >
          Dashboard
        </a>
      </nav>

      <mat-tab-nav-panel #tabPanel>
        <div class="content-area">
          <router-outlet />
        </div>
      </mat-tab-nav-panel>
    </div>
  `,
  styles: [
    `
      :host {
        display: flex;
        flex-direction: column;
        min-height: 100vh;
      }
      .app-header {
        border-bottom: 1px solid #d7d0c3;
        padding: 0 1.5rem;
        flex-shrink: 0;
        height: auto;
        padding-top: 0.75rem;
        padding-bottom: 0.75rem;
      }
      .header-inner {
        display: flex;
        flex-direction: column;
      }
      .header-eyebrow {
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.18em;
        color: #b5532d;
      }
      .header-title {
        font-size: 2.25rem;
        font-weight: 600;
        margin: 0.25rem 0 0;
        line-height: 1.15;
      }
      .toolbar-spacer {
        flex: 1;
      }
      .fallback-link {
        display: flex;
        align-items: center;
        color: #6e6558;
        text-decoration: none;
        transition: color 150ms;
        &:hover {
          color: #1f1b16;
        }
      }
      .app-body {
        display: flex;
        flex-direction: column;
        flex: 1;
      }
      .app-nav {
        padding: 0 1.5rem;
      }
      .content-area {
        max-width: 64rem;
        width: 100%;
        padding: 1.5rem;
        margin: 0 auto;
      }
    `
  ],
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
