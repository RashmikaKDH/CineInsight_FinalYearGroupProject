# User Account Navigation and Saved Reports Implementation Report

**Project:** CineInsight  
**Workspace:** `C:\Users\Rashmika\Documents\GitHub\CineInsight_FinalYearGroupProject\CineInsight`  
**Date:** 2026-10-19  

---

## 1. Executive Summary

This report documents the implementation of the shared user account panel, navigation overhaul, and saved-reports library in the CineInsight web application. The implementation replaces ad-hoc navigation and the legacy Colab import UI with a reusable, accessible header component, dynamic account dropdown, a dedicated Saved Reports library, and a recent reports section on the user profile page.

All changes preserve existing model execution pipelines, background thread processing, CSRF protection, report ownership isolation, and database schemas.

---

## 2. Changes Made and Files Affected

### 2.1 Reusable UI Components
- **`templates/components/account_panel.html` (New)**:
  - Reusable Jinja2 component rendering the user's initial avatar and dropdown toggle button.
  - Dropdown menu displaying:
    - User display name and email address.
    - Navigation link to **My Profile** (`/profile`).
    - Navigation link to **My Reports** (`/reports`).
    - Conditional navigation link to **Admin Panel** (`/admin`), displayed strictly when `session.get('user_role') == 'Admin'`.
    - **Sign Out** form submitting via `POST` to `/logout` (with fallback support for standard GET if required).
  - Full ARIA attributes (`aria-haspopup="menu"`, `aria-expanded="false"`, `role="menu"`, `role="menuitem"`, `tabindex`).

- **`templates/components/header.html` (New)**:
  - Reusable primary navigation header containing the CineInsight brand logo, primary navigation links (**Dashboard**, **Reports**, and optional **Admin** pill badge), and the account panel component.

### 2.2 Styles and Client-Side Logic
- **`static/account_panel.css` (New)**:
  - CSS styling scoped to `.cine-header`, `.account-panel`, `.account-dropdown`, and `.user-avatar`.
  - Harmonious dark-mode styling with subtle borders, gradients, and elevation shadows matching CineInsight's design system.
  - Accessible focus states (`:focus-visible`), smooth transitions, and badge styling for Admin roles.
  - Responsive breakpoints for tablets (`max-width: 680px`) and mobile screens (`max-width: 480px`).

- **`static/account_panel.js` (New)**:
  - Toggles dropdown open/closed on click.
  - Handles outside click detection and blur/focus-out events to close the menu.
  - Accessible keyboard navigation:
    - `Enter` / `Space` to toggle dropdown.
    - `Escape` closes the dropdown and returns focus to the toggle trigger.
    - `ArrowDown` / `ArrowUp` cycles focus through interactive menu items.
    - `Home` / `End` focuses the first or last menu item.
  - Deterministic avatar color gradient generation based on the user's name character codes.

- **`static/profile.css` (Modified)**:
  - Added layout and card styles for the new "My Reports" section on the profile page (`.profile-reports-section`, `.reports-grid`, `.report-card`, `.report-metric-chip`, `.reports-empty-state`).

- **`static/reports.css` (Modified)**:
  - Added styles for the Saved Reports Library view, report cards, metric chips (sentiment, sarcasm rate, analyzed segments count), and library empty states.

### 2.3 Backend Services and Routes
- **`services/report_import.py` (Modified)**:
  - **`get_user_saved_reports(instance_path, user_id, limit=None)`**:
    - Scans `imported_reports/<sha256(user_id)>/` for saved report `.json` files.
    - Strictly isolates report access to the authenticated user's hashed folder.
    - Optionally enriches reports with database metadata (title, date) via `get_analyses_for_user(user_id)` without blocking if the database is unavailable.
    - Extracts saved metadata (title, URL, date, positive sentiment score, sarcasm rate, segment count) without calling external YouTube or Gemini APIs.
    - Sorts reports chronologically (newest first) and supports optional `limit` parameter.
  - **`library()` (`/reports`)**:
    - When accessed normally via `GET`, renders the Saved Reports Library (`reports.html`).
    - Transparently delegates to `handle_manual_import()` if a `POST` request, `analysis_id`, or `import` query parameter is present (maintaining backward compatibility).
  - **`manual_import()` (`/reports/import`)**:
    - Dedicated authenticated backup route serving the legacy Colab CSV manual import tool.

