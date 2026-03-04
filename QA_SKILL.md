# QA Skill — Demo Hub Heuristic Checklist

This skill defines what to look for when exploring each screen of a tenant demo. Apply every check on every screen you visit. Flag anything that fails as a bug.

---

## How to use this skill

For each screen you land on, run through all four categories below. Not every check will be relevant on every screen — use judgment. If a check clearly doesn't apply (e.g. "form validation" on a read-only dashboard), skip it. If it applies and fails, log a bug.

---

## 1. Functional Checks (P0 / P1)

These are the highest priority. A functional failure means something doesn't work as expected.

### Navigation & Routing
- [ ] Every nav item leads to the correct screen
- [ ] No nav item throws a 404, blank page, or error state
- [ ] Browser back/forward buttons work correctly
- [ ] Deep links (direct URLs) load the correct screen without errors
- [ ] Clicking on any avatar, thumbnail, or card navigates correctly (does not redirect to login)

### Forms & Inputs
- [ ] All input fields accept the expected data types
- [ ] Required field validation triggers on submit (not silently ignored)
- [ ] Submitting a valid form produces the expected result
- [ ] Submitting an empty/invalid form shows a meaningful error — not a blank screen or crash
- [ ] File uploads (if present) work and show confirmation
- [ ] Date pickers, dropdowns, and selects open and return correct values

### Data & State
- [ ] Data displayed matches what was created/edited (no stale state)
- [ ] Deleting an item removes it from the list without page reload errors
- [ ] Creating an item adds it immediately without requiring manual refresh
- [ ] Filters and search return accurate results
- [ ] Pagination works (next/prev, page numbers)
- [ ] Sorting columns (if present) correctly reorder data

### Modals & Overlays
- [ ] All modals open and close correctly
- [ ] Pressing Escape closes modals
- [ ] Clicking outside a modal closes it (if expected)
- [ ] Modals don't appear behind other elements
- [ ] Confirm/cancel actions in modals produce the correct outcome

### Authentication & Access
- [ ] Logout works and redirects to login
- [ ] Accessing a protected URL when logged out redirects to login (not a blank/error page)
- [ ] User role/permissions are respected (if applicable)

---

## 2. UX Checks (P1 / P2)

These catch usability issues that make the product harder to use, even if technically functional.

### Visibility of System Status
- [ ] Loading states are shown for async operations (spinners, skeletons, progress bars)
- [ ] Success feedback is shown after completing an action (toast, confirmation message)
- [ ] Error states are clearly communicated — not just a red border with no message
- [ ] Active nav items are visually highlighted

### Clarity & Language
- [ ] Labels, headings, and CTAs use plain language — no internal jargon or abbreviations
- [ ] Empty states have helpful messages (not just blank space)
- [ ] Tooltip or help text is present on complex or non-obvious fields
- [ ] Error messages explain what went wrong and how to fix it

### User Control & Freedom
- [ ] Users can cancel out of any action (modals, multi-step flows, forms)
- [ ] Destructive actions (delete, archive) have a confirmation step
- [ ] Multi-step flows show progress and allow going back
- [ ] Accidental navigation doesn't lose unsaved form data without warning

### Consistency
- [ ] Button styles are consistent (primary, secondary, destructive)
- [ ] Icon usage is consistent — same icon always means the same thing
- [ ] Date/time formats are consistent across screens
- [ ] Terminology is consistent — same entity is not called different names on different screens

### Efficiency
- [ ] Common actions are accessible without deep navigation (not buried 3 levels deep)
- [ ] Tables/lists have bulk actions if managing multiple items is a core use case
- [ ] Search is available where lists are long
- [ ] Keyboard navigation works on interactive elements (Tab, Enter, Space)

---

## 3. Visual / UI Checks (P2 / P3)

These catch defects in the visual layer that degrade the perceived quality of the product.

### Layout
- [ ] No overlapping text or elements
- [ ] No content cut off or hidden behind other elements
- [ ] Cards, tables, and lists are properly aligned
- [ ] Padding and spacing is consistent — no elements touching the edge of containers
- [ ] Long text is handled gracefully (truncation with tooltip, or wrapping)

### Responsiveness (if applicable)
- [ ] No horizontal scroll at standard viewport widths
- [ ] No broken layouts at 1280px, 1440px, and 1920px widths
- [ ] Modals fit within the viewport

### Typography
- [ ] Font sizes are consistent with hierarchy (heading > subheading > body > caption)
- [ ] No text rendering issues (invisible text, wrong contrast, text on same-colour background)
- [ ] No placeholder text left visible in production

### Imagery & Icons
- [ ] No broken image links (empty boxes, alt text showing)
- [ ] Icons are correctly sized and aligned with their labels
- [ ] Avatars/thumbnails load correctly and are not distorted

### Colour & Branding
- [ ] Interactive elements (links, buttons) have visible hover and focus states
- [ ] Disabled states are visually distinct from active states
- [ ] Brand colours are applied consistently

---

## 4. Performance Checks (P1 / P2)

These catch slowness or unresponsiveness that would frustrate a real user.

### Load Times
- [ ] Initial page load completes within ~3 seconds on a normal connection
- [ ] Navigating between screens feels immediate (< 1 second) for pre-loaded routes
- [ ] Data tables with many rows load without freezing the page

### Responsiveness Under Interaction
- [ ] Clicking a button produces visible feedback within 300ms
- [ ] Scrolling is smooth — no jank or lag on lists/tables
- [ ] Typing in search/filter inputs is responsive — no input lag

### Error Resilience
- [ ] The page does not crash (white screen) if an API call fails — a graceful error state is shown
- [ ] Network errors (simulated by slow navigation) produce a user-friendly message, not a silent failure

---

## Bug Severity Quick Reference

| Category | Typical Prio | Example |
|----------|-------------|---------|
| Crash / white screen | P0 | Clicking avatar throws unhandled error |
| Broken core flow | P0 | Cannot create/save a primary entity |
| Broken secondary flow (workaround exists) | P1 | Edit works but requires page refresh |
| Missing feedback / confusing UX | P1–P2 | No success toast after saving |
| Visual defect (layout/spacing) | P2–P3 | Card text overflows container |
| Cosmetic inconsistency | P3 | Button uses wrong colour variant |
| Performance slow but usable | P2 | Table takes 4s to load |
| Performance degraded on interaction | P1 | Typing in search causes visible lag |
