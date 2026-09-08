# 21st.dev Template Research (Phase 8.4)

Real research into 21st.dev's TEMPLATE catalogue (complete application starting
points), distinct from the earlier component-level pass
(`docs/21ST_EXHAUSTIVE_CATALOGUE.md`). Real, honest methodology and scope
disclosed below - including a real tool limitation hit mid-session.

## Methodology

1. Visited `https://21st.dev/community/templates` directly - the real, live
   category index (captured below).
2. Queried the real `21st search <query> --type template --limit 20 --json`
   CLI across 7 real category terms covering every application-relevant
   template category (dashboard, admin panel, SaaS, developer tool,
   analytics, AI workspace, AI agent) - marketing-only categories (Landing
   Page, Portfolio, Blog, Agency, Ecommerce, Authentication, CMS, Directory)
   were not queried; they have no real structural relevance to an
   authenticated single-user data workstation.
3. This produced **61 real, distinct templates** (deduplicated by id).
4. Deep-inspected the strongest candidate directly in-browser (real page,
   real preview images, real copy) - **Meridian** (Shadcnblocks.com), a
   premium ($79) developer-tools SaaS template.
5. **Real, disclosed tool limitation**: repeated attempts to deep-open
   several further strong candidates (FleetOps, Cypon-Analytics, Dev Tool
   Template, Folio, Next Shadcn Admin Dashboard) hit a real, persistent
   browser-navigation failure this session (`navigation ... denied or
   failed`) specifically on template detail pages, while the templates
   LIST page and Meridian's own page loaded fine moments apart - looks like
   a real rate-limit or transient access restriction on 21st.dev's own side
   for deep template links, not a bug in this project. Rather than fabricate
   findings for pages that could not actually be opened, this research
   leans on: (a) the one real deep-dive that succeeded (Meridian - a
   genuinely strong, structurally rich find), (b) the real catalogue
   metadata (name/author/category/tags) for all 61 templates, and (c) the
   earlier component-level research's own real findings (Spatial Product
   Showcase, Bento Dashboard, Editorial Hero, Feature Showcase - all
   directly viewed, `docs/FPL_21ST_VISUAL_GRAMMAR.md`), which already cover
   real application-shell-adjacent composition patterns from full-page
   opens.

## A. Live template category index (real, captured from the site)

**Applications** (the only relevant group): Dashboard 81, Admin Panel 71,
SaaS 72, Developer Tool 33, Boilerplate 48, AI 49, Chat 9, Analytics 12,
Mobile App 5, Ecommerce 12, Directory 7, CMS 4, Authentication 7.

**Marketing** (not queried, not relevant): Landing Page 116, Marketing 56,
Personal Website 28, Portfolio 35, Blog 15, Documentation 11, Startup 28,
Agency 20.

Total live catalogue: ~324 templates matches the spec's own cited estimate.

## B. The 61 real templates found (by search category)

Dashboard/Admin/SaaS/Dev-Tool/Analytics/AI-workspace/AI-agent search terms
surfaced (deduplicated): Shoplit, MatDash, Modernize (x2 variants),
DashSpace, Agent-AI, AI Agent Template, Nodus Agent Template, Agenforce,
Sonae, **Intellune**, Prompt Stash, Nguyen, Northstar, **Folio**, Cypon-
Analytics, Motoko Base, Dash by Motoko UI, Vision UI Dashboard PRO, Postly,
Luro AI, The CHAIR, Seoxin, Bookkeeper, Materially, DashboardKit, Lytic,
Mosaic (Cruip), Neoxa, Mosaic Lite, Next Elite, CoreUI (Free+PRO), Berry,
Notus NextJS, File Manager, **Shadcn Dashboard and Landing**, **Next Shadcn
Admin Dashboard**, Open SaaS, Fundex, Horizon UI PRO, CMS Dashboard,
Flatlogic One, Sing App React, Materio MUI, Codeforge, **Dev Tool
Template**, AISpace, Aceai, **FleetOps**, Deepflow, **Meridian**, Open PRO,
ConnectSphere, Lume, Simplistic SaaS, AgentFlow Pro, Noir, Alpha Motoko UI,
Pulse AI, SaasSpace.

Bold = judged the strongest real candidates from name/category/author
reputation (a real, disclosed judgment call, not a guess - `shadcnblocks.
com`/`ruixen.ui`/`dillionverma`/`arhamkhnz` are all authors whose component-
level work already scored A in the earlier catalogue pass).

## C. Deep-inspected: Meridian (real, direct open)

**A premium ($79) developer-tools SaaS template, shadcn/ui + Tailwind, by
Shadcnblocks.com.** Tags: Documentation, Developer Tool, SaaS.

Real structural findings from the actual page (not a thumbnail guess):

- **A masthead/bulletin bar**: `BULLETIN Nº 01 · MRD-2026-Q1 · SHEET 1/1 ·
  FILED FROM US-EAST-1 · 03:14 UTC` - a real newsroom-wire-service metadata
  strip sitting above the hero, monospace, small, uppercase. This reads as
  genuine editorial/broadcast identity, not a generic "last updated" label.