- **`app.py` (Modified)**:
  - Updated `/profile` route to retrieve the latest 5 saved reports using `get_user_saved_reports(app.instance_path, session['user_id'], limit=5)`.
  - Added session fallback data for `user` dictionary if the MySQL database is unreachable or disconnected, preventing 500 errors.
  - Passes `saved_reports` list to `templates/profile.html`.

### 2.4 Templates Updated
- **`templates/index.html` (Modified)**:
  - Header actions: If authenticated, displays a "Go to Dashboard" link and the reusable account panel; if unauthenticated, displays "Sign In" and "Sign Up / Get Started".
  - Hero action buttons: Similarly displays "Go to Dashboard" for logged-in users and "Get Started" for visitors.
- **`templates/dashboard.html` (Modified)**:
  - Replaced ad-hoc header with `templates/components/header.html`.
  - Removed old standalone "Import Colab Report / Saved Reports →" text link.
  - Retained video search, duration filter, cancel search, video selection, and Analyze button functionality intact.
- **`templates/profile.html` (Modified)**:
  - Integrated `templates/components/header.html`.
  - Added "My Reports" section displaying recent reports with metrics, "View Report" actions, and a "View all reports" link to `/reports`.
  - Included a clean, informative empty state for users without saved reports.
- **`templates/reports.html` (Modified)**:
  - Re-architected into the Saved Reports Library.
  - Displays total reports count, responsive grid of report cards with sentiment/sarcasm metrics, direct links to view results, and CSV download links.
  - Includes a subtle fallback link at the footer to the manual import tool (`/reports/import`).
- **`templates/report_import.html` (New)**:
  - Dedicated template for manual Colab CSV imports preserving CSRF token (`report_token`), analysis selection, file validation, and error banners.
- **`templates/report_base.html` (Modified)**:
  - Integrated reusable header and included `account_panel.css` / `account_panel.js` across all report views (including progress and final analysis views).
- **`templates/admin.html` (Modified)**:
  - Integrated `templates/components/header.html` with Admin badge indication.

---

## 3. Final Navigation and Report-Access Behavior

| Page | Unauthenticated Behavior | Authenticated (User) Behavior | Authenticated (Admin) Behavior |
| :--- | :--- | :--- | :--- |
| **Home (`/`)** | Shows "Sign In" and "Sign Up" links in header and hero. | Shows "Dashboard" button + Account Panel in header; "Go to Dashboard" in hero. | Same as User, with Admin role badge in dropdown. |
| **Dashboard (`/dashboard`)** | Redirects to `/signin`. | Shared header with Dashboard active, Reports link, Account Panel. Standalone Colab link removed. | Same as User + Admin link in dropdown and header. |
| **Profile (`/profile`)** | Redirects to `/signin`. | Shows profile details + "My Reports" section (latest 5 reports) + empty state if none. | Same as User + Admin role indicator. |
| **Reports Library (`/reports`)** | Redirects to `/signin`. | Displays full list of saved reports with sentiment, sarcasm rate, and links to view or download CSV. | Same as User. |
| **Manual Import (`/reports/import`)** | Redirects to `/signin`. | Allows uploading Colab CSV against existing analysis history with CSRF verification. | Same as User. |
| **Analysis Progress & Results** | Redirects to `/signin`. | Shared header with brand navigation and Account Panel accessible throughout execution. | Same as User + Admin link in dropdown. |
| **Admin Panel (`/admin`)** | Redirects to `/signin`. | Blocked by `@admin_required` (403 or redirect). | Full admin dashboard with shared header. |

### Account Dropdown Behavior
- Clicking the avatar button toggles the menu.
- Keyboard navigation:
  - `Escape` closes the dropdown and restores focus to the trigger button.
  - `ArrowDown` / `ArrowUp` navigates through menu items.
  - Outside click closes the dropdown.
- Sign Out performs a `POST` request to `/logout`, destroying the server session.

---

## 4. Treatment of the Legacy Manual Import Feature

1. **Separation from Primary Navigation**:
   - The prominent Colab import upload form and instructions were removed from `/reports` and `/dashboard`.
   - The legacy import feature has been relocated to a dedicated route at `/reports/import` (`templates/report_import.html`).
