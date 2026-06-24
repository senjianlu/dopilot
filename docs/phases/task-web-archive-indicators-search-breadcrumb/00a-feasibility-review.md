# Feasibility Review — Web Archive Indicators, Prefix Search, Breadcrumb, Sidebar Logo

Reviewer: Claude (implementation/test agent). Scope: feasibility only, no code
changed. Dependency `task-artifact-archive` was verified as already implemented
in-tree (see below), so this task can build on it.

## Verdict

**Feasible as briefed, with minor adjustments.** All four workstreams are
implementable with existing components and the existing `task-artifact-archive`
backend. No new dependencies, no migration, no runtime-semantics change. Two
concrete items need attention before/while implementing: (1) the backend list
path must avoid an N+1 and extend the existing batch helper, and (2) Tooltip
rendering in **vitest** needs a `TooltipProvider` (runtime already has one; the
test harness does not). Neither is blocking; both have clear fixes.

## Dependency check (task-artifact-archive)

Confirmed present, so this task's assumptions hold:
- `BuildArtifactView.archived` / `archived_at` exist
  (`apps/server/.../api/v1/schemas.py:84-85`); `build_artifact_view` derives them
  (`services/artifacts.py:289-290`).
- `get_bindable_artifact_or_404` (runnable AND unarchived) is separate from
  `get_runnable_artifact_or_404` (run/dispatch path does NOT re-check archive)
  — `services/artifacts.py:200-236`, `services/templates.py:78-117`. So "archive
  must not block bound runs" is already structurally guaranteed; this task adds
  no run-path changes.
- Web `BuildArtifact` type carries `archived` / `archived_at`
  (`lib/api/types.ts:112-113`); the template picker already excludes archived and
  keeps the current archived binding visible (`templates/page.tsx:130-146,
  400-412`). The brief's "picker behavior unchanged" is therefore free.

## Focus answers

### 1. Is `ExecutionTemplateView` the right place for `build_artifact_archived*`?

