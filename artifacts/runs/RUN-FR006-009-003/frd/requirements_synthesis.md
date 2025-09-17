# Requirements Synthesis Export – Adjacency Map Extension

Generated: 2025-09-17T06:45:00Z
Source Captures: RUN-ALPHA-EXP-002 exploration, RUN-CRAWL-DEMO-001 BFS crawl, RUN-FR006-009-001 baseline selectors

## Feature: Corporate About Hub
- Story ID: STORY-FR-006-ABOUT
- User Story: As a prospect, I want to review the company's About page so I can understand mission statements before onboarding.
- Acceptance Criteria:
  1. When the About page is reached via crawl, then it is present in the crawl_result adjacency map.
  2. When synthesis exports selectors, then an `about_header` locator is available for downstream automation.
- Traceability:
  - Crawl evidence: source/crawl/crawl_result.json (depth map)
  - Selector package: selectors/about_selectors.json

## Feature: Team Directory Insights
- Story ID: STORY-FR-006-TEAM
- User Story: As a hiring manager, I want the Team page to enumerate staff so I can verify roster coverage.
- Acceptance Criteria:
  1. When BFS runs, then the Team page is captured with depth metadata.
  2. When selectors are generated, then `team_list` strategies exist for roster validation.
- Traceability:
  - Crawl evidence: source/crawl/crawl_result.json
  - Selector package: selectors/team_selectors.json

## Feature: Admin Audit Console
- Story ID: STORY-FR-006-ADMIN
- User Story: As a compliance officer, I want an Admin panel identified so that audit logs and user permissions can be reviewed quickly.
- Acceptance Criteria:
  1. When BFS emission occurs, then the Admin page entry is present with depth 2 in the adjacency map.
  2. When selectors export runs, then `audit_table` selector strategies are available for downstream audit assertions.
- Traceability:
  - Crawl evidence: source/crawl/crawl_result.json
  - Selector package: selectors/admin_selectors.json

## Shared Coverage Notes
- Exploration coverage summary: source/exploration/coverage_report.json
- Visited pages: source/exploration/visited_pages.jsonl
- Previous synthesis baseline: artifacts/runs/RUN-FR006-009-002/frd/stories_export.json