2. **Backward Compatibility**:
   - The `/reports` route retains backward-compatibility logic: if invoked via `POST`, or with query parameters `?analysis_id=...` or `?import=1`, it transparently routes to `handle_manual_import()`. This ensures older links, bookmarks, and existing tests continue to function seamlessly.
3. **Security and Integrity Maintained**:
   - CSRF token validation (`report_token`) via `secrets.compare_digest` is strictly preserved.
   - User ownership verification (`analysis_history(session['user_id'])`) is strictly enforced; users cannot associate imported CSVs with another user's analysis record.
   - File size limits (5 MB) and CSV parsing logic (`parse_report`) remain identical.

---

## 5. Verification and Checks Run

### 5.1 Automated Test Suites (pytest)
All tests were executed using the project's virtual environment (`venv\Scripts\python -m pytest`):

```powershell
venv\Scripts\python -m pytest tests/test_account_navigation.py tests/test_report_import.py tests/test_automated_flow.py tests/test_analyze_flow.py -v
```

**Results:**
- `tests/test_account_navigation.py`: **13/13 PASSED**
  - `test_analysis_page_renders_account_panel`: PASSED
  - `test_dashboard_removed_old_import_link`: PASSED
  - `test_get_user_saved_reports_isolation_and_limit`: PASSED
  - `test_home_page_logged_in`: PASSED
  - `test_home_page_logged_out`: PASSED
  - `test_manual_import_backup_route_auth_and_rendering`: PASSED
  - `test_profile_my_reports_empty_state`: PASSED
  - `test_profile_my_reports_with_data`: PASSED
  - `test_reports_library_empty_state`: PASSED
  - `test_reports_library_normal_view`: PASSED
  - `test_results_page_renders_account_panel`: PASSED
  - `test_shared_account_panel_admin_role`: PASSED
  - `test_shared_account_panel_user_role`: PASSED
  - `test_shared_header_across_authenticated_pages`: PASSED
- `tests/test_report_import.py`: **5/5 PASSED**
  - `test_actual_report`: PASSED
  - `test_history_selection_and_rejection`: PASSED
  - `test_history_unavailable`: PASSED
  - `test_import_render_and_duplicate`: PASSED
  - `test_validation_and_auth`: PASSED
- `tests/test_automated_flow.py`: **5/5 PASSED**
  - `test_database_upsert_uses_one_transaction`: PASSED
  - `test_full_background_flow_saves_db_result_and_download`: PASSED
  - `test_partial_and_database_failure_preserve_result`: PASSED
  - `test_restart_does_not_restart_processing`: PASSED
  - `test_start_idempotence_owner_and_auth`: PASSED
- `tests/test_analyze_flow.py`: **10/10 PASSED**
  - `TestSSEProgressStages` (4 tests): PASSED
  - `TestRedirectConditions` (4 tests): PASSED
  - `TestAnalysisHistoryPreselection` (2 tests): PASSED

**Total: 34 passed, 4 subtests passed, 0 failures.**

### 5.2 Verification Methodology Clarification
> **Note on Verification Scope**:  
> Automated unit, integration, and HTTP rendering tests were executed against the Flask test client using simulated session states and mock database/filesystem fixtures. No live MySQL service or live browser-driven automation (e.g., Selenium/Playwright) was invoked during this test execution run.

---

## 6. Remaining Limitations and Notes

1. **Report Titles in Offline Mode**:
   - If a saved report was generated without recording an explicit video title in the database, `get_user_saved_reports()` uses the saved YouTube URL or report ID hash. As per constraints, external YouTube/Gemini API calls are intentionally avoided during list rendering to maintain low latency and eliminate external dependency risks.
2. **Background Thread Concurrency**:
   - The automatic pipeline uses Python in-process background worker threads. While navigating away or logging out does not terminate processing in the current process, deploying across multi-process WSGI servers without a shared job queue (such as Celery/Redis) would require process-affinity for progress monitoring.
3. **Database Schema**:
   - Zero database migrations or schema alterations were required. All report metadata is persisted via the existing JSON/CSV file storage in `imported_reports/<sha256(user_id)>/`, with optional lookup enrichment via the existing database schema.
