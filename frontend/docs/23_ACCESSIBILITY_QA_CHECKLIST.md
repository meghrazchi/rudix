# Accessibility QA Checklist (F177)

Rudix targets WCAG 2.1 AA as the baseline. This document covers what was implemented in the F177 accessibility pass and provides a checklist for ongoing QA.

---

## What was fixed in F177

### App shell (`AppShell.tsx`)

| Fix                                                           | Detail                                                                                                                                                         |
| ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Skip navigation link                                          | `<SkipLink>` rendered before the sidebar; targets `#main-content`                                                                                              |
| `<main id="main-content" tabIndex={-1}>`                      | Gives the skip link a focusable target                                                                                                                         |
| `aria-current="page"` on active nav link                      | Screen readers now announce the current page in the sidebar nav                                                                                                |
| Disabled nav items are keyboard-reachable                     | Changed from `<div aria-disabled>` to `role="link" tabIndex={0} aria-disabled` with a full accessible label including the disabled reason                      |
| Notifications button aria-label includes unread count         | When `count > 0`, label becomes `"{count} unread notifications"` so AT announces the count                                                                     |
| Mobile menu button aria-label + aria-expanded + aria-controls | `aria-label="Open navigation menu"`, `aria-expanded`, `aria-controls="mobile-sidebar"`                                                                         |
| Mobile sidebar close button aria-label                        | `aria-label="Close navigation menu"`                                                                                                                           |
| Primary nav `aria-label` on the `<nav>` element               | `NavList` accepts `ariaLabel` and sets `<nav aria-label="Primary navigation">`                                                                                 |
| Command menu result sections labelled                         | Section headers use `id` + `aria-labelledby` on the `<section>`                                                                                                |
| Command menu result links get `focus-visible` ring            | `focus-visible:ring-2 focus-visible:ring-[#3525cd]`                                                                                                            |
| Route-change announcer                                        | Polite `aria-live="polite" role="status"` + assertive `aria-live="assertive" role="alert"` regions injected into the DOM; route changes announce the page name |
| Sidebar toggle `focus-visible` ring                           | Added to collapse/expand button                                                                                                                                |
| Help and profile buttons `focus-visible` ring                 | Added                                                                                                                                                          |

### FeedbackModal (`FeedbackModal.tsx`)

| Fix                                                            | Detail                                                                                                        |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `useOverlayFocus` for real focus trap                          | Replaced manual `keydown` listener with the shared `useOverlayFocus` hook (Tab cycling, Escape, return focus) |
| `aria-labelledby` pointing to `<h2 id="feedback-modal-title">` | Proper modal title association instead of `aria-label` on the overlay div                                     |
| `role="dialog"` on the inner panel div                         | Moved from the backdrop div to the focusable white card                                                       |
| Comment char-count is `aria-live="polite"`                     | `<p id="feedback-comment-count" aria-live="polite" aria-atomic="true">`                                       |
| Textarea `aria-describedby="feedback-comment-count"`           | AT announces the counter when it changes                                                                      |
| Footer buttons `focus-visible` ring                            | Added to all three action buttons                                                                             |

### DocumentPreviewModal (`DocumentPreviewModal.tsx`)

| Fix                               | Detail                                                    |
| --------------------------------- | --------------------------------------------------------- |
| Close button `focus-visible` ring | Added `focus-visible:ring-2 focus-visible:ring-[#3525cd]` |

### i18n strings added (`appShell` namespace, all 4 locales)

| Key                   | Value (EN)                     |
| --------------------- | ------------------------------ |
| `skipToMainContent`   | "Skip to main content"         |
| `primaryNav`          | "Primary navigation"           |
| `notificationsUnread` | "{count} unread notifications" |
| `navigatedTo`         | "Navigated to {page}"          |

### Utilities added

- `src/components/layout/SkipLink.tsx` — i18n-aware skip-to-content link
- `src/lib/a11y.ts` — `announce()` helper for programmatic live-region updates

---

## Automated test coverage added

