# TYPE_DEBT — healthcare-ui import sites not yet migrated

Pass 4 (this pass) completed StatCard → MetricCard migration for:
- quality/page.tsx
- prospective/page.tsx
- providers/ProvidersModals.tsx (import cleanup)
- disputes/page.tsx
- system/page.tsx
- developer/page.tsx
- users/page.tsx
- documents/page.tsx
- dashboards/CoderDashboard.tsx
- dashboards/AdminDashboard.tsx (import cleanup)
- components/OutreachSummaryCards.tsx

## Remaining `@/components/healthcare-ui` import sites (non-StatCard, but should eventually move to ui/ primitives)

These files still import from `healthcare-ui` but only use exports other than `StatCard`
(PageHeader, SectionHeader, EmptyState, ProgressBar, RiskBadge, DataRow, etc.).
They are NOT blocked — no deprecated StatCard renders remain.

| File | Remaining healthcare-ui exports used |
|------|--------------------------------------|
| src/app/attestations/page.tsx | MetricCard (already migrated), PageHeader, EmptyState |
| src/app/audit/page.tsx | PageHeader, EmptyState |
| src/app/batch/page.tsx | PageHeader, EmptyState |
| src/app/claims/ClaimsDetailPane.tsx | healthcare-ui primitives |
| src/app/claims/page.tsx | MetricCard (already migrated), PageHeader |
| src/app/cohorts/builder/page.tsx | PageHeader, SectionHeader |
| src/app/developer/page.tsx | PageHeader (StatCard removed this pass) |
| src/app/disputes/page.tsx | PageHeader (StatCard removed this pass) |
| src/app/documents/page.tsx | PageHeader, ProgressBar, EmptyState, etc. (StatCard removed) |
| src/app/emr-config/page.tsx | MetricCard (already migrated), PageHeader |
| src/app/hedis/page.tsx | PageHeader, SectionHeader |
| src/app/patients/[pid]/components/* | RAFTab, OverviewTab, etc. — no StatCard, non-metric exports |
| src/app/population/heatmap/page.tsx | MetricCard (already migrated), misc |
| src/app/pre-submission/page.tsx | MetricCard (already migrated) |
| src/app/prospective/page.tsx | PageHeader, EmptyState (StatCard removed this pass) |
| src/app/providers/page.tsx | MetricCard (already migrated), PageHeader |
| src/app/providers/ProvidersModals.tsx | SectionHeader (StatCard removed this pass) |
| src/app/providers/scorecard/page.tsx | healthcare-ui primitives |
| src/app/qa/page.tsx | MetricCard (already migrated) |
| src/app/quality/page.tsx | PageHeader, SectionHeader (StatCard removed this pass) |
| src/app/quality/tabs/StarsTab.tsx | SectionHeader only |
| src/app/recapture/page.tsx | MetricCard (already migrated) |
| src/app/roi/page.tsx | healthcare-ui primitives |
| src/app/submissions/page.tsx | MetricCard (already migrated) |
| src/app/system/page.tsx | PageHeader, SectionHeader (StatCard removed this pass) |
| src/app/users/page.tsx | PageHeader, SectionHeader, EmptyState (StatCard removed) |
| src/app/worklist/page.tsx | PageHeader only |
| src/components/dashboards/AdminDashboard.tsx | RiskBadge, ProgressBar, SectionHeader, PageHeader |
| src/components/dashboards/CoderDashboard.tsx | PageHeader, SectionHeader (StatCard removed) |
| src/components/dashboards/ProviderDashboard.tsx | MetricCard (already migrated), SectionHeader |
| src/components/model-comparison.tsx | SectionHeader, EmptyState |
| src/components/OutreachChannelBreakdown.tsx | EmptyState only |
| src/components/OutreachTemplateManager.tsx | EmptyState only |

## Next steps (pass 5+)

- Replace `PageHeader` with a local `<PageHeader>` in ui/ to remove
  the last `healthcare-ui` surface area
- Migrate `EmptyState`, `SectionHeader` to ui/ primitives
- Once `healthcare-ui.tsx` exports zero components, delete the file
