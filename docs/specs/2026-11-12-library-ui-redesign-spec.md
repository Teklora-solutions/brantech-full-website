# Knowledge Library UI redesign — Tasks #35 / #40

## Problem

The delivered library has functional pages but visually resembles a scaffold: raw navigation links, weak search/action hierarchy, an unhelpful empty state, raw machine-state badges, stacked unstructured forms, and pagination even when empty. The operator requested a redesign of the complete flow using the existing Teklora admin shell.

## Design contract

- Retain the existing admin sidebar/header and shared light/dark theme variables. No new framework, feature toggle, permission changes, or production data migration.
- Use a clear page header with breadcrumb, title, concise supporting copy and primary upload CTA; segmented navigation separates documents, processing clearance and public review. Navigation exposes only permitted destinations and uses `aria-current`.
- Document browsing: permission-filtered summary cards, a full-width search/filter toolbar, readable document rows with format icon, title, owner/date and independent human-readable processing/public badges. Distinguish an empty library from zero search results and an empty review queue. Offer an actionable upload or reset CTA; omit pagination for a single page.
- Upload: two-column metadata/upload form plus a compact policy panel; styled, keyboard-accessible native file chooser enhanced with drag/drop and selected-file feedback. Client checks for size/extensions improve feedback but never replace server validation. Show real upload progress with success only after server confirmation; preserve normal POST behavior without JavaScript.
- Detail: document header/download action, independent lifecycle/status strip, escaped extracted preview, a concise facts/access sidebar, and focused disclosure panels for metadata, replacement, sharing and review actions. Use distinct clearance/public review sections and restrained destructive actions. No duplicate form field IDs.
- Style every field, error/help message, badge, loading state, queue and activity entry consistently. Use native form controls, visible focus, meaningful labels, responsive layouts, reduced-motion support and theme-aware colors.
- Add only ACL-filtered display summaries and optional processing-status filtering; counts must never expose inaccessible records. Preserve per-version POST validation and all backend authorization rules.

## Acceptance

Exercise empty/populated/search/review pages, upload validation and progress, detail/sharing/review workflows, desktop/mobile and both themes. Inspect screenshots in a real local browser, not just HTTP template rendering. Run affected Django tests against isolated PostgreSQL/pgvector with fake providers. Record any unverified behavior honestly.
