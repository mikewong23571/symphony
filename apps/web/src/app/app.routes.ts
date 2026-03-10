import { Routes } from "@angular/router";

import { DashboardPageComponent } from "./features/dashboard/dashboard-page.component";
import { IssueDetailPageComponent } from "./features/issues/issue-detail-page.component";

export const routes: Routes = [
  {
    path: "",
    title: "Symphony Runtime",
    component: DashboardPageComponent
  },
  {
    path: "issues/:id",
    title: "Issue Runtime",
    component: IssueDetailPageComponent
  },
  {
    path: "**",
    redirectTo: ""
  }
];
