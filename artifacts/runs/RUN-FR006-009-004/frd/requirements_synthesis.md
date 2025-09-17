# Requirements Synthesis Export – Adjacency DOM Capture

Generated: 2025-09-17T07:05:00Z
Source Captures: RUN-ALPHA-EXP-003 exploration/crawl, RUN-CRAWL-DEMO-001 adjacency map, RUN-FR006-009-003 baseline selectors

## Feature: Corporate About Hub
- Story ID: STORY-FR-006-ABOUT
- User Story: As a prospect, I want the mission statement visible on the About page so I can evaluate the company quickly.
- Acceptance Criteria:
  1. When the About page loads, the `section#mission` region renders the mission copy.
  2. When selectors export, the `mission_section` strategy includes `css=section#mission`.
- Traceability:
  - DOM: source/dom/about.html
  - Screenshot: source/screenshots/about.png
  - Selector package: selectors/about_selectors.json

## Feature: Team Directory Insights
- Story ID: STORY-FR-006-TEAM
- User Story: As a hiring manager, I want an accurate team roster so I can confirm coverage.
- Acceptance Criteria:
  1. When the Team page is captured, the `ul.team` list contains entries for each team member.
  2. When selectors export, the `team_member_item` strategy exposes `ul.team > li` nodes.
- Traceability:
  - DOM: source/dom/team.html
  - Screenshot: source/screenshots/team.png
  - Selector package: selectors/team_selectors.json

## Feature: Admin Audit Console
- Story ID: STORY-FR-006-ADMIN
- User Story: As a compliance officer, I want audit tables accessible so I can inspect user activity.
- Acceptance Criteria:
  1. When the Admin page loads, an audit table with header `User` is present.
  2. When selectors export, the `audit_table` strategy targets `table.audit`.
- Traceability:
  - DOM: source/dom/admin.html
  - Screenshot: source/screenshots/admin.png
  - Selector package: selectors/admin_selectors.json

## Coverage Notes
- Adjacency map depth entries: artifacts/runs/RUN-CRAWL-DEMO-001/crawl/crawl_result.json
- Exploration evidence: source/exploration/visited_pages.jsonl
- Previous stories baseline: artifacts/runs/RUN-FR006-009-003/frd/stories_export.json