| File                                              | Tests                                                                                                                                                                               |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/components/layout/accessibility.test.tsx`    | 23 tests: skip link, landmark structure, `aria-current`, disabled nav keyboard access, live regions, notifications button, mobile sidebar dialog, command menu dialog, profile menu |
| `src/components/chat/FeedbackModal.a11y.test.tsx` | 10 tests: dialog role/aria-labelledby, close button label, Escape key, fieldset structure, textarea/char-count association, button states, backdrop click                           |

---

## Manual keyboard QA checklist

Run these steps in a browser with keyboard only (no mouse). Chrome + macOS or Windows works well.

### Global

- [ ] Tab from URL bar into the page — first focusable element is the **skip link** ("Skip to main content").
- [ ] Activate the skip link — focus moves to `<main>` (no visible outline on main is fine since it uses `focus:outline-none`).
- [ ] All interactive elements (nav links, buttons, inputs, links) receive a visible blue ring on focus.
- [ ] No keyboard trap occurs outside of open modals.

### Navigation sidebar

- [ ] Tab through sidebar nav links — each receives a focus ring.
- [ ] Active link announces `current page` via screen reader.
- [ ] Disabled links are reachable via Tab and announce their disabled reason.
- [ ] Collapse/expand button is reachable and announces its label.

### Mobile menu (narrow viewport)

- [ ] Tab to "Menu" button — `aria-expanded="false"` is announced.
- [ ] Activate button — sidebar dialog opens, focus moves to close button.
- [ ] Tab cycles within the dialog (focus trap).
- [ ] Press Escape — dialog closes, focus returns to Menu button.

### Command menu (⌘/Ctrl + K)

- [ ] Keyboard shortcut opens the modal.
- [ ] Focus moves to search input.
- [ ] Tab cycles within the modal.
- [ ] Results are navigable with Tab.
- [ ] Press Escape — modal closes, focus returns to the search trigger button.

### Profile menu

- [ ] Activate profile button — menu opens, first item receives focus.
- [ ] Press Escape — menu closes.
- [ ] Tab/Shift+Tab navigate menu items.

### Feedback modal (chat page)

- [ ] Open feedback modal from a chat response — focus enters the dialog.
- [ ] Radio groups are navigable with arrow keys.
- [ ] Comment textarea is reachable and correctly labelled.
- [ ] Char count updates are announced.
- [ ] Close dialog with Escape — focus returns to the feedback button.

### Document preview modal (chat page)

- [ ] Open preview from a citation — focus enters the dialog.
- [ ] Close button is visible and focusable with a focus ring.
- [ ] Press Escape — modal closes and focus returns to the citation link.

---

## Screen-reader spot checks

Use **VoiceOver** (macOS, Safari/Chrome) or **NVDA** (Windows, Firefox/Chrome).

- [ ] **Page title** is announced on load and on route change.
- [ ] **Route change announcements**: when navigating between pages, the polite live region announces "Navigated to {page}".
- [ ] **Chat answer**: each AI answer paragraph is read in order; citations are announced as links.
- [ ] **Upload flow**: document status changes (processing → indexed / failed) are announced if the component uses `role="status"` or updates a live region.
- [ ] **Error states**: `role="alert"` causes errors to be read immediately.
- [ ] **Notification badge**: button reads as "3 unread notifications" when count > 0.

---

## Contrast and sizing notes

Contrast was not audited programmatically in F177. When running an audit:

- Use `axe-core` in browser DevTools (Axe Chrome extension or `@axe-core/playwright` in E2E tests).
- Key brand colours to audit: `#3525cd` on `#f7f5ff` background (sidebar active), white text on `#3525cd` button.
- Touch target minimum: 44 × 44 CSS pixels. All top-bar icon buttons are `h-10 w-10` (40 × 40). Consider increasing to `h-11 w-11` in a follow-up if auditing on mobile.

---

## Known gaps deferred to follow-up

| Area                               | Deferred item                                                                    |
| ---------------------------------- | -------------------------------------------------------------------------------- |
| Chat message list                  | Announce new AI responses via a live region (complex integration with streaming) |
| File upload drag-and-drop          | Keyboard-accessible drag-and-drop alternative needed                             |
| `@axe-core/playwright` integration | Automated contrast + ARIA lint in E2E suite                                      |
| Admin data tables                  | Column sort announcements, row selection accessible name                         |
| Touch target size                  | Some icon buttons are 40×40 (below the 44×44 recommended target)                 |