**Yes.** `ExecutionTemplateView` already exposes other live, artifact-derived
read-only fields (`artifact_type`, `project`, `version`) that are resolved from
the bound artifact rather than stored on the template, and `template_view()`
already takes an injected `artifact_type` arg
(`services/templates.py:316-332`, `api/v1/templates.py:43-44,53-63,73,91`). Adding
`build_artifact_archived: bool` + `build_artifact_archived_at: str | null` follows
the exact same "live property, not frozen snapshot" pattern. This keeps the web's
Schedules-from-templates derivation possible (see #2) without a second artifact
round-trip.

Implementation note (not blocking, but required to avoid N+1):
- `template_view(template, artifact_type)` currently receives only a type string.
  It must also receive archive state. Cleanest path: change the batch helper
  `artifact_types_for_templates` (`services/templates.py:301-313`) — which today
  selects `(id, artifact_type)` — into one that also selects `archived_at`, and
  return a small per-id record (type + archived_at) instead of just the type
  string. Then `template_view` derives `archived = archived_at is not None` and
  serializes `archived_at` with the already-imported `_iso`.
- The single-row paths (create/get/update) use `artifact_type_for_template`
  (`services/templates.py:285-298`), which fetches the artifact already — extend
  it (or add a sibling) to also surface `archived_at`. The artifact object is
  already loaded there, so it's free.
- Legacy/dangling binding (`build_artifact_id` null or artifact missing): default
  `archived = false`, `archived_at = null`. Confirm this is the intended default
  (it matches the `scrapy` fallback the code already uses).

### 2. Can Schedules derive archived indicators from `listTemplates`?

**Yes, cleanly.** `schedules/page.tsx` already calls `listTemplates()` in its
`load()` (`:165-169`) and resolves the row's template via
`templateName(id)` → `templates.find(t => t.id === id)` (`:123-125`). Once
`ExecutionTemplate` carries `build_artifact_archived`, the row can look up the
same template object and read the flag — no `ScheduleView` change, matching the
brief's "do not add artifact state to `ScheduleView` unless feasibility proves it
needed." Feasibility does **not** prove it needed. Keep `ScheduleView` untouched.

Caveat: if a schedule references a template id not present in the loaded list
(deleted/stale), the indicator simply doesn't render — same graceful fallback as
the existing `templateName` (it falls back to showing the id). Acceptable.

### 3. shadcn Tooltip / Breadcrumb composition & provider requirements

- Both components already exist: `components/ui/tooltip.tsx` (exports
  `Tooltip`, `TooltipTrigger`, `TooltipContent`, `TooltipProvider`) and
  `components/ui/breadcrumb.tsx` (full set incl. `BreadcrumbSeparator`,
  `BreadcrumbPage`). `lucide-react` (`^0.469.0`) and `radix-ui` (`^1.6.0`) are
  present. **No new deps.**
- **Provider — runtime is fine, tests are not.** `SidebarProvider` wraps the whole
  app tree in `<TooltipProvider delayDuration={0}>`
  (`components/ui/sidebar.tsx:131-149`), and `(app)/layout.tsx:21` mounts every
  page under it. So Tooltips on Templates/Schedules need **no** extra provider at
  runtime. **But** `renderWithProviders` (`lib/test/render.tsx`) wraps only
  `I18nextProvider` + `ConfirmProvider` — **no `TooltipProvider`**. A Radix
  `Tooltip` rendered without a provider ancestor throws. Recommended fix: have the
  shared archive-indicator component include its **own** `<TooltipProvider>`
  (nesting providers is safe in Radix) so it is self-contained in both contexts.
  Alternative: add `TooltipProvider` to `renderWithProviders`. Prefer the
  self-contained component — it also keeps the indicator drop-in for any future
  page. **Flag this in the brief** so the implementer doesn't discover it only at
  test time.
- Keyboard/focus accessibility: `TooltipTrigger` defaults to a focusable element
  via Radix; if the trigger wraps a bare `<svg>`/icon, wrap it in a
  `<button type="button">` (or pass `asChild` to a focusable element) so it is
  tab-reachable, satisfying "not hover-only." The lucide icon needs an
  `aria-label`/`aria-hidden` decision: the accessible name should come from the
  trigger, with the localized tooltip text as the description.

### 4. Collapsed sidebar logo clipping risk

Real but low-risk and self-contained. The header brand uses
`SidebarMenuButton size="lg"` with an inner `size-8` box and a `size-4` masked
logo (`app-sidebar.tsx:49-70`). In `collapsible="icon"` the rail collapses to
`--sidebar-width-icon: 3rem` (48px) and `size=lg` menu buttons get
`group-data-[collapsible=icon]` overrides from `sidebar.tsx`; the `size-8` (32px)
box plus button padding can exceed the icon slot and clip. Fix is CSS-only
(constrain the brand box / adjust padding under `group-data-[collapsible=icon]`),
no structural change. Risk: over-correcting could shift the expanded-state
layout — verify both states. This is visual-only; not coverable by vitest
(see test section).

## Blocking issues

None. The task can proceed.

## Risky assumptions

1. **N+1 on template list.** If `build_artifact_archived` is populated by fetching
   each template's artifact individually in `list_templates`, it regresses the
   list endpoint. Must extend the existing batch helper instead (see #1). Treat as
   a required implementation constraint, not optional.
2. **Test harness lacks `TooltipProvider`** (see #3). If unaddressed, new Tooltip
   tests (and any page test that renders a row with the indicator) will throw.
3. **Adding a required field to the `ExecutionTemplate` TS interface** will force
   every existing test fixture that builds an `ExecutionTemplate` (e.g.
   `templates.test.tsx:34-47`, schedules test fixtures) to add the new field or TS
   compilation fails. Either make the field optional in the TS type, or update all
   fixtures. Recommend updating fixtures + making it required to mirror the backend
   (which always populates it).
4. **Breadcrumb label source.** Brief allows "app name + current page" or "just
   current page." Reusing existing `nav.<key>` + `common.appName` keys avoids new
   i18n; deriving the current nav key from `usePathname()` mirrors the sidebar's
   active-route logic (`app-sidebar.tsx:84-88`). Nested routes like
   `/tasks/detail` should map to the parent nav key (`tasks`) for a stable label —
   confirm that's the desired behavior vs. showing a `detail` leaf.

## Missing decisions / questions for Codex

1. Breadcrumb content model: app-name root + page, or page only? And for nested
   routes (`/tasks/detail`) — show only the parent nav label, or a 2-level crumb
   (`Tasks / Detail`)? A 2-level crumb needs a label for `detail` (new i18n key);
   parent-only needs none.
2. Should the new `ExecutionTemplate.build_artifact_archived` TS field be optional
   or required? (Drives whether all fixtures must change.)
3. Indicator placement precision: brief says "immediately after the version value"
   (Templates) — version cell currently renders `{tpl.version ?? "-"}`
   (`templates/page.tsx:328`). Confirm the mark renders even when version is `-`
   (archived artifact could still have a version, but a dangling one may not).
4. Search input: any debounce/clear-affordance expected, or plain controlled
   input filtering in-memory? (Brief says client-side `startsWith`, trim,
   case-insensitive — a `useMemo` filter over the loaded array suffices.)

## Suggested scope / sequencing changes

1. **Sequence backend first.** Land `build_artifact_archived*` on
   `ExecutionTemplateView` (+ batch-helper change + server tests) before web work,
   so both Templates and Schedules consume one finished contract. Schedules
   indicator is then pure web (no API change).
2. **Extract one shared indicator component** (e.g.
   `components/features/archived-indicator.tsx`) that bundles
   `TooltipProvider + Tooltip + TooltipTrigger + TooltipContent` + the lucide
   warning icon + localized text, used by both pages. This resolves the test-
   provider issue once and guarantees the "consistent behavior" acceptance
   criterion. The brief already anticipates this ("add or reuse a small
   component/helper").
3. **Keep search as a local helper** (e.g. a tiny `lib/` prefix-match util) shared
   by both pages so the trim/case-insensitive/`startsWith` semantics are tested
   once and identical across pages.
4. **Treat the sidebar-logo fix and breadcrumb as one app-shell commit**, separate
   from the indicator/search commit — they touch `layout.tsx` /
   `app-sidebar.tsx`, not the pages, and are independently reviewable.

## Test coverage needed

Backend (`apps/server/tests/`):
- `template_view` / list+get+create+update responses include
  `build_artifact_archived` + `build_artifact_archived_at`, true when the bound
  artifact is archived, false/null otherwise.
- Live-property semantics: archive an artifact after a template is bound → the
  template view flips `build_artifact_archived` to true, **and the template still
  runs** (`POST /templates/{id}/run` unaffected) and stays editable for other
  fields. This directly guards the "archive does not block bound runs" invariant.
- List path does not regress to N+1 (assert via a single batched query, or at
  least cover a multi-template list with mixed archived/unarchived bindings).
- Dangling/legacy binding → `archived=false`, `archived_at=null`.

Web (`apps/web/.../__tests__/`):
- Templates: archived-bound template renders the amber mark + tooltip after
  version; unarchived does not. Prefix search filters by name (`startsWith`,
  trim, case-insensitive, empty shows all, non-prefix substring does **not**
  match).
- Schedules: schedule whose resolved template is archived shows the mark after
  the template name; derivation works from the templates list with no API change;
  search by schedule name.
- Indicator accessibility: trigger is focus-reachable and exposes the localized
  text (covers "not hover-only").
- Update/extend existing fixtures for the new `ExecutionTemplate` field.
- Add `TooltipProvider` coverage path (self-contained component renders under
  `renderWithProviders` without throwing).

Not coverable by vitest (call out for manual/visual check in the acceptance
summary): collapsed-sidebar logo clipping and breadcrumb truncation/layout — both
are CSS/visual and should be verified with `corepack pnpm --filter web build`
plus a manual look (or a Playwright/screenshot pass if the team runs one).

## Constraints honored

No upstream scrapydweb consulted or referenced. No code implemented or modified —
only this review file was created.