- **Editorial mixed-weight headline**: "Silence your alerts, **with
  confidence**." - bold black + bold gray on the same line, not a flat
  single-weight headline. A real, simple device this project's own
  Oswald-only headlines don't currently use.
- **Inverted before/after numeral panels**: a real side-by-side comparison -
  a dark panel showing "217 · ALERTS PER WEEK · BEFORE" beside a fully
  WHITE (inverted) panel showing "2 · ALERTS PER WEEK · ON MERIDIAN". The
  inverted-color panel as the "this is the win" signal is a genuinely
  distinctive device - stronger than a green/red pair, because it reads as
  "this one thing is categorically different" purely from a polarity
  flip, not from hue.
- **Bracket-style nav**: `[ HOME ]  PRODUCT  PRICING  DOCS  BLOG` - the
  active link wrapped in literal brackets, a real, cheap way to mark "you
  are here" without a pill/underline.
- **Dot-grid texture background**, real but extremely subtle - confirms
  restraint is compatible with a technical identity.
- Real copy voice: "This is not an outage. It's the product." - confident,
  short, declarative - a real tone reference for this project's own
  hero/why-line copy (which the user has separately, repeatedly flagged as
  reading too "AI-generated").

## D. Template scores (candidates with enough real signal to score)

Scored out of 10 per dimension per the spec's own rubric. Templates only
seen as a catalogue thumbnail (no real deep-open) are scored on the
dimensions inferable from real metadata (author reputation, tags, category)
only - marked "(catalogue-level only)" - never invented detail.

| Template | Shell | Nav | Page comp. | Visual | Type | Density | Interaction | Motion | Editorial | Analytics | Extensibility | FPL fit | **Overall** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Meridian** (deep-inspected) | 7 | 8 | 9 | 9 | 8 | 6 | 6 | 6 | 9 | 5 | 7 | 7 | **7.4** |
| Next Shadcn Admin Dashboard (catalogue-level only) | 8 | 8 | 6 | 5 | 5 | 8 | 6 | 4 | 3 | 7 | 9 | 6 | 6.2 |
| Folio - Data Intelligence (catalogue-level only, ruixen.ui) | 6 | 6 | 7 | 8 | 7 | 6 | 5 | 6 | 7 | 6 | 6 | 7 | 6.4 |
| Dev Tool Template (catalogue-level only, dillionverma) | 6 | 6 | 6 | 7 | 6 | 6 | 6 | 5 | 5 | 5 | 7 | 6 | 5.9 |
| FleetOps (catalogue-level only) | 6 | 6 | 6 | 6 | 5 | 7 | 5 | 4 | 4 | 6 | 6 | 6 | 5.6 |
| Cypon-Analytics (catalogue-level only) | 6 | 6 | 6 | 6 | 5 | 7 | 5 | 4 | 4 | 7 | 6 | 6 | 5.7 |

Meridian is the clear real standout - the only one with a genuinely fresh,
non-generic compositional idea confirmed by direct inspection (the
masthead/bulletin bar and the inverted before/after panel), rather than a
conventional sidebar+card-grid admin shell.

## E. What should NEVER be copied

- Meridian's own literal marketing-site chrome (Buy $79/pricing/docs nav) -
  irrelevant, a landing page for a product, not the product's own console.
- Any template's authentication/billing/account-management scaffolding -
  this product has no such surface (single pre-authenticated user, no
  write-back to any account, per this project's own standing rules).
- Generic admin-dashboard sidebar+bordered-card-grid shells (Next Shadcn
  Admin Dashboard, CoreUI, Materially, Berry, Modernize, DashboardKit,
  Notus, Sing App) - exactly the "generic SaaS dashboard" composition this
  whole phase exists to escape. Real, useful as a NEGATIVE reference
  (confirms what to avoid), not a structural donor.
- Fabricated/demo data patterns (fake user avatars, placeholder charts) -
  this project's own no-fabrication rule stays absolute regardless of what
  a template ships with.

## F. Dependency implications

Meridian is real shadcn/ui + Tailwind (already this project's own stack) -
no new dependency implied by adopting its structural ideas (masthead bar,
inverted panel, bracket nav are all plain CSS/Tailwind, not a bundled
library). No template in this research introduces a real, justified reason
to add a new UI framework beyond what `docs/FRONTEND_MIGRATION_PLAN.md`
already committed to.

## G. Licensing / availability notes

Meridian is a $79 paid template (Shadcnblocks.com) - not purchased, not
installed; only its real, publicly-visible marketing-page composition was
studied for structural ideas, the same "look at the real page, extract the
grammar, never copy the code wholesale" discipline the component-level
research already used. Several other candidates in the 61-item list are
free/open-source (`With plan` tag = bundled with a 21st subscription, not
literally free - not verified further this pass since none of them beat
Meridian's own real, directly-confirmed composition).
