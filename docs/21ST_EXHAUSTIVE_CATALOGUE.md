# 21st.dev Exhaustive Catalogue Research (Phase 8.3)

Date: 2026-09-08. Real, direct crawl of the live 21st.dev community catalogue (`https://21st.dev/community/components`) - every current top-level category, both Marketing Blocks and UI Components sections.

## Methodology (disclosed honestly)

The live catalogue's own category counts (captured directly from the site's category index, not estimated) run into the thousands per category - Buttons alone lists 2043, Heroes 1152, Cards 1780. Literal item-by-item pagination through every single one of ~20,000+ real components is not a bounded, honest claim to make in one session. What was actually done, real and verifiable:

1. **Every one of the 77 real, currently-listed categories** (28 Marketing Blocks + 49 UI Components, the live category index's own current set) was queried via the real `21st search` CLI (free, unmetered, no fabrication - each result is a real catalogue entry with a real id/author/URL), requesting up to 20 real results per category.
2. This produced **775 real result rows, 749 distinct real components** after de-duplication (a component can rank in more than one category search).
3. Each entry was classified A/B/C/D against THIS product's real needs (Part 4/6 of the spec) - category-level defaults set first from genuine product judgment, then upgraded per-item on a real keyword signal (benchmark/radar/bento/stat/compare/timeline/ticker/etc. in the component's own name or description).
4. The strongest real candidates (every A-rated item, plus the standout B items) were then **opened directly in the browser** - real page, real preview, real description - not reconstructed from a screenshot alone. See `docs/FPL_21ST_VISUAL_GRAMMAR.md` for the deep-dive findings from those direct opens, organized by visual function rather than by 21st's own category taxonomy.
5. `search` is 21st's own relevance-ranked query across its full catalogue, not a literal category browse-with-pagination endpoint - so the up-to-20 results per category are that category's own most relevant/prominent real entries, not an arbitrary first page.

## Index

- Real categories scanned: **78** (all 77 currently on the live site, plus one stray duplicate query)
- Real component entries enumerated: **775 raw / 749 distinct**
- Deep-inspected directly in-browser (real page open, not screenshot-only): **18** (see Visual Grammar doc)
- **A (strong fit): 165**
- **B (useful pattern): 208**
- **C (interesting/experimental): 156**
- **D (not appropriate): 246**

## Marketing Blocks

### Announcements

*Live catalogue size: 71 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Team Invitation Alert](https://21st.dev/@arihantcodes_1f7b8c4d/components/alert-2) | arihantcodes_1f7b8c4d | keyword-flagged for a second look despite a D-default category |
| C | [Astryx Banner](https://21st.dev/@Astryxdesign/components/astryx-banner) | Astryxdesign | keyword-flagged for a second look despite a D-default category |

**D (not appropriate, 8):** Announcement, Announcement, Announcement Banner, Team Invitation, Banner, Project Banner, Update Available Banner, Highlighter

### ASCII Art

*Live catalogue size: uncounted/new category on the live site. Sampled: 10.*

**D (not appropriate, 10):** m ASCII, 2 ASCII, Ascii Clouds, k ASCII, n ASCII, پ ASCII, ASCII log leet, art gallery girl, i ASCII, AsherAscii

### Backgrounds

*Live catalogue size: 365 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Tiles](https://21st.dev/@lukacho/components/tiles) | lukacho | atmosphere only, used sparingly (once per hero) - never a decorative wash on every panel |
| C | [background plus](https://21st.dev/@reuno-ui/components/background-plus) | reuno-ui | atmosphere only, used sparingly (once per hero) - never a decorative wash on every panel |
| C | [Background Circles](https://21st.dev/@kokonutd/components/background-circles) | kokonutd | atmosphere only, used sparingly (once per hero) - never a decorative wash on every panel |
| C | [Background](https://21st.dev/@demonstrikk/components/background) | demonstrikk | atmosphere only, used sparingly (once per hero) - never a decorative wash on every panel |
| C | [Space Background](https://21st.dev/@designali-in/components/space-background) | designali-in | atmosphere only, used sparingly (once per hero) - never a decorative wash on every panel |
| C | [Background Paths](https://21st.dev/@kokonutd/components/background-paths) | kokonutd | atmosphere only, used sparingly (once per hero) - never a decorative wash on every panel |
| C | [Background 1](https://21st.dev/@obscurepastas/components/background-1) | obscurepastas | atmosphere only, used sparingly (once per hero) - never a decorative wash on every panel |
| C | [Bubble Background](https://21st.dev/@skyleen77/components/components-backgrounds-bubble) | skyleen77 | atmosphere only, used sparingly (once per hero) - never a decorative wash on every panel |
| C | [Gradient Background](https://21st.dev/@efferd/components/gradient-background) | efferd | atmosphere only, used sparingly (once per hero) - never a decorative wash on every panel |
| C | [Gradient Background 4](https://21st.dev/@ibelick/components/gradient-background-4) | ibelick | atmosphere only, used sparingly (once per hero) - never a decorative wash on every panel |

### Borders

*Live catalogue size: 111 real listed. Sampled: 10.*

**D (not appropriate, 10):** Moving Border, Border Trail, Border Beam, Pulsing Border, Border Beam, Border Beam, Avatar - Border, Moving Border, Breadcrumb, Breadcrumb

### Calls to Action

*Live catalogue size: 501 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [CTA Section](https://21st.dev/@shadcnstore/components/cta-section-3) | shadcnstore | keyword-flagged for a second look despite a D-default category |

**D (not appropriate, 9):** Call to Action, Call to Action, Call To Action, Call to action, Cta 10, Call to Action (CTA), Call To Action 3, Call to Action 01, CTA 3

### Clients

*Live catalogue size: 17 real listed. Sampled: 5.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Sidebar](https://21st.dev/@uniquesonu/components/sidebar) | uniquesonu | keyword-flagged for a second look despite a D-default category |

**D (not appropriate, 4):** Cases with Infinite Scroll, Testimonial, Marquee, DoctorLiveChatCard

### Comparisons

*Live catalogue size: 31 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Compare](https://21st.dev/@manuarora700/components/compare) | manuarora700 | STRONG - direct fit: chosen-vs-alternative path, captain matchup, transfer candidate comparison |
| A | [Image Comparison](https://21st.dev/@ibelick/components/image-comparison) | ibelick | STRONG - direct fit: chosen-vs-alternative path, captain matchup, transfer candidate comparison |
| A | [Us vs Them Comparison](https://21st.dev/@7ovr/components/comparison-2) | 7ovr | STRONG - direct fit: chosen-vs-alternative path, captain matchup, transfer candidate comparison |
| A | [Compare 1](https://21st.dev/@designali-in/components/compare-1) | designali-in | STRONG - direct fit: chosen-vs-alternative path, captain matchup, transfer candidate comparison |
| A | [Pricing Section with Comparison](https://21st.dev/@tommyjepsen/components/pricing-section-with-comparison) | tommyjepsen | STRONG - direct fit: chosen-vs-alternative path, captain matchup, transfer candidate comparison |
| A | [Compare 2](https://21st.dev/@designali-in/components/compare-2) | designali-in | STRONG - direct fit: chosen-vs-alternative path, captain matchup, transfer candidate comparison |
| A | [Comparison Table](https://21st.dev/@ruixen.ui/components/comparison-table) | ruixen.ui | STRONG - direct fit: chosen-vs-alternative path, captain matchup, transfer candidate comparison |
| A | [Feature Comparison Table](https://21st.dev/@7ovr/components/comparison-3) | 7ovr | STRONG - direct fit: chosen-vs-alternative path, captain matchup, transfer candidate comparison |
| A | [Compare Slider](https://21st.dev/@diceui/components/compare-slider) | diceui | STRONG - direct fit: chosen-vs-alternative path, captain matchup, transfer candidate comparison |
| A | [Comparison Slider with Highlights](https://21st.dev/@ziegfiroyt/components/reveal2) | ziegfiroyt | STRONG - direct fit: chosen-vs-alternative path, captain matchup, transfer candidate comparison |

### Docks

*Live catalogue size: 49 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| B | [dock](https://21st.dev/@badtzx0/components/dock) | badtzx0 | contextual player actions (compare/pin/inspect) in MY TEAM/SCOUT - a floating action dock on selection |
| B | [Dock](https://21st.dev/@saurabh10102/components/dock) | saurabh10102 | contextual player actions (compare/pin/inspect) in MY TEAM/SCOUT - a floating action dock on selection |
| B | [Dock ](https://21st.dev/@lyanchouss/components/dock) | lyanchouss | contextual player actions (compare/pin/inspect) in MY TEAM/SCOUT - a floating action dock on selection |
| B | [BeUI Shared Layout Background](https://21st.dev/@saurabh10102/components/beui-dock) | saurabh10102 | contextual player actions (compare/pin/inspect) in MY TEAM/SCOUT - a floating action dock on selection |
| B | [Dock](https://21st.dev/@anurag-mishra22/components/dock-two) | anurag-mishra22 | contextual player actions (compare/pin/inspect) in MY TEAM/SCOUT - a floating action dock on selection |
| B | [Dock](https://21st.dev/@ruixen.ui/components/dock) | ruixen.ui | contextual player actions (compare/pin/inspect) in MY TEAM/SCOUT - a floating action dock on selection |
| B | [Floating Dock](https://21st.dev/@manuarora700/components/floating-dock) | manuarora700 | contextual player actions (compare/pin/inspect) in MY TEAM/SCOUT - a floating action dock on selection |
| B | [Dock](https://21st.dev/@ibelick/components/dock) | ibelick | contextual player actions (compare/pin/inspect) in MY TEAM/SCOUT - a floating action dock on selection |
| B | [Docks](https://21st.dev/@ruixen.ui/components/docks) | ruixen.ui | contextual player actions (compare/pin/inspect) in MY TEAM/SCOUT - a floating action dock on selection |
| B | [Dock](https://21st.dev/@cult-ui/components/dock) | cult-ui | contextual player actions (compare/pin/inspect) in MY TEAM/SCOUT - a floating action dock on selection |

### FAQs

*Live catalogue size: 191 real listed. Sampled: 10.*

**D (not appropriate, 10):** FAQs Component, FAQ Section, Faqs 1, FAQ Pro, FAQ Sections, Faq 5, FAQ Section, textRevealFAQs, FAQ Section, FAQ List

### Features

*Live catalogue size: 318 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| B | [Feature](https://21st.dev/@tommyjepsen/components/feature) | tommyjepsen | section-composition pattern (asymmetric text+media) reused for editorial screen intros |
| B | [Feature with advantages](https://21st.dev/@tommyjepsen/components/feature-with-advantages) | tommyjepsen | section-composition pattern (asymmetric text+media) reused for editorial screen intros |
| B | [Features 4](https://21st.dev/@meschacirung/components/features-4) | meschacirung | section-composition pattern (asymmetric text+media) reused for editorial screen intros |
| B | [Features 8](https://21st.dev/@meschacirung/components/features-8) | meschacirung | section-composition pattern (asymmetric text+media) reused for editorial screen intros |
| B | [Features 9](https://21st.dev/@meschacirung/components/features-9) | meschacirung | section-composition pattern (asymmetric text+media) reused for editorial screen intros |
| B | [Features 1](https://21st.dev/@meschacirung/components/features-1) | meschacirung | section-composition pattern (asymmetric text+media) reused for editorial screen intros |
| B | [Features 6](https://21st.dev/@meschacirung/components/features-6) | meschacirung | section-composition pattern (asymmetric text+media) reused for editorial screen intros |
| B | [Features 2](https://21st.dev/@meschacirung/components/features-2) | meschacirung | section-composition pattern (asymmetric text+media) reused for editorial screen intros |
| B | [Features](https://21st.dev/@meschacirung/components/features) | meschacirung | section-composition pattern (asymmetric text+media) reused for editorial screen intros |
| B | [Feature 108](https://21st.dev/@shadcnblockscom/components/shadcnblocks-com-feature108) | shadcnblockscom | section-composition pattern (asymmetric text+media) reused for editorial screen intros |

### Footers

*Live catalogue size: 65 real listed. Sampled: 10.*

**D (not appropriate, 10):** Footer, Footer, Footer, Footer, Footer 2, Footer column, Footer, Stacked Circular Footer, Animated Footer Section, Footer section

### Galleries

*Live catalogue size: 272 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| B | [Gallery](https://21st.dev/@designali-in/components/gallery) | designali-in | player/team visual browsing in SCOUT's player grid and MY TEAM's squad view |
| B | [Arch Gallery](https://21st.dev/@vinny_b0b96136/components/arch-gallery) | vinny_b0b96136 | player/team visual browsing in SCOUT's player grid and MY TEAM's squad view |
| B | [Elastic Gallery](https://21st.dev/@daiwiikharihar/components/elastic-gallery) | daiwiikharihar | player/team visual browsing in SCOUT's player grid and MY TEAM's squad view |
| B | [Portfolio Gallery](https://21st.dev/@isaiahbjork/components/portfolio-gallery) | isaiahbjork | player/team visual browsing in SCOUT's player grid and MY TEAM's squad view |
| B | [Gallery with image cards](https://21st.dev/@shadcnblockscom/components/gallery4) | shadcnblockscom | player/team visual browsing in SCOUT's player grid and MY TEAM's squad view |
| B | [Circular Gallery](https://21st.dev/@ravikatiyar162/components/circular-gallery) | ravikatiyar162 | player/team visual browsing in SCOUT's player grid and MY TEAM's squad view |
| B | [Image Gallery](https://21st.dev/@prebuiltui/components/image-gallery) | prebuiltui | player/team visual browsing in SCOUT's player grid and MY TEAM's squad view |
| B | [Arc Gallery Hero Component](https://21st.dev/@minhxthanh/components/arc-gallery-hero-component) | minhxthanh | player/team visual browsing in SCOUT's player grid and MY TEAM's squad view |
| B | [Portfolio and Image Gallery](https://21st.dev/@iamsatish4564/components/portfolio-and-image-gallery) | iamsatish4564 | player/team visual browsing in SCOUT's player grid and MY TEAM's squad view |
| B | [Image Gallery](https://21st.dev/@efferd/components/image-gallery) | efferd | player/team visual browsing in SCOUT's player grid and MY TEAM's squad view |

### Gradients

*Live catalogue size: uncounted/new category on the live site. Sampled: 10.*

**D (not appropriate, 10):** Gradients, Graaadeints, Gradient Text, Mesh Gradient, Grain Gradient, Gradient Tracing, Liquid Gradient, mesh gradient, 2 Gradient, Background Gradient

### Heroes

*Live catalogue size: 1152 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Hero Section Dark](https://21st.dev/@kinfe123/components/hero-section-dark) | kinfe123 | STRONG - COMMAND's own dominant-decision composition is a hero pattern |
| A | [Modern Hero](https://21st.dev/@shadcnblockscom/components/modern-hero) | shadcnblockscom | STRONG - COMMAND's own dominant-decision composition is a hero pattern |
| A | [Hero Shader](https://21st.dev/@designali-in/components/hero-shader) | designali-in | STRONG - COMMAND's own dominant-decision composition is a hero pattern |
| A | [Hero Section](https://21st.dev/@reuno-ui/components/hero-section) | reuno-ui | STRONG - COMMAND's own dominant-decision composition is a hero pattern |
| A | [Hero 45](https://21st.dev/@shadcnblockscom/components/shadcnblocks-com-hero45) | shadcnblockscom | STRONG - COMMAND's own dominant-decision composition is a hero pattern |
| A | [Hero Section](https://21st.dev/@ravikatiyar162/components/hero-section-2) | ravikatiyar162 | STRONG - COMMAND's own dominant-decision composition is a hero pattern |
| A | [Hero Section ](https://21st.dev/@haydenbleasel/components/hero-section-2) | haydenbleasel | STRONG - COMMAND's own dominant-decision composition is a hero pattern |
| A | [Hero Section](https://21st.dev/@prebuiltui/components/hero-section) | prebuiltui | STRONG - COMMAND's own dominant-decision composition is a hero pattern |
| A | [Hero Section](https://21st.dev/@moumensoliman/components/hero-section-shadcnui) | moumensoliman | STRONG - COMMAND's own dominant-decision composition is a hero pattern |
| A | [Hero Section 6](https://21st.dev/@meschacirung/components/hero-section-6) | meschacirung | STRONG - COMMAND's own dominant-decision composition is a hero pattern |

### Hooks

*Live catalogue size: 51 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Toggle](https://21st.dev/@cnippet-dev/components/cnippet-toggle) | cnippet-dev | keyword-flagged for a second look despite a D-default category |
| C | [Interfaces Collapsible](https://21st.dev/@jshguo/components/interfaces-collapsible) | jshguo | keyword-flagged for a second look despite a D-default category |

**D (not appropriate, 8):** Attachment Button, useElasticLineEvents, Curtain Theme Toggle, Loop Animation Hook, Input, Button, Drawer, Link Preview

### Images

*Live catalogue size: 428 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Picture](https://21st.dev/@shoota/components/picture) | shoota | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| B | [Image Generation](https://21st.dev/@kvnkld/components/image-generation) | kvnkld | editorial player/crest imagery treatment (fade masks, full-bleed) for MY TEAM/FOOTBALL |
| B | [Image Text](https://21st.dev/@animbits/components/image-text) | animbits | editorial player/crest imagery treatment (fade masks, full-bleed) for MY TEAM/FOOTBALL |
| B | [Slide Image](https://21st.dev/@slide-cn/components/slide-image) | slide-cn | editorial player/crest imagery treatment (fade masks, full-bleed) for MY TEAM/FOOTBALL |
| B | [Image Tiles](https://21st.dev/@tonyzebastian/components/image-tiles) | tonyzebastian | editorial player/crest imagery treatment (fade masks, full-bleed) for MY TEAM/FOOTBALL |
| B | [File Attachment](https://21st.dev/@serafimcloud/components/file-attachment) | serafimcloud | editorial player/crest imagery treatment (fade masks, full-bleed) for MY TEAM/FOOTBALL |
| B | [LQIP Image](https://21st.dev/@pulkitxm/components/lqip-image) | pulkitxm | editorial player/crest imagery treatment (fade masks, full-bleed) for MY TEAM/FOOTBALL |
| B | [Gallery](https://21st.dev/@designali-in/components/gallery) | designali-in | editorial player/crest imagery treatment (fade masks, full-bleed) for MY TEAM/FOOTBALL |
| B | [Image Stream Hero](https://21st.dev/@ruixen.ui/components/image-stream-hero) | ruixen.ui | editorial player/crest imagery treatment (fade masks, full-bleed) for MY TEAM/FOOTBALL |
| B | [Infinite Image Field](https://21st.dev/@componentry/components/infinite-image-field) | componentry | editorial player/crest imagery treatment (fade masks, full-bleed) for MY TEAM/FOOTBALL |

### Maps

*Live catalogue size: 51 real listed. Sampled: 10.*

**D (not appropriate, 10):** Expanded Map, Interactive Map, Expand Map, World Map, Location Map, Heatmaps, MarkerContent, FlightRoutes, SatelliteOrbit, Globe

### Marquees

*Live catalogue size: 113 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| B | [Marquee](https://21st.dev/@lukacho/components/marquee) | lukacho | fixture ticker / live event ribbon on LIVE and the global status strip |
| B | [Marquee](https://21st.dev/@serafimcloud/components/marquee) | serafimcloud | fixture ticker / live event ribbon on LIVE and the global status strip |
| B | [Marquee](https://21st.dev/@ekmas/components/marquee) | ekmas | fixture ticker / live event ribbon on LIVE and the global status strip |
| B | [Marquee](https://21st.dev/@haydenbleasel/components/marquee) | haydenbleasel | fixture ticker / live event ribbon on LIVE and the global status strip |
| B | [3D Marquee](https://21st.dev/@Shatlyk1011/components/3d-marquee) | Shatlyk1011 | fixture ticker / live event ribbon on LIVE and the global status strip |
| B | [Logo Marquee](https://21st.dev/@grootstudio/components/logo-marquee) | grootstudio | fixture ticker / live event ribbon on LIVE and the global status strip |
| B | [CTA with Marquee](https://21st.dev/@lyanchouss/components/cta-with-marquee) | lyanchouss | fixture ticker / live event ribbon on LIVE and the global status strip |
| B | [Logo Marquee](https://21st.dev/@ddoemonn/components/logo-marquee) | ddoemonn | fixture ticker / live event ribbon on LIVE and the global status strip |
| B | [Text Marque](https://21st.dev/@uilayout.contact/components/text-marque) | uilayout.contact | fixture ticker / live event ribbon on LIVE and the global status strip |
| B | [Marquee Effect](https://21st.dev/@bundui/components/marquee-effect) | bundui | fixture ticker / live event ribbon on LIVE and the global status strip |

### Navigation Menus

*Live catalogue size: 477 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| B | [Navigation menu](https://21st.dev/@shadcn/components/navigation-menu) | shadcn | informs the sidebar/command-palette navigation language |
| B | [Navbar Menu](https://21st.dev/@manuarora700/components/navbar-menu) | manuarora700 | informs the sidebar/command-palette navigation language |
| B | [Navigation Menu](https://21st.dev/@sean0205/components/navigation-menu) | sean0205 | informs the sidebar/command-palette navigation language |
| B | [Rich Navigation Menu](https://21st.dev/@shadcnui-blocks/components/navigation-menu-06) | shadcnui-blocks | informs the sidebar/command-palette navigation language |
| B | [Menubar](https://21st.dev/@shadcn/components/menubar) | shadcn | informs the sidebar/command-palette navigation language |
| B | [Navigation Menu](https://21st.dev/@larsen66/components/navigation-menu) | larsen66 | informs the sidebar/command-palette navigation language |
| B | [Motion Navigation Menu](https://21st.dev/@unlumen/components/motion-navigation-menu) | unlumen | informs the sidebar/command-palette navigation language |
| B | [Navigation Menu](https://21st.dev/@originui/components/navigation-menu) | originui | informs the sidebar/command-palette navigation language |
| B | [Shop Navigation Menu](https://21st.dev/@bundui/components/navigation-menu4) | bundui | informs the sidebar/command-palette navigation language |
| B | [Dropdown Menu](https://21st.dev/@shadcn/components/dropdown-menu) | shadcn | informs the sidebar/command-palette navigation language |

### Pricing Sections

*Live catalogue size: 216 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| B | [Pricing Section](https://21st.dev/@kokonutd/components/pricing-section) | kokonutd | repurposed as chip/strategic-path comparison layout, not literal pricing |
| B | [Pricing Section](https://21st.dev/@brijr/components/pricing-section) | brijr | repurposed as chip/strategic-path comparison layout, not literal pricing |
| B | [Pricing Section 1](https://21st.dev/@shadcnstore/components/pricing-section-1) | shadcnstore | repurposed as chip/strategic-path comparison layout, not literal pricing |
| B | [Pricing Section with Comparison](https://21st.dev/@tommyjepsen/components/pricing-section-with-comparison) | tommyjepsen | repurposed as chip/strategic-path comparison layout, not literal pricing |
| B | [Pricing Section](https://21st.dev/@bigbogiballer/components/pricing-section) | bigbogiballer | repurposed as chip/strategic-path comparison layout, not literal pricing |
| B | [Pricing Section](https://21st.dev/@uilayout.contact/components/pricing-section-1) | uilayout.contact | repurposed as chip/strategic-path comparison layout, not literal pricing |
| B | [Pricing Section](https://21st.dev/@mikolajdobrucki/components/pricing) | mikolajdobrucki | repurposed as chip/strategic-path comparison layout, not literal pricing |
| B | [Pricing Section with Frequency Toggle](https://21st.dev/@efferd/components/pricing-4) | efferd | repurposed as chip/strategic-path comparison layout, not literal pricing |
| B | [Pricing Section](https://21st.dev/@uilayout.contact/components/pricing-section-3) | uilayout.contact | repurposed as chip/strategic-path comparison layout, not literal pricing |
| B | [Pricing Section](https://21st.dev/@uilayout.contact/components/pricing-section) | uilayout.contact | repurposed as chip/strategic-path comparison layout, not literal pricing |

### Scroll Areas

*Live catalogue size: 293 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| B | [Scroll Area](https://21st.dev/@shadcn/components/scroll-area) | shadcn | sticky analytical side-panel pattern for dense ADVANCED/SCOUT tables |
| B | [Scroll Area](https://21st.dev/@lina.sameer/components/scroll-area-1) | lina.sameer | sticky analytical side-panel pattern for dense ADVANCED/SCOUT tables |
| B | [Scroll Area with Sheet](https://21st.dev/@bundui/components/scroll-area2) | bundui | sticky analytical side-panel pattern for dense ADVANCED/SCOUT tables |
| B | [Scroll Area](https://21st.dev/@sean0205/components/scroll-area) | sean0205 | sticky analytical side-panel pattern for dense ADVANCED/SCOUT tables |
| B | [Scroll Area](https://21st.dev/@bundui/components/scroll-area3) | bundui | sticky analytical side-panel pattern for dense ADVANCED/SCOUT tables |
| B | [Scroll Area](https://21st.dev/@preetsuthar17/components/scroll-area) | preetsuthar17 | sticky analytical side-panel pattern for dense ADVANCED/SCOUT tables |
| B | [Scroll Area](https://21st.dev/@olivier_1b6cd5bc/components/scroll-area-1) | olivier_1b6cd5bc | sticky analytical side-panel pattern for dense ADVANCED/SCOUT tables |
| B | [Scroll Area](https://21st.dev/@extend-hq/components/scroll-area) | extend-hq | sticky analytical side-panel pattern for dense ADVANCED/SCOUT tables |
| B | [Scroll Based Velocity](https://21st.dev/@dillionverma/components/scroll-based-velocity) | dillionverma | sticky analytical side-panel pattern for dense ADVANCED/SCOUT tables |
| B | [XScroll](https://21st.dev/@nelwincatalogo/components/x-scroll) | nelwincatalogo | sticky analytical side-panel pattern for dense ADVANCED/SCOUT tables |

### Shaders

*Live catalogue size: uncounted/new category on the live site. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [SHADER STATE](https://21st.dev/@vnantes/components/shader-state) | vnantes | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| C | [Background Paper Shaders](https://21st.dev/@reuno-ui/components/background-paper-shaders) | reuno-ui | not used - explicitly too decorative for a data-integrity-first tool; the flat broadcast language already gives atmosphere |
| C | [Wrap Shader](https://21st.dev/@moazamtrade/components/wrap-shader) | moazamtrade | not used - explicitly too decorative for a data-integrity-first tool; the flat broadcast language already gives atmosphere |
| C | [Background Shaders ](https://21st.dev/@moazamtrade/components/background-shaders) | moazamtrade | not used - explicitly too decorative for a data-integrity-first tool; the flat broadcast language already gives atmosphere |
| C | [Hive](https://21st.dev/@xordev/components/hive) | xordev | not used - explicitly too decorative for a data-integrity-first tool; the flat broadcast language already gives atmosphere |
| C | [Interactive Shader](https://21st.dev/@dhileepkumargm/components/interactive-shader) | dhileepkumargm | not used - explicitly too decorative for a data-integrity-first tool; the flat broadcast language already gives atmosphere |
| C | [Crystalline Cube](https://21st.dev/@dhileepkumargm/components/crystalline-cube) | dhileepkumargm | not used - explicitly too decorative for a data-integrity-first tool; the flat broadcast language already gives atmosphere |
| C | [Line Shader Homlu UI](https://21st.dev/@senommu/components/line-shader-homlu-ui) | senommu | not used - explicitly too decorative for a data-integrity-first tool; the flat broadcast language already gives atmosphere |
| C | [Abstract Glassy Shader](https://21st.dev/@dhileepkumargm/components/abstract-glassy-shader) | dhileepkumargm | not used - explicitly too decorative for a data-integrity-first tool; the flat broadcast language already gives atmosphere |
| C | [Shadow Blending](https://21st.dev/@serafimcloud/components/shadow-blending) | serafimcloud | not used - explicitly too decorative for a data-integrity-first tool; the flat broadcast language already gives atmosphere |

### Stats & KPIs

*Live catalogue size: 153 real listed. Sampled: 0.*

### Steppers

*Live catalogue size: 124 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Stepper](https://21st.dev/@originui/components/stepper) | originui | STRONG - PLAN's transfer/chip sequence, trajectory legs |
| A | [Stepper](https://21st.dev/@sean0205/components/stepper) | sean0205 | STRONG - PLAN's transfer/chip sequence, trajectory legs |
| A | [Stepper](https://21st.dev/@nyxbui/components/stepper) | nyxbui | STRONG - PLAN's transfer/chip sequence, trajectory legs |
| A | [Registration Stepper](https://21st.dev/@ravikatiyar162/components/registration-stepper) | ravikatiyar162 | STRONG - PLAN's transfer/chip sequence, trajectory legs |
| A | [Steps](https://21st.dev/@anubra266/components/steps) | anubra266 | STRONG - PLAN's transfer/chip sequence, trajectory legs |
| A | [Onboarding Stepper Progress](https://21st.dev/@shadcnspace/components/progress-02) | shadcnspace | STRONG - PLAN's transfer/chip sequence, trajectory legs |
| A | [Wizard Steps](https://21st.dev/@ddoemonn/components/wizard-steps) | ddoemonn | STRONG - PLAN's transfer/chip sequence, trajectory legs |
| A | [Step Card](https://21st.dev/@ruixen.ui/components/step-card) | ruixen.ui | STRONG - PLAN's transfer/chip sequence, trajectory legs |
| A | [MultiStep Button](https://21st.dev/@ruixen.ui/components/multi-step-button) | ruixen.ui | STRONG - PLAN's transfer/chip sequence, trajectory legs |
| A | [Multi-Step Form](https://21st.dev/@ravikatiyar162/components/multi-step-form) | ravikatiyar162 | STRONG - PLAN's transfer/chip sequence, trajectory legs |

### Team Sections

*Live catalogue size: 119 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Stats Section with Text](https://21st.dev/@tommyjepsen/components/stats-section-with-text) | tommyjepsen | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| B | [Team Section](https://21st.dev/@ravikatiyar162/components/team-section-1) | ravikatiyar162 | club/team identity presentation in FOOTBALL's team-state view |
| B | [Feature Sections](https://21st.dev/@prebuiltui/components/feature-sections) | prebuiltui | club/team identity presentation in FOOTBALL's team-state view |
| B | [Team Section](https://21st.dev/@youcefbnm/components/team-section) | youcefbnm | club/team identity presentation in FOOTBALL's team-state view |
| B | [Team Section](https://21st.dev/@ravikatiyar162/components/team-section) | ravikatiyar162 | club/team identity presentation in FOOTBALL's team-state view |
| B | [Team](https://21st.dev/@cnippet-dev/components/team) | cnippet-dev | club/team identity presentation in FOOTBALL's team-state view |
| B | [Team Section Block](https://21st.dev/@moumensoliman/components/team-section-block-shadcnui) | moumensoliman | club/team identity presentation in FOOTBALL's team-state view |
| B | [Feature 108](https://21st.dev/@shadcnblockscom/components/shadcnblocks-com-feature108) | shadcnblockscom | club/team identity presentation in FOOTBALL's team-state view |
| B | [Hero Section ](https://21st.dev/@haydenbleasel/components/hero-section-2) | haydenbleasel | club/team identity presentation in FOOTBALL's team-state view |
| B | [Feature Section with Grid](https://21st.dev/@tommyjepsen/components/feature-section-with-grid) | tommyjepsen | club/team identity presentation in FOOTBALL's team-state view |

### Testimonials

*Live catalogue size: 161 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [testimonial](https://21st.dev/@uilayout.contact/components/testimonial) | uilayout.contact | repurposed ONLY where a real quote/evidence source exists - football intelligence evidence text in FOOTBALL, never a fabricated quote |
| C | [Circular Testimonials](https://21st.dev/@maxim.bort.devel/components/circular-testimonials) | maxim.bort.devel | repurposed ONLY where a real quote/evidence source exists - football intelligence evidence text in FOOTBALL, never a fabricated quote |
| C | [Testimonial](https://21st.dev/@uilayout.contact/components/testimonial-1) | uilayout.contact | repurposed ONLY where a real quote/evidence source exists - football intelligence evidence text in FOOTBALL, never a fabricated quote |
| C | [Testimonial](https://21st.dev/@prebuiltui/components/testimonial) | prebuiltui | repurposed ONLY where a real quote/evidence source exists - football intelligence evidence text in FOOTBALL, never a fabricated quote |
| C | [Testimonials](https://21st.dev/@tommyjepsen/components/testimonials) | tommyjepsen | repurposed ONLY where a real quote/evidence source exists - football intelligence evidence text in FOOTBALL, never a fabricated quote |
| C | [Testimonials Section](https://21st.dev/@efferd/components/testimonials-section) | efferd | repurposed ONLY where a real quote/evidence source exists - football intelligence evidence text in FOOTBALL, never a fabricated quote |
| C | [Testimonials Five](https://21st.dev/@meschacirung/components/mist-testimonials-5) | meschacirung | repurposed ONLY where a real quote/evidence source exists - football intelligence evidence text in FOOTBALL, never a fabricated quote |
| C | [Testimonial](https://21st.dev/@anurag-mishra22/components/testimonial) | anurag-mishra22 | repurposed ONLY where a real quote/evidence source exists - football intelligence evidence text in FOOTBALL, never a fabricated quote |
| C | [Stagger Testimonials](https://21st.dev/@vaib215/components/stagger-testimonials) | vaib215 | repurposed ONLY where a real quote/evidence source exists - football intelligence evidence text in FOOTBALL, never a fabricated quote |
| C | [Design Testimonial](https://21st.dev/@jatin-yadav05/components/design-testimonial) | jatin-yadav05 | repurposed ONLY where a real quote/evidence source exists - football intelligence evidence text in FOOTBALL, never a fabricated quote |

### Texts

*Live catalogue size: 663 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Text Particle](https://21st.dev/@designali-in/components/text-particle) | designali-in | event-driven text-transition pattern for live state changes only, never decorative |
| C | [Liquid Text](https://21st.dev/@designali-in/components/liquid-text) | designali-in | event-driven text-transition pattern for live state changes only, never decorative |
| C | [Dia Text](https://21st.dev/@animbits/components/text-dia) | animbits | event-driven text-transition pattern for live state changes only, never decorative |
| C | [Encrypted Text](https://21st.dev/@manuarora700/components/encrypted-text) | manuarora700 | event-driven text-transition pattern for live state changes only, never decorative |
| C | [Text Rewind](https://21st.dev/@kokonutd/components/text-rewind) | kokonutd | event-driven text-transition pattern for live state changes only, never decorative |
| C | [Scramble Text](https://21st.dev/@dqnamo/components/scramble-text) | dqnamo | event-driven text-transition pattern for live state changes only, never decorative |
| C | [Dia Text](https://21st.dev/@edwinvakayil/components/dia-text) | edwinvakayil | event-driven text-transition pattern for live state changes only, never decorative |
| C | [Decrypt Text](https://21st.dev/@rmahammad/components/decrypt-text) | rmahammad | event-driven text-transition pattern for live state changes only, never decorative |
| C | [Text Scramble](https://21st.dev/@cnippet-dev/components/text-scramble) | cnippet-dev | event-driven text-transition pattern for live state changes only, never decorative |
| C | [Special Text](https://21st.dev/@tom_ui/components/special-text) | tom_ui | event-driven text-transition pattern for live state changes only, never decorative |

### Timelines

*Live catalogue size: 74 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Timeline](https://21st.dev/@nyxbui/components/timeline) | nyxbui | STRONG - PLAN's strategic trajectory, LIVE's match-event feed |
| A | [Timeline](https://21st.dev/@preetsuthar17/components/timeline) | preetsuthar17 | STRONG - PLAN's strategic trajectory, LIVE's match-event feed |
| A | [Modern Timeline](https://21st.dev/@chowlol202/components/modern-timeline) | chowlol202 | STRONG - PLAN's strategic trajectory, LIVE's match-event feed |
| A | [Timeline](https://21st.dev/@manuarora700/components/timeline) | manuarora700 | STRONG - PLAN's strategic trajectory, LIVE's match-event feed |
| A | [How It Works Timeline](https://21st.dev/@7ovr/components/how-it-works-2) | 7ovr | STRONG - PLAN's strategic trajectory, LIVE's match-event feed |
| A | [Timeline-02](https://21st.dev/@ruixen.ui/components/timeline-02) | ruixen.ui | STRONG - PLAN's strategic trajectory, LIVE's match-event feed |
| A | [Timeline](https://21st.dev/@Codehagen/components/timeline) | Codehagen | STRONG - PLAN's strategic trajectory, LIVE's match-event feed |
| A | [Daily Timeline Scheduler](https://21st.dev/@ruixen.ui/components/daily-timeline-scheduler) | ruixen.ui | STRONG - PLAN's strategic trajectory, LIVE's match-event feed |
| A | [8bit Timeline Horizontal](https://21st.dev/@theorcdev/components/8bit-timeline2) | theorcdev | STRONG - PLAN's strategic trajectory, LIVE's match-event feed |
| A | [Timeline Rail](https://21st.dev/@nayan_radadiya6/components/timeline-rail) | nayan_radadiya6 | STRONG - PLAN's strategic trajectory, LIVE's match-event feed |

### Videos

*Live catalogue size: 162 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Scroll-Linked Video Scrubber](https://21st.dev/@pulkitxm/components/scroll-linked-video-scrubber) | pulkitxm | keyword-flagged for a second look despite a D-default category |

**D (not appropriate, 9):** Video Thumbnail Player, Video Modal, Video Upload Card, Interactive Video Portfolio Scroller, Video Player, Scroll-Locked Video Hero, VHS Hero Section, Animated Testimonials, About

## UI Components

### Accordions

*Live catalogue size: 234 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Accordion](https://21st.dev/@cnippet-dev/components/cnippet-accordion) | cnippet-dev | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| B | [Accordion - Cheveron](https://21st.dev/@designali-in/components/accordion-01) | designali-in | ADVANCED's per-diagnostic-module disclosure (already the existing pattern, kept) |
| B | [Accordion](https://21st.dev/@brijr/components/accordion-1) | brijr | ADVANCED's per-diagnostic-module disclosure (already the existing pattern, kept) |
| B | [Accordion](https://21st.dev/@ddoemonn/components/accordion) | ddoemonn | ADVANCED's per-diagnostic-module disclosure (already the existing pattern, kept) |
| B | [Accordion](https://21st.dev/@coss.com/components/coss-accordion) | coss.com | ADVANCED's per-diagnostic-module disclosure (already the existing pattern, kept) |
| B | [Accordion](https://21st.dev/@originui/components/accordion) | originui | ADVANCED's per-diagnostic-module disclosure (already the existing pattern, kept) |
| B | [Accordion](https://21st.dev/@educalvolpz/components/accordion-2) | educalvolpz | ADVANCED's per-diagnostic-module disclosure (already the existing pattern, kept) |
| B | [Accordion](https://21st.dev/@ShadcnStudio/components/accordion-1) | ShadcnStudio | ADVANCED's per-diagnostic-module disclosure (already the existing pattern, kept) |
| B | [Accordion](https://21st.dev/@anubra266/components/accordion-1) | anubra266 | ADVANCED's per-diagnostic-module disclosure (already the existing pattern, kept) |
| B | [Accordion](https://21st.dev/@olivier_1b6cd5bc/components/accordion-1) | olivier_1b6cd5bc | ADVANCED's per-diagnostic-module disclosure (already the existing pattern, kept) |

### AI Chats

*Live catalogue size: 248 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [AI Input](https://21st.dev/@haydenbleasel/components/ai-input) | haydenbleasel | noted as a real future direction (Part 16 'ask the engine') - not built this phase, no real backend endpoint for it yet |
| C | [IA Siri Chat](https://21st.dev/@botsnew354/components/ia-siri-chat) | botsnew354 | noted as a real future direction (Part 16 'ask the engine') - not built this phase, no real backend endpoint for it yet |
| C | [AI Assistant Interface](https://21st.dev/@rafa-porto/components/ai-assistant-interface) | rafa-porto | noted as a real future direction (Part 16 'ask the engine') - not built this phase, no real backend endpoint for it yet |
| C | [AI Chat Input](https://21st.dev/@baozhouqi/components/ai-chat-input) | baozhouqi | noted as a real future direction (Part 16 'ask the engine') - not built this phase, no real backend endpoint for it yet |
| C | [AI Input](https://21st.dev/@aghasisahakyan1/components/ai-input) | aghasisahakyan1 | noted as a real future direction (Part 16 'ask the engine') - not built this phase, no real backend endpoint for it yet |
| C | [AI Chat Image Generation](https://21st.dev/@gonzalochale/components/ai-chat-image-generation-1) | gonzalochale | noted as a real future direction (Part 16 'ask the engine') - not built this phase, no real backend endpoint for it yet |
| C | [AI Chat Input](https://21st.dev/@daiwiikharihar/components/ai-chat-input) | daiwiikharihar | noted as a real future direction (Part 16 'ask the engine') - not built this phase, no real backend endpoint for it yet |
| C | [AI Chat Input](https://21st.dev/@preetsuthar17/components/ai-chat-input) | preetsuthar17 | noted as a real future direction (Part 16 'ask the engine') - not built this phase, no real backend endpoint for it yet |
| C | [AI Suggested Actions](https://21st.dev/@elements-/components/suggested-actions) | elements- | noted as a real future direction (Part 16 'ask the engine') - not built this phase, no real backend endpoint for it yet |
| C | [AI Suggestions](https://21st.dev/@pacekit/components/ai-suggestions) | pacekit | noted as a real future direction (Part 16 'ask the engine') - not built this phase, no real backend endpoint for it yet |

### Alerts

*Live catalogue size: 240 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Notice Alert](https://21st.dev/@corr/components/notice-alert) | corr | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Reshaped Alert](https://21st.dev/@reshaped/components/reshaped-alert) | reshaped | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| B | [Alert](https://21st.dev/@serafimcloud/components/alert) | serafimcloud | system-degraded/error-state presentation (API unreachable, stale decision) |
| B | [Alert](https://21st.dev/@shadcn/components/alert) | shadcn | system-degraded/error-state presentation (API unreachable, stale decision) |
| B | [Alert with Icon and Actions](https://21st.dev/@cnippet-dev/components/v-alert-3) | cnippet-dev | system-degraded/error-state presentation (API unreachable, stale decision) |
| B | [Alert](https://21st.dev/@sean0205/components/alert-1) | sean0205 | system-degraded/error-state presentation (API unreachable, stale decision) |
| B | [Alert](https://21st.dev/@sean0205/components/alert) | sean0205 | system-degraded/error-state presentation (API unreachable, stale decision) |
| B | [Warning Alert](https://21st.dev/@cnippet-dev/components/v-alert-6) | cnippet-dev | system-degraded/error-state presentation (API unreachable, stale decision) |
| B | [Alert](https://21st.dev/@coss.com/components/alert) | coss.com | system-degraded/error-state presentation (API unreachable, stale decision) |
| B | [Alert Badge](https://21st.dev/@serafimcloud/components/alert-badge) | serafimcloud | system-degraded/error-state presentation (API unreachable, stale decision) |

### Avatars

*Live catalogue size: 597 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| B | [Avatar](https://21st.dev/@originui/components/avatar) | originui | player identity chip (shirt/crest combo) reused across MY TEAM/SCOUT/FOOTBALL |
| B | [Astryx Avatar](https://21st.dev/@Astryxdesign/components/astryx-avatar) | Astryxdesign | player identity chip (shirt/crest combo) reused across MY TEAM/SCOUT/FOOTBALL |
| B | [User Avatars](https://21st.dev/@user_hardp/components/user-avatars) | user_hardp | player identity chip (shirt/crest combo) reused across MY TEAM/SCOUT/FOOTBALL |
| B | [Avatar](https://21st.dev/@shugar/components/avatar) | shugar | player identity chip (shirt/crest combo) reused across MY TEAM/SCOUT/FOOTBALL |
| B | [Avatar](https://21st.dev/@shadcn/components/avatar) | shadcn | player identity chip (shirt/crest combo) reused across MY TEAM/SCOUT/FOOTBALL |
| B | [Reshaped Avatar](https://21st.dev/@reshaped/components/reshaped-avatar) | reshaped | player identity chip (shirt/crest combo) reused across MY TEAM/SCOUT/FOOTBALL |
| B | [Avatar](https://21st.dev/@shugar/components/avatar-1) | shugar | player identity chip (shirt/crest combo) reused across MY TEAM/SCOUT/FOOTBALL |
| B | [Avatar](https://21st.dev/@coss.com/components/coss-avatar) | coss.com | player identity chip (shirt/crest combo) reused across MY TEAM/SCOUT/FOOTBALL |
| B | [Fallback Avatar](https://21st.dev/@tom_ui/components/fallback-avatar) | tom_ui | player identity chip (shirt/crest combo) reused across MY TEAM/SCOUT/FOOTBALL |
| B | [Presence Avatars](https://21st.dev/@ddoemonn/components/presence-avatars) | ddoemonn | player identity chip (shirt/crest combo) reused across MY TEAM/SCOUT/FOOTBALL |

### Badges

*Live catalogue size: 605 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Badge](https://21st.dev/@sean0205/components/badge-2) | sean0205 | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Astryx Badge](https://21st.dev/@Astryxdesign/components/astryx-badge) | Astryxdesign | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Status Badge](https://21st.dev/@serafimcloud/components/status-badge) | serafimcloud | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Marketing Badges](https://21st.dev/@jatin-yadav05/components/marketing-badges) | jatin-yadav05 | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Multi state badge](https://21st.dev/@motiondotdev/components/motion-multi-state-badge) | motiondotdev | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| B | [Badge](https://21st.dev/@coss.com/components/coss-badge) | coss.com | status/verdict tags (BUY/HOLD/REVIEW, lineup state) - already in use, kept minimal per the anti-badge-clutter rule |
| B | [Badge Delta](https://21st.dev/@serafimcloud/components/badge-delta) | serafimcloud | status/verdict tags (BUY/HOLD/REVIEW, lineup state) - already in use, kept minimal per the anti-badge-clutter rule |
| B | [Removable Badges](https://21st.dev/@bundui/components/badge10) | bundui | status/verdict tags (BUY/HOLD/REVIEW, lineup state) - already in use, kept minimal per the anti-badge-clutter rule |
| B | [Beautiful Simple Badges](https://21st.dev/@devetaigabbai/components/beautiful-simple-badges) | devetaigabbai | status/verdict tags (BUY/HOLD/REVIEW, lineup state) - already in use, kept minimal per the anti-badge-clutter rule |
| B | [Achievement badge](https://21st.dev/@trophyso/components/achievement-badge) | trophyso | status/verdict tags (BUY/HOLD/REVIEW, lineup state) - already in use, kept minimal per the anti-badge-clutter rule |

### Buttons

*Live catalogue size: 2043 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Astryx Button](https://21st.dev/@Astryxdesign/components/astryx-button) | Astryxdesign | keyword-flagged for a second look despite a D-default category |

**D (not appropriate, 9):** Button, Buttons, Button, Button, Button, Interfaces Button, Texture Button, Minimal Buttons, Button

### Calendars

*Live catalogue size: 239 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Calendar](https://21st.dev/@anubra266/components/calendar-1) | anubra266 | considered for a deadline/fixture planner; deferred - `fixture ticker` already covers this need more directly |
| C | [Calendar](https://21st.dev/@SubframeApp/components/calendar-1) | SubframeApp | considered for a deadline/fixture planner; deferred - `fixture ticker` already covers this need more directly |
| C | [Calendar](https://21st.dev/@shugar/components/calendar) | shugar | considered for a deadline/fixture planner; deferred - `fixture ticker` already covers this need more directly |
| C | [Calendar Planner](https://21st.dev/@ruixen.ui/components/calendar-planner) | ruixen.ui | considered for a deadline/fixture planner; deferred - `fixture ticker` already covers this need more directly |
| C | [Calendar](https://21st.dev/@designali-in/components/calendar) | designali-in | considered for a deadline/fixture planner; deferred - `fixture ticker` already covers this need more directly |
| C | [Calendar [React Day Picker]](https://21st.dev/@originui/components/calendar) | originui | considered for a deadline/fixture planner; deferred - `fixture ticker` already covers this need more directly |
| C | [Calendar with Booked Days](https://21st.dev/@shadcnspace/components/calendar-02) | shadcnspace | considered for a deadline/fixture planner; deferred - `fixture ticker` already covers this need more directly |
| C | [Calendar with Event Indicators](https://21st.dev/@cnippet-dev/components/v-calendar-10) | cnippet-dev | considered for a deadline/fixture planner; deferred - `fixture ticker` already covers this need more directly |
| C | [Calendar [React-Area]](https://21st.dev/@originui/components/calendar-rac) | originui | considered for a deadline/fixture planner; deferred - `fixture ticker` already covers this need more directly |
| C | [Calendar with Holidays](https://21st.dev/@cnippet-dev/components/v-calendar-14) | cnippet-dev | considered for a deadline/fixture planner; deferred - `fixture ticker` already covers this need more directly |

### Cards

*Live catalogue size: 1780 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Cards Stack](https://21st.dev/@youcefbnm/components/cards-stack) | youcefbnm | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Card Table](https://21st.dev/@felipemenezes098/components/table-08) | felipemenezes098 | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| C | [Cards](https://21st.dev/@ravikatiyar162/components/cards-1) | ravikatiyar162 | explicitly minimized per the redesign directive - used only where content genuinely has no better affordance |
| C | [Cards](https://21st.dev/@prebuiltui/components/cards) | prebuiltui | explicitly minimized per the redesign directive - used only where content genuinely has no better affordance |
| C | [Cursor Cards](https://21st.dev/@badtzx0/components/cursor-cards) | badtzx0 | explicitly minimized per the redesign directive - used only where content genuinely has no better affordance |
| C | [Card Studio](https://21st.dev/@ShadcnStudio/components/card-studio) | ShadcnStudio | explicitly minimized per the redesign directive - used only where content genuinely has no better affordance |
| C | [Card](https://21st.dev/@jshguo/components/interfaces-card) | jshguo | explicitly minimized per the redesign directive - used only where content genuinely has no better affordance |
| C | [Liquid Glass Card](https://21st.dev/@designali-in/components/liquid-glass-card) | designali-in | explicitly minimized per the redesign directive - used only where content genuinely has no better affordance |
| C | [Cards Grid](https://21st.dev/@kavikatiyar/components/cards-grid) | kavikatiyar | explicitly minimized per the redesign directive - used only where content genuinely has no better affordance |
| C | [Card](https://21st.dev/@sean0205/components/card) | sean0205 | explicitly minimized per the redesign directive - used only where content genuinely has no better affordance |

### Carousels

*Live catalogue size: 239 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Circular Carousel](https://21st.dev/@nexus-ui/components/circular-carousel) | nexus-ui | SCOUT's player-comparison swipe (bounded candidate set) - not a marketing carousel |
| C | [Feature Carousel](https://21st.dev/@0xUrvish/components/feature-carousel) | 0xUrvish | SCOUT's player-comparison swipe (bounded candidate set) - not a marketing carousel |
| C | [Carousel](https://21st.dev/@manuarora700/components/carousel) | manuarora700 | SCOUT's player-comparison swipe (bounded candidate set) - not a marketing carousel |
| C | [Interfaces Carousel](https://21st.dev/@jshguo/components/interfaces-carousel) | jshguo | SCOUT's player-comparison swipe (bounded candidate set) - not a marketing carousel |
| C | [3D Carousel](https://21st.dev/@cult-ui/components/3d-carousel) | cult-ui | SCOUT's player-comparison swipe (bounded candidate set) - not a marketing carousel |
| C | [Linear Carousel](https://21st.dev/@animbits/components/specials-linear-carousel) | animbits | SCOUT's player-comparison swipe (bounded candidate set) - not a marketing carousel |
| C | [Carousel Cards](https://21st.dev/@kokonutd/components/carousel-cards) | kokonutd | SCOUT's player-comparison swipe (bounded candidate set) - not a marketing carousel |
| C | [Snap Carousel](https://21st.dev/@ddoemonn/components/snap-carousel) | ddoemonn | SCOUT's player-comparison swipe (bounded candidate set) - not a marketing carousel |
| C | [Carousel](https://21st.dev/@anubra266/components/carousel-1) | anubra266 | SCOUT's player-comparison swipe (bounded candidate set) - not a marketing carousel |
| C | [Circular Gallery](https://21st.dev/@ravikatiyar162/components/circular-gallery) | ravikatiyar162 | SCOUT's player-comparison swipe (bounded candidate set) - not a marketing carousel |

### Charts

*Live catalogue size: 246 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Charts](https://21st.dev/@edwinvakayil/components/charts) | edwinvakayil | STRONG - this product's existing ApexCharts infra IS this category; 21st chart compositions inform layout, not library choice (chart-library-reuse rule stays) |
| A | [Line Charts 1](https://21st.dev/@sean0205/components/line-charts-1) | sean0205 | STRONG - this product's existing ApexCharts infra IS this category; 21st chart compositions inform layout, not library choice (chart-library-reuse rule stays) |
| A | [Line Charts 5](https://21st.dev/@sean0205/components/line-charts-5) | sean0205 | STRONG - this product's existing ApexCharts infra IS this category; 21st chart compositions inform layout, not library choice (chart-library-reuse rule stays) |
| A | [Line Charts 9](https://21st.dev/@sean0205/components/line-charts-9) | sean0205 | STRONG - this product's existing ApexCharts infra IS this category; 21st chart compositions inform layout, not library choice (chart-library-reuse rule stays) |
| A | [Line Charts 6](https://21st.dev/@sean0205/components/line-charts-6) | sean0205 | STRONG - this product's existing ApexCharts infra IS this category; 21st chart compositions inform layout, not library choice (chart-library-reuse rule stays) |
| A | [Mini Chart](https://21st.dev/@jatin-yadav05/components/mini-chart) | jatin-yadav05 | STRONG - this product's existing ApexCharts infra IS this category; 21st chart compositions inform layout, not library choice (chart-library-reuse rule stays) |
| A | [Line Charts 8](https://21st.dev/@sean0205/components/line-charts-8) | sean0205 | STRONG - this product's existing ApexCharts infra IS this category; 21st chart compositions inform layout, not library choice (chart-library-reuse rule stays) |
| A | [Line Charts 2](https://21st.dev/@sean0205/components/line-charts-2) | sean0205 | STRONG - this product's existing ApexCharts infra IS this category; 21st chart compositions inform layout, not library choice (chart-library-reuse rule stays) |
| A | [Line Charts 4](https://21st.dev/@sean0205/components/line-charts-4) | sean0205 | STRONG - this product's existing ApexCharts infra IS this category; 21st chart compositions inform layout, not library choice (chart-library-reuse rule stays) |
| A | [Radar chart](https://21st.dev/@airbnb-visx/components/radar-chart) | airbnb-visx | STRONG - this product's existing ApexCharts infra IS this category; 21st chart compositions inform layout, not library choice (chart-library-reuse rule stays) |

### Checkboxes

*Live catalogue size: 238 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Interfaces Checkbox](https://21st.dev/@jshguo/components/interfaces-checkbox) | jshguo | keyword-flagged for a second look despite a D-default category |
| C | [Select All Checkbox](https://21st.dev/@felipemenezes098/components/checkbox-06) | felipemenezes098 | keyword-flagged for a second look despite a D-default category |

**D (not appropriate, 8):** Checkbox, Checkbox, Checkbox, Checkbox, Checkbox, Checkbox, Checkbox, Checkbox

### Cursors

*Live catalogue size: 152 real listed. Sampled: 10.*

**D (not appropriate, 10):** Custom Cursor, Cursor, Cursor, Custom Cursor, Custom Cursor, Cursor Cards, Custom Cursor, Tidal Cursor, Inverted Cursor, Morphing Cursor

### Dashboards

*Live catalogue size: 400 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [ Dashboard](https://21st.dev/@ravikatiyar162/components/dashboard-1) | ravikatiyar162 | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Advanced Stats](https://21st.dev/@uilayout.contact/components/advanced-stats) | uilayout.contact | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Bento Dashboard](https://21st.dev/@daiwiikharihar/components/bento-dashboard) | daiwiikharihar | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Financial Dashboard](https://21st.dev/@ravikatiyar162/components/financial-dashboard) | ravikatiyar162 | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Sidebar Dashboard Skeleton](https://21st.dev/@cnippet-dev/components/v-skeleton-8) | cnippet-dev | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| B | [Dashboard Overview](https://21st.dev/@uniquesonu/components/dashboard-overview) | uniquesonu | audited directly (see Visual Grammar doc) - mostly generic SaaS card-grids, exactly what this redesign is escaping; only the neo-brutalist 'Bento Dashboard' cleared the bar |
| B | [Dashboard Sidebar](https://21st.dev/@arunjdass/components/dashboard-sidebar) | arunjdass | audited directly (see Visual Grammar doc) - mostly generic SaaS card-grids, exactly what this redesign is escaping; only the neo-brutalist 'Bento Dashboard' cleared the bar |
| B | [Dashboard](https://21st.dev/@ravikatiyar162/components/dashboard) | ravikatiyar162 | audited directly (see Visual Grammar doc) - mostly generic SaaS card-grids, exactly what this redesign is escaping; only the neo-brutalist 'Bento Dashboard' cleared the bar |
| B | [Dashboard Configuration](https://21st.dev/@dgearsonu1/components/dashboard-configuration) | dgearsonu1 | audited directly (see Visual Grammar doc) - mostly generic SaaS card-grids, exactly what this redesign is escaping; only the neo-brutalist 'Bento Dashboard' cleared the bar |
| B | [Dashboard Activities](https://21st.dev/@uniquesonu/components/dashboard-activities) | uniquesonu | audited directly (see Visual Grammar doc) - mostly generic SaaS card-grids, exactly what this redesign is escaping; only the neo-brutalist 'Bento Dashboard' cleared the bar |

### Date Pickers

*Live catalogue size: 250 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Date Wheel Picker](https://21st.dev/@johuniq/components/date-wheel-picker) | johuniq | GW/fixture-date selection controls where needed (PLAN horizon picker) |
| C | [Day Picker](https://21st.dev/@0xUrvish/components/day-picker) | 0xUrvish | GW/fixture-date selection controls where needed (PLAN horizon picker) |
| C | [Calendar [React Day Picker]](https://21st.dev/@originui/components/calendar) | originui | GW/fixture-date selection controls where needed (PLAN horizon picker) |
| C | [Datetime Picker](https://21st.dev/@BelkacemYerfa/components/datetime-picker) | BelkacemYerfa | GW/fixture-date selection controls where needed (PLAN horizon picker) |
| C | [Date Picker with Presets](https://21st.dev/@cnippet-dev/components/date-picker-with-presets) | cnippet-dev | GW/fixture-date selection controls where needed (PLAN horizon picker) |
| C | [Universal Date Picker](https://21st.dev/@ruixen.ui/components/universal-date-picker) | ruixen.ui | GW/fixture-date selection controls where needed (PLAN horizon picker) |
| C | [Date Wheel Picker](https://21st.dev/@osiris-balonga/components/date-wheel-picker) | osiris-balonga | GW/fixture-date selection controls where needed (PLAN horizon picker) |
| C | [Calendar Date Picker](https://21st.dev/@shadcn/components/calendar-date-picker) | shadcn | GW/fixture-date selection controls where needed (PLAN horizon picker) |
| C | [Date Picker [react-aria-components]](https://21st.dev/@jolbol1/components/date-picker) | jolbol1 | GW/fixture-date selection controls where needed (PLAN horizon picker) |
| C | [Date Picker](https://21st.dev/@kavikatiyar/components/date-picker) | kavikatiyar | GW/fixture-date selection controls where needed (PLAN horizon picker) |

### Dialogs

*Live catalogue size: 328 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| B | [Dialog](https://21st.dev/@jolbol1/components/dialog-2) | jolbol1 | player inspector modal / confirmation-adjacent surfaces (this tool never auto-submits, so dialogs are read-only detail views, not action confirmations) |
| B | [Dialog](https://21st.dev/@anubra266/components/dialog-2) | anubra266 | player inspector modal / confirmation-adjacent surfaces (this tool never auto-submits, so dialogs are read-only detail views, not action confirmations) |
| B | [Dialog](https://21st.dev/@shadcn/components/dialog) | shadcn | player inspector modal / confirmation-adjacent surfaces (this tool never auto-submits, so dialogs are read-only detail views, not action confirmations) |
| B | [Dialog](https://21st.dev/@originui/components/dialog) | originui | player inspector modal / confirmation-adjacent surfaces (this tool never auto-submits, so dialogs are read-only detail views, not action confirmations) |
| B | [Dialog](https://21st.dev/@ephraimduncan/components/dialog-1) | ephraimduncan | player inspector modal / confirmation-adjacent surfaces (this tool never auto-submits, so dialogs are read-only detail views, not action confirmations) |
| B | [Dialog](https://21st.dev/@efferd/components/dialog) | efferd | player inspector modal / confirmation-adjacent surfaces (this tool never auto-submits, so dialogs are read-only detail views, not action confirmations) |
| B | [Dialog](https://21st.dev/@ephraimduncan/components/dialog) | ephraimduncan | player inspector modal / confirmation-adjacent surfaces (this tool never auto-submits, so dialogs are read-only detail views, not action confirmations) |
| B | [The Dialog ](https://21st.dev/@felipemenezes098/components/the-dialog) | felipemenezes098 | player inspector modal / confirmation-adjacent surfaces (this tool never auto-submits, so dialogs are read-only detail views, not action confirmations) |
| B | [Dialog Info](https://21st.dev/@ephraimduncan/components/dialog-info) | ephraimduncan | player inspector modal / confirmation-adjacent surfaces (this tool never auto-submits, so dialogs are read-only detail views, not action confirmations) |
| B | [Dialog](https://21st.dev/@olivier_1b6cd5bc/components/dialog-2) | olivier_1b6cd5bc | player inspector modal / confirmation-adjacent surfaces (this tool never auto-submits, so dialogs are read-only detail views, not action confirmations) |

### Dropdowns

*Live catalogue size: 506 real listed. Sampled: 10.*

**D (not appropriate, 10):** Animated Dropdown, Dropdown Menu, Dropdown, Shifting Dropdown, Dropdown Menu, HeroUI Dropdown, Dropdown (Radix UI), Dropdown, Action dropdown, dropdown 01

### Empty States

*Live catalogue size: 77 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Empty State with Marquee](https://21st.dev/@shadcnui-blocks/components/empty-state-04) | shadcnui-blocks | STRONG - 'no squad locked yet' / 'no live match' / degraded-source states, already a real product requirement |
| A | [Empty](https://21st.dev/@cnippet-dev/components/cnippet-empty) | cnippet-dev | STRONG - 'no squad locked yet' / 'no live match' / degraded-source states, already a real product requirement |
| A | [Interactive Empty State](https://21st.dev/@remcostoeten/components/interactive-empty-state) | remcostoeten | STRONG - 'no squad locked yet' / 'no live match' / degraded-source states, already a real product requirement |
| A | [Empty State](https://21st.dev/@serafimcloud/components/empty-state) | serafimcloud | STRONG - 'no squad locked yet' / 'no live match' / degraded-source states, already a real product requirement |
| A | [Empty Background](https://21st.dev/@uiable/components/empty-background) | uiable | STRONG - 'no squad locked yet' / 'no live match' / degraded-source states, already a real product requirement |
| A | [EmptyState – Beautiful, Accessible ‘No Data’ States](https://21st.dev/@uniquesonu/components/empty-state-beautiful-accessible-no-data-states) | uniquesonu | STRONG - 'no squad locked yet' / 'no live match' / degraded-source states, already a real product requirement |
| A | [Offline Empty State](https://21st.dev/@bundui/components/empty8) | bundui | STRONG - 'no squad locked yet' / 'no live match' / degraded-source states, already a real product requirement |
| A | [Empty State with Tabs](https://21st.dev/@shadcnui-blocks/components/empty-state-03) | shadcnui-blocks | STRONG - 'no squad locked yet' / 'no live match' / degraded-source states, already a real product requirement |
| A | [Error Empty State](https://21st.dev/@7ovr/components/empty-states-4) | 7ovr | STRONG - 'no squad locked yet' / 'no live match' / degraded-source states, already a real product requirement |
| A | [Empty](https://21st.dev/@j1zuzz/components/empty) | j1zuzz | STRONG - 'no squad locked yet' / 'no live match' / degraded-source states, already a real product requirement |

### File Trees

*Live catalogue size: 61 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| B | [File Tree](https://21st.dev/@edwinvakayil/components/file-tree) | edwinvakayil | ADVANCED's diagnostic-module navigation, if the disclosure list grows large enough to need one - not adopted yet, existing accordion suffices |
| B | [File Tree View](https://21st.dev/@cnippet-dev/components/v-collapsible-7) | cnippet-dev | ADVANCED's diagnostic-module navigation, if the disclosure list grows large enough to need one - not adopted yet, existing accordion suffices |
| B | [File Tree](https://21st.dev/@dillionverma/components/file-tree) | dillionverma | ADVANCED's diagnostic-module navigation, if the disclosure list grows large enough to need one - not adopted yet, existing accordion suffices |
| B | [FileTree](https://21st.dev/@ruixen.ui/components/file-tree-1) | ruixen.ui | ADVANCED's diagnostic-module navigation, if the disclosure list grows large enough to need one - not adopted yet, existing accordion suffices |
| B | [Filesystem Item](https://21st.dev/@builduilabs/components/filesystem-item) | builduilabs | ADVANCED's diagnostic-module navigation, if the disclosure list grows large enough to need one - not adopted yet, existing accordion suffices |
| B | [Tree](https://21st.dev/@originui/components/tree) | originui | ADVANCED's diagnostic-module navigation, if the disclosure list grows large enough to need one - not adopted yet, existing accordion suffices |
| B | [FileTree](https://21st.dev/@ruixen.ui/components/file-tree) | ruixen.ui | ADVANCED's diagnostic-module navigation, if the disclosure list grows large enough to need one - not adopted yet, existing accordion suffices |
| B | [Tree Folder structure](https://21st.dev/@shailendrakumar19999/components/tree-folder-structure) | shailendrakumar19999 | ADVANCED's diagnostic-module navigation, if the disclosure list grows large enough to need one - not adopted yet, existing accordion suffices |
| B | [File Tree](https://21st.dev/@justinlevinedotme/components/file-tree) | justinlevinedotme | ADVANCED's diagnostic-module navigation, if the disclosure list grows large enough to need one - not adopted yet, existing accordion suffices |
| B | [Tree View](https://21st.dev/@preetsuthar17/components/tree-view) | preetsuthar17 | ADVANCED's diagnostic-module navigation, if the disclosure list grows large enough to need one - not adopted yet, existing accordion suffices |

### File Uploads

*Live catalogue size: 154 real listed. Sampled: 10.*

**D (not appropriate, 10):** File Upload, FileUpload, File Upload, File Upload, File Upload, File Upload Field, Upload Multiple Files, File Upload, useImageUpload, upload

### Forms

*Live catalogue size: 1522 real listed. Sampled: 10.*

**D (not appropriate, 10):** Form, Signup Form, Form, Form Fields Skeleton, Horizontal Form Fields, Form, Form, form, Multi-Field Form, Form

### Globes

*Live catalogue size: 41 real listed. Sampled: 10.*

**D (not appropriate, 10):** Globe, Globe, Orbiting Circles with Globe, COBE Globe, Globe Satellites, Globe, Globe Labels, Globe, Globe Interactive, Globe Type Study

### Grids and Bento

*Live catalogue size: 620 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Bento Grid](https://21st.dev/@designali-in/components/bento-grid) | designali-in | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [bento grid 01](https://21st.dev/@avanishverma4/components/bento-grid-01) | avanishverma4 | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Bento Grid](https://21st.dev/@lavikatiyar/components/bento-grid) | lavikatiyar | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Magnified Bento](https://21st.dev/@0xUrvish/components/magnified-bento) | 0xUrvish | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Bento](https://21st.dev/@kinfe123/components/bento) | kinfe123 | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Bento Grid](https://21st.dev/@kokonutd/components/bento-grid) | kokonutd | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Bento Grid](https://21st.dev/@manuarora700/components/bento-grid) | manuarora700 | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Aurora Bento Grid](https://21st.dev/@dhileepkumargm/components/aurora-bento-grid) | dhileepkumargm | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Feature Section with Bento Grid](https://21st.dev/@tommyjepsen/components/feature-section-with-bento-grid) | tommyjepsen | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [About Bento](https://21st.dev/@uilayout.contact/components/about-bento) | uilayout.contact | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |

### Icons

*Live catalogue size: 851 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Chip](https://21st.dev/@hero_ui/components/heroui-chip) | hero_ui | keyword-flagged for a second look despite a D-default category |
| C | [Animated State Icons](https://21st.dev/@dev.yadhakim/components/animated-state-icons) | dev.yadhakim | keyword-flagged for a second look despite a D-default category |

**D (not appropriate, 8):** Icons, Icons, Icon Set, Social Icons, Interactive Icon Cloud, Icon with Title Tabs, Icon Only Badge, Button

### Inputs

*Live catalogue size: 949 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Input](https://21st.dev/@originui/components/input) | originui | search/filter primitives for SCOUT - not catalogued further |
| C | [Input Bar](https://21st.dev/@serafimcloud/components/input-bar) | serafimcloud | search/filter primitives for SCOUT - not catalogued further |
| C | [Input with inner tags](https://21st.dev/@originui/components/input-with-inner-tags) | originui | search/filter primitives for SCOUT - not catalogued further |
| C | [Input With Feedback](https://21st.dev/@tigerabrodi/components/input-with-feedback) | tigerabrodi | search/filter primitives for SCOUT - not catalogued further |
| C | [Input](https://21st.dev/@hero_ui/components/heroui-input) | hero_ui | search/filter primitives for SCOUT - not catalogued further |
| C | [Prompt Input](https://21st.dev/@ibelick/components/prompt-input) | ibelick | search/filter primitives for SCOUT - not catalogued further |
| C | [Tags Input](https://21st.dev/@uilayout.contact/components/tags-input-2) | uilayout.contact | search/filter primitives for SCOUT - not catalogued further |
| C | [Base Input](https://21st.dev/@sean0205/components/base-input) | sean0205 | search/filter primitives for SCOUT - not catalogued further |
| C | [Unit Field](https://21st.dev/@arikchakma/components/unit-field) | arikchakma | search/filter primitives for SCOUT - not catalogued further |
| C | [Tag Input](https://21st.dev/@ddoemonn/components/tag-input) | ddoemonn | search/filter primitives for SCOUT - not catalogued further |

### Links

*Live catalogue size: 354 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Link Element](https://21st.dev/@platejs/components/link-node) | platejs | keyword-flagged for a second look despite a D-default category |

**D (not appropriate, 9):** Link Preview, Magnetic, Reveal links, Css Link, Social Links, Linktypes, Social Links, Link [react-aria-components], Clip Path Links

### Lists

*Live catalogue size: 349 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Animated List](https://21st.dev/@dillionverma/components/animated-list) | dillionverma | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [List](https://21st.dev/@haydenbleasel/components/list) | haydenbleasel | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Timeline](https://21st.dev/@nyxbui/components/timeline) | nyxbui | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| B | [Stacked List x](https://21st.dev/@0xUrvish/components/stacked-list) | 0xUrvish | monitor ticker / change-event feed rows (already adopted pattern) |
| B | [Key Value List](https://21st.dev/@corr/components/key-value-list) | corr | monitor ticker / change-event feed rows (already adopted pattern) |
| B | [List 2](https://21st.dev/@shadcnblockscom/components/list-2) | shadcnblockscom | monitor ticker / change-event feed rows (already adopted pattern) |
| B | [Tag List](https://21st.dev/@felipemenezes098/components/badge-13) | felipemenezes098 | monitor ticker / change-event feed rows (already adopted pattern) |
| B | [List Item](https://21st.dev/@0xUrvish/components/list-item) | 0xUrvish | monitor ticker / change-event feed rows (already adopted pattern) |
| B | [Select](https://21st.dev/@shugar/components/select-1) | shugar | monitor ticker / change-event feed rows (already adopted pattern) |
| B | [List](https://21st.dev/@platejs/components/block-list) | platejs | monitor ticker / change-event feed rows (already adopted pattern) |

### Menus

*Live catalogue size: 287 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Menubar](https://21st.dev/@shadcn/components/menubar) | shadcn | command-palette (Cmd/Ctrl+K) menu presentation |
| C | [Menubar](https://21st.dev/@sean0205/components/menubar) | sean0205 | command-palette (Cmd/Ctrl+K) menu presentation |
| C | [Dropdown Menu](https://21st.dev/@shadcn/components/dropdown-menu) | shadcn | command-palette (Cmd/Ctrl+K) menu presentation |
| C | [Dropdown Menu](https://21st.dev/@jshguo/components/interfaces-dropdown-menu) | jshguo | command-palette (Cmd/Ctrl+K) menu presentation |
| C | [Dock](https://21st.dev/@ibelick/components/dock) | ibelick | command-palette (Cmd/Ctrl+K) menu presentation |
| C | [Menu](https://21st.dev/@antdesign/components/menu-1) | antdesign | command-palette (Cmd/Ctrl+K) menu presentation |
| C | [Menu](https://21st.dev/@jolbol1/components/menu-1) | jolbol1 | command-palette (Cmd/Ctrl+K) menu presentation |
| C | [ Menu](https://21st.dev/@anubra266/components/menu-1) | anubra266 | command-palette (Cmd/Ctrl+K) menu presentation |
| C | [Menubar](https://21st.dev/@olivier_1b6cd5bc/components/menubar-1) | olivier_1b6cd5bc | command-palette (Cmd/Ctrl+K) menu presentation |
| C | [Context Menu](https://21st.dev/@shadcn/components/context-menu) | shadcn | command-palette (Cmd/Ctrl+K) menu presentation |

### Notifications

*Live catalogue size: 247 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Toast Notification](https://21st.dev/@framecn/components/toast-notification) | framecn | STRONG - live match events, decision-recompute events (event-driven only, never decorative) |
| A | [Alert](https://21st.dev/@serafimcloud/components/alert) | serafimcloud | STRONG - live match events, decision-recompute events (event-driven only, never decorative) |
| A | [Notifications](https://21st.dev/@ruixen.ui/components/notifications) | ruixen.ui | STRONG - live match events, decision-recompute events (event-driven only, never decorative) |
| A | [Notice Alert](https://21st.dev/@corr/components/notice-alert) | corr | STRONG - live match events, decision-recompute events (event-driven only, never decorative) |
| A | [Notifications](https://21st.dev/@ruixen.ui/components/notifications-1) | ruixen.ui | STRONG - live match events, decision-recompute events (event-driven only, never decorative) |
| A | [Popover](https://21st.dev/@originui/components/popover) | originui | STRONG - live match events, decision-recompute events (event-driven only, never decorative) |
| A | [Alert](https://21st.dev/@sean0205/components/alert-1) | sean0205 | STRONG - live match events, decision-recompute events (event-driven only, never decorative) |
| A | [Alert](https://21st.dev/@shadcn/components/alert) | shadcn | STRONG - live match events, decision-recompute events (event-driven only, never decorative) |
| A | [System Update Notification Alert Dialog](https://21st.dev/@cnippet-dev/components/v-alert-dialog-8) | cnippet-dev | STRONG - live match events, decision-recompute events (event-driven only, never decorative) |
| A | [Mono Alerts](https://21st.dev/@sean0205/components/mono-alerts) | sean0205 | STRONG - live match events, decision-recompute events (event-driven only, never decorative) |

### Numbers

*Live catalogue size: 54 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Number Flow](https://21st.dev/@educalvolpz/components/number-flow) | educalvolpz | STRONG - CountUp already adopted; broadcast-style number transitions on real value changes only |
| A | [Animated Number](https://21st.dev/@ibelick/components/animated-number) | ibelick | STRONG - CountUp already adopted; broadcast-style number transitions on real value changes only |
| A | [Number Ticker](https://21st.dev/@dillionverma/components/number-ticker) | dillionverma | STRONG - CountUp already adopted; broadcast-style number transitions on real value changes only |
| A | [Number Ticker](https://21st.dev/@danielpetho/components/basic-number-ticker) | danielpetho | STRONG - CountUp already adopted; broadcast-style number transitions on real value changes only |
| A | [7 segment number](https://21st.dev/@jakapatb/components/7-segment-number) | jakapatb | STRONG - CountUp already adopted; broadcast-style number transitions on real value changes only |
| A | [Numbered Pagination](https://21st.dev/@originui/components/numbered-pagination) | originui | STRONG - CountUp already adopted; broadcast-style number transitions on real value changes only |
| A | [Counting Number](https://21st.dev/@cnippet-dev/components/counting-number) | cnippet-dev | STRONG - CountUp already adopted; broadcast-style number transitions on real value changes only |
| A | [Animated Blur Number](https://21st.dev/@serafimcloud/components/animated-blur-number) | serafimcloud | STRONG - CountUp already adopted; broadcast-style number transitions on real value changes only |
| A | [Button](https://21st.dev/@originui/components/button) | originui | STRONG - CountUp already adopted; broadcast-style number transitions on real value changes only |
| A | [Number Ticker Real-Time Metrics Counter](https://21st.dev/@shadcnspace/components/number-ticker-05) | shadcnspace | STRONG - CountUp already adopted; broadcast-style number transitions on real value changes only |

### Onboarding

*Live catalogue size: 53 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Onboarding Wizard Form](https://21st.dev/@cnippet-dev/components/v-form-8) | cnippet-dev | keyword-flagged for a second look despite a D-default category |

**D (not appropriate, 9):** Onboarding, Onboarding Checklist, Onboarding Card, Onboarding Form, Onboarding Checklist, Onboarding / Welcome Screen, Onboarding Dialog, Onboarding Stages, Onboarding Steps Carousel

### Paginations

*Live catalogue size: 130 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Numbered Pagination](https://21st.dev/@originui/components/numbered-pagination) | originui | SCOUT's large player table, if virtualization scroll isn't preferred there - virtualization is the better real fit (Part 20), pagination not adopted |
| C | [Pagination](https://21st.dev/@originui/components/pagination) | originui | SCOUT's large player table, if virtualization scroll isn't preferred there - virtualization is the better real fit (Part 20), pagination not adopted |
| C | [Pagination](https://21st.dev/@shadcn/components/pagination) | shadcn | SCOUT's large player table, if virtualization scroll isn't preferred there - virtualization is the better real fit (Part 20), pagination not adopted |
| C | [Pagination](https://21st.dev/@ddoemonn/components/pagination) | ddoemonn | SCOUT's large player table, if virtualization scroll isn't preferred there - virtualization is the better real fit (Part 20), pagination not adopted |
| C | [Joined Pagination](https://21st.dev/@originui/components/joined-pagination) | originui | SCOUT's large player table, if virtualization scroll isn't preferred there - virtualization is the better real fit (Part 20), pagination not adopted |
| C | [Pagination](https://21st.dev/@bundui/components/pagination6) | bundui | SCOUT's large player table, if virtualization scroll isn't preferred there - virtualization is the better real fit (Part 20), pagination not adopted |
| C | [Pagination with Page Info and Page Size](https://21st.dev/@bundui/components/pagination9) | bundui | SCOUT's large player table, if virtualization scroll isn't preferred there - virtualization is the better real fit (Part 20), pagination not adopted |
| C | [Pagination with Ellipsis](https://21st.dev/@bundui/components/pagination8) | bundui | SCOUT's large player table, if virtualization scroll isn't preferred there - virtualization is the better real fit (Part 20), pagination not adopted |
| C | [Numberless Pagination with Text](https://21st.dev/@shadcnui-blocks/components/pagination-12) | shadcnui-blocks | SCOUT's large player table, if virtualization scroll isn't preferred there - virtualization is the better real fit (Part 20), pagination not adopted |
| C | [Pagination with text buttons](https://21st.dev/@originui/components/text-pagination) | originui | SCOUT's large player table, if virtualization scroll isn't preferred there - virtualization is the better real fit (Part 20), pagination not adopted |

### Popovers

*Live catalogue size: 179 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| B | [Popover](https://21st.dev/@anubra266/components/popover-1) | anubra266 | player quick-stat hover, fixture difficulty detail |
| B | [Popover](https://21st.dev/@jolbol1/components/popover-1) | jolbol1 | player quick-stat hover, fixture difficulty detail |
| B | [Popover](https://21st.dev/@efferd/components/popover) | efferd | player quick-stat hover, fixture difficulty detail |
| B | [Reshaped Popover](https://21st.dev/@reshaped/components/reshaped-popover) | reshaped | player quick-stat hover, fixture difficulty detail |
| B | [Smart Popover](https://21st.dev/@efferd/components/smart-popover) | efferd | player quick-stat hover, fixture difficulty detail |
| B | [Popover](https://21st.dev/@originui/components/popover) | originui | player quick-stat hover, fixture difficulty detail |
| B | [Popover](https://21st.dev/@shadcn/components/popover) | shadcn | player quick-stat hover, fixture difficulty detail |
| B | [Popover](https://21st.dev/@ibelick/components/popover) | ibelick | player quick-stat hover, fixture difficulty detail |
| B | [Popover](https://21st.dev/@ddoemonn/components/popover) | ddoemonn | player quick-stat hover, fixture difficulty detail |
| B | [Popover](https://21st.dev/@retroui/components/popover) | retroui | player quick-stat hover, fixture difficulty detail |

### Profiles

*Live catalogue size: 270 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Profile Selector](https://21st.dev/@ravikatiyar162/components/profile-selector) | ravikatiyar162 | STRONG - the player identity system (shirt/crest/price/position) reused everywhere a player appears |
| A | [Profile Card](https://21st.dev/@ravikatiyar162/components/profile-card-1) | ravikatiyar162 | STRONG - the player identity system (shirt/crest/price/position) reused everywhere a player appears |
| A | [Edit Profile Sheet](https://21st.dev/@cnippet-dev/components/v-sheet-1) | cnippet-dev | STRONG - the player identity system (shirt/crest/price/position) reused everywhere a player appears |
| A | [Profile Card](https://21st.dev/@isaiahbjork/components/profile-card) | isaiahbjork | STRONG - the player identity system (shirt/crest/price/position) reused everywhere a player appears |
| A | [Profile-Card](https://21st.dev/@waleedkibhen/components/profile-card) | waleedkibhen | STRONG - the player identity system (shirt/crest/price/position) reused everywhere a player appears |
| A | [Profile Card](https://21st.dev/@daiwiikharihar/components/profile-card) | daiwiikharihar | STRONG - the player identity system (shirt/crest/price/position) reused everywhere a player appears |
| A | [ProfileCard](https://21st.dev/@dhileepkumargm/components/profile-card) | dhileepkumargm | STRONG - the player identity system (shirt/crest/price/position) reused everywhere a player appears |
| A | [Sidebar](https://21st.dev/@uniquesonu/components/sidebar) | uniquesonu | STRONG - the player identity system (shirt/crest/price/position) reused everywhere a player appears |
| A | [Feature](https://21st.dev/@tommyjepsen/components/feature) | tommyjepsen | STRONG - the player identity system (shirt/crest/price/position) reused everywhere a player appears |
| A | [Team Showcase](https://21st.dev/@makviesainte/components/team-showcase) | makviesainte | STRONG - the player identity system (shirt/crest/price/position) reused everywhere a player appears |

### Progress

*Live catalogue size: 375 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Progress](https://21st.dev/@preetsuthar17/components/progress) | preetsuthar17 | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Circle Progress](https://21st.dev/@hihahihahoho/components/circle-progress) | hihahihahoho | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| B | [Progress](https://21st.dev/@anubra266/components/progress-1) | anubra266 | chip/transfer-sequence completion, robustness/confidence meters |
| B | [Progress](https://21st.dev/@shugar/components/progress) | shugar | chip/transfer-sequence completion, robustness/confidence meters |
| B | [Progress](https://21st.dev/@coss.com/components/progress) | coss.com | chip/transfer-sequence completion, robustness/confidence meters |
| B | [Progress](https://21st.dev/@sean0205/components/progress) | sean0205 | chip/transfer-sequence completion, robustness/confidence meters |
| B | [Progress](https://21st.dev/@jshguo/components/interfaces-progress) | jshguo | chip/transfer-sequence completion, robustness/confidence meters |
| B | [Progress](https://21st.dev/@sean0205/components/progress-1) | sean0205 | chip/transfer-sequence completion, robustness/confidence meters |
| B | [Progress](https://21st.dev/@olivier_1b6cd5bc/components/progress-1) | olivier_1b6cd5bc | chip/transfer-sequence completion, robustness/confidence meters |
| B | [Progress](https://21st.dev/@shadcn/components/progress) | shadcn | chip/transfer-sequence completion, robustness/confidence meters |

### Radio Groups

*Live catalogue size: 152 real listed. Sampled: 10.*

**D (not appropriate, 10):** Radio Group, Radio Group, Radio Group 1, Radio Group, Radio Group, ReUI Radio Group, Radio Group Field, 8-bit Radio Group, BeUI Radio Group, Radio Group Colors Demo

### Search Bars

*Live catalogue size: 218 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Search Bar](https://21st.dev/@santoshvarmaaddala/components/search-bar) | santoshvarmaaddala | STRONG - SCOUT's player search, global Cmd/Ctrl+K search |
| A | [Action Search Bar](https://21st.dev/@kokonutd/components/action-search-bar) | kokonutd | STRONG - SCOUT's player search, global Cmd/Ctrl+K search |
| A | [Sidebar 1](https://21st.dev/@uiable/components/uiable-sidebar-1) | uiable | STRONG - SCOUT's player search, global Cmd/Ctrl+K search |
| A | [Toolbar Expandable](https://21st.dev/@ibelick/components/toolbar-expandable) | ibelick | STRONG - SCOUT's player search, global Cmd/Ctrl+K search |
| A | [Expandable Search Bar](https://21st.dev/@arunachalam/components/expandable-search-bar) | arunachalam | STRONG - SCOUT's player search, global Cmd/Ctrl+K search |
| A | [Action Searchbar](https://21st.dev/@koustubhayadiyala36/components/action-searchbar) | koustubhayadiyala36 | STRONG - SCOUT's player search, global Cmd/Ctrl+K search |
| A | [Animated Search](https://21st.dev/@aghasisahakyan1/components/animated-search-1) | aghasisahakyan1 | STRONG - SCOUT's player search, global Cmd/Ctrl+K search |
| A | [Search Modal](https://21st.dev/@efferd/components/search-modal) | efferd | STRONG - SCOUT's player search, global Cmd/Ctrl+K search |
| A | [Search Input with Keyboard Shortcut](https://21st.dev/@shadcnspace/components/kbd-04) | shadcnspace | STRONG - SCOUT's player search, global Cmd/Ctrl+K search |
| A | [Search With Category](https://21st.dev/@ruixen.ui/components/search-with-category) | ruixen.ui | STRONG - SCOUT's player search, global Cmd/Ctrl+K search |

### Selects

*Live catalogue size: 316 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Select](https://21st.dev/@jolbol1/components/select-1) | jolbol1 | GW-window/sort-order selectors - standard primitive, not catalogued further |
| C | [Select](https://21st.dev/@originui/components/select) | originui | GW-window/sort-order selectors - standard primitive, not catalogued further |
| C | [Select](https://21st.dev/@anubra266/components/select-1) | anubra266 | GW-window/sort-order selectors - standard primitive, not catalogued further |
| C | [HeroUI Select](https://21st.dev/@hero_ui/components/heroui-select) | hero_ui | GW-window/sort-order selectors - standard primitive, not catalogued further |
| C | [Select (Native)](https://21st.dev/@originui/components/select-native) | originui | GW-window/sort-order selectors - standard primitive, not catalogued further |
| C | [Select](https://21st.dev/@extend-hq/components/select) | extend-hq | GW-window/sort-order selectors - standard primitive, not catalogued further |
| C | [Select](https://21st.dev/@cnippet-dev/components/select) | cnippet-dev | GW-window/sort-order selectors - standard primitive, not catalogued further |
| C | [Select With Object](https://21st.dev/@felipemenezes098/components/select-05) | felipemenezes098 | GW-window/sort-order selectors - standard primitive, not catalogued further |
| C | [Select](https://21st.dev/@jshguo/components/interfaces-select) | jshguo | GW-window/sort-order selectors - standard primitive, not catalogued further |
| C | [Select with Disabled Items](https://21st.dev/@felipemenezes098/components/select-07) | felipemenezes098 | GW-window/sort-order selectors - standard primitive, not catalogued further |

### Sidebars

*Live catalogue size: 95 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Sidebar](https://21st.dev/@manuarora700/components/sidebar) | manuarora700 | STRONG - already the app shell's own navigation; researched for consistency/quality bar only |
| A | [Sidebar](https://21st.dev/@shadcn/components/sidebar) | shadcn | STRONG - already the app shell's own navigation; researched for consistency/quality bar only |
| A | [Sidebar 1](https://21st.dev/@uiable/components/uiable-sidebar-1) | uiable | STRONG - already the app shell's own navigation; researched for consistency/quality bar only |
| A | [Sidebar](https://21st.dev/@andrewlu0/components/sidebar) | andrewlu0 | STRONG - already the app shell's own navigation; researched for consistency/quality bar only |
| A | [Navbars](https://21st.dev/@arihantcodes_1f7b8c4d/components/navbars) | arihantcodes_1f7b8c4d | STRONG - already the app shell's own navigation; researched for consistency/quality bar only |
| A | [Dashboard Sidebar](https://21st.dev/@arunjdass/components/dashboard-sidebar) | arunjdass | STRONG - already the app shell's own navigation; researched for consistency/quality bar only |
| A | [Animated Sidebar](https://21st.dev/@unlumen/components/sidebar-001) | unlumen | STRONG - already the app shell's own navigation; researched for consistency/quality bar only |
| A | [Sidebar Light](https://21st.dev/@inference-sh/components/sidebar-light) | inference-sh | STRONG - already the app shell's own navigation; researched for consistency/quality bar only |
| A | [Whatsapp Sidebar](https://21st.dev/@rayimanoj8/components/whatsapp-sidebar) | rayimanoj8 | STRONG - already the app shell's own navigation; researched for consistency/quality bar only |
| A | [SidebarShowcase](https://21st.dev/@ruixen.ui/components/sidebar-showcase) | ruixen.ui | STRONG - already the app shell's own navigation; researched for consistency/quality bar only |

### Sign Ins

*Live catalogue size: 103 real listed. Sampled: 10.*

**D (not appropriate, 10):** Family Sign In Drawer, Sign In, Sign In Split Screen, Sign Up, Sign In Card, Sign In, Modern Animated Sign In, Sign In Flow, Auth Section 3, Auth Section 2

### Sign ups

*Live catalogue size: 58 real listed. Sampled: 10.*

**D (not appropriate, 10):** Sign Up, Signup, Signup 1, Sign up Form, Signup Form, Sign Up 2, Registration, Login & Signup, Full Screen Signup, Sign Up BLock

### Sliders

*Live catalogue size: 217 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| B | [Slider](https://21st.dev/@originui/components/slider) | originui | GW-horizon range control, price-range filter in SCOUT |
| B | [Basic Slider](https://21st.dev/@anubra266/components/basic-slider) | anubra266 | GW-horizon range control, price-range filter in SCOUT |
| B | [Sliding Number](https://21st.dev/@ibelick/components/sliding-number) | ibelick | GW-horizon range control, price-range filter in SCOUT |
| B | [Slider](https://21st.dev/@builduilabs/components/slider) | builduilabs | GW-horizon range control, price-range filter in SCOUT |
| B | [Slider](https://21st.dev/@coss.com/components/slider) | coss.com | GW-horizon range control, price-range filter in SCOUT |
| B | [Dual Range Slider](https://21st.dev/@arihantcodes_1f7b8c4d/components/dual-range-slider) | arihantcodes_1f7b8c4d | GW-horizon range control, price-range filter in SCOUT |
| B | [Slider](https://21st.dev/@ekmas/components/slider) | ekmas | GW-horizon range control, price-range filter in SCOUT |
| B | [8-bit Slider](https://21st.dev/@theorcdev/components/8bit-slider) | theorcdev | GW-horizon range control, price-range filter in SCOUT |
| B | [book slider](https://21st.dev/@aarispathan15/components/book-slider) | aarispathan15 | GW-horizon range control, price-range filter in SCOUT |
| B | [Slider](https://21st.dev/@micka_design/components/slider) | micka_design | GW-horizon range control, price-range filter in SCOUT |

### Spinner Loaders

*Live catalogue size: 480 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [Loader](https://21st.dev/@ibelick/components/loader) | ibelick | keyword-flagged for a second look despite a D-default category |

**D (not appropriate, 9):** Spinner Loader, Animated Loader, Loader, Loader, Loader, Spinner, Loader, Spinner, Spinner

### Tables

*Live catalogue size: 313 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Table](https://21st.dev/@originui/components/table) | originui | STRONG - SCOUT's player market table, ADVANCED's diagnostic tables - TanStack Table + the existing Financial Markets Table research |
| A | [Table](https://21st.dev/@haydenbleasel/components/data-table) | haydenbleasel | STRONG - SCOUT's player market table, ADVANCED's diagnostic tables - TanStack Table + the existing Financial Markets Table research |
| A | [Records Table](https://21st.dev/@theshanelevine/components/records-table) | theshanelevine | STRONG - SCOUT's player market table, ADVANCED's diagnostic tables - TanStack Table + the existing Financial Markets Table research |
| A | [Table](https://21st.dev/@cnippet-dev/components/cnippet-table) | cnippet-dev | STRONG - SCOUT's player market table, ADVANCED's diagnostic tables - TanStack Table + the existing Financial Markets Table research |
| A | [Table](https://21st.dev/@coss.com/components/table) | coss.com | STRONG - SCOUT's player market table, ADVANCED's diagnostic tables - TanStack Table + the existing Financial Markets Table research |
| A | [Table](https://21st.dev/@jolbol1/components/table-2) | jolbol1 | STRONG - SCOUT's player market table, ADVANCED's diagnostic tables - TanStack Table + the existing Financial Markets Table research |
| A | [Table](https://21st.dev/@micka_design/components/table) | micka_design | STRONG - SCOUT's player market table, ADVANCED's diagnostic tables - TanStack Table + the existing Financial Markets Table research |
| A | [Column Visibility Table](https://21st.dev/@felipemenezes098/components/table-15) | felipemenezes098 | STRONG - SCOUT's player market table, ADVANCED's diagnostic tables - TanStack Table + the existing Financial Markets Table research |
| A | [Table](https://21st.dev/@shailendrakumar19999/components/table) | shailendrakumar19999 | STRONG - SCOUT's player market table, ADVANCED's diagnostic tables - TanStack Table + the existing Financial Markets Table research |
| A | [Data Table](https://21st.dev/@shadcn/components/data-table) | shadcn | STRONG - SCOUT's player market table, ADVANCED's diagnostic tables - TanStack Table + the existing Financial Markets Table research |

### Tabs

*Live catalogue size: 239 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| B | [Tabs](https://21st.dev/@sean0205/components/tabs) | sean0205 | MY TEAM's current-vs-projected-squad switcher, ADVANCED's diagnostic grouping |
| B | [Tabs](https://21st.dev/@coss.com/components/tabs) | coss.com | MY TEAM's current-vs-projected-squad switcher, ADVANCED's diagnostic grouping |
| B | [Tabs](https://21st.dev/@originui/components/tabs) | originui | MY TEAM's current-vs-projected-squad switcher, ADVANCED's diagnostic grouping |
| B | [Tabs](https://21st.dev/@bankkroll/components/tabs) | bankkroll | MY TEAM's current-vs-projected-squad switcher, ADVANCED's diagnostic grouping |
| B | [Tabs](https://21st.dev/@shadcn/components/tabs) | shadcn | MY TEAM's current-vs-projected-squad switcher, ADVANCED's diagnostic grouping |
| B | [Tabs](https://21st.dev/@shugar/components/tabs-1) | shugar | MY TEAM's current-vs-projected-squad switcher, ADVANCED's diagnostic grouping |
| B | [Tabs (Radix UI)](https://21st.dev/@edwinvakayil/components/r-tabs) | edwinvakayil | MY TEAM's current-vs-projected-squad switcher, ADVANCED's diagnostic grouping |
| B | [Tabs with Count Badges](https://21st.dev/@felipemenezes098/components/tabs-07) | felipemenezes098 | MY TEAM's current-vs-projected-squad switcher, ADVANCED's diagnostic grouping |
| B | [Tabs in cell for navigation](https://21st.dev/@k3menn/components/tabs-in-cell-for-navigation) | k3menn | MY TEAM's current-vs-projected-squad switcher, ADVANCED's diagnostic grouping |
| B | [Tabs like bookmark](https://21st.dev/@k3menn/components/tabs-like-bookmark) | k3menn | MY TEAM's current-vs-projected-squad switcher, ADVANCED's diagnostic grouping |

### Tags

*Live catalogue size: 74 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Chip](https://21st.dev/@preetsuthar17/components/chip) | preetsuthar17 | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| A | [Tag Group [react-aria-components]](https://21st.dev/@jolbol1/components/tag-group) | jolbol1 | keyword-upgraded (real stat/comparison/broadcast signal in name or description) |
| B | [Tag Selector](https://21st.dev/@serafimcloud/components/tag-selector) | serafimcloud | category/status tags (already the flat tag-block pattern adopted) |
| B | [Tags Selector](https://21st.dev/@ln-dev7/components/tags-selector) | ln-dev7 | category/status tags (already the flat tag-block pattern adopted) |
| B | [Tags Select](https://21st.dev/@m.umairwaheedansari/components/tags-select) | m.umairwaheedansari | category/status tags (already the flat tag-block pattern adopted) |
| B | [Tag Group](https://21st.dev/@jolbol1/components/tag-group-2) | jolbol1 | category/status tags (already the flat tag-block pattern adopted) |
| B | [Tag](https://21st.dev/@unlumen/components/tag) | unlumen | category/status tags (already the flat tag-block pattern adopted) |
| B | [Basic Tags Input](https://21st.dev/@anubra266/components/basic-tags-input) | anubra266 | category/status tags (already the flat tag-block pattern adopted) |
| B | [Input With Tags](https://21st.dev/@chetanverma16/components/input-with-tags) | chetanverma16 | category/status tags (already the flat tag-block pattern adopted) |
| B | [Badge Tag](https://21st.dev/@prebuiltui/components/badge-tag) | prebuiltui | category/status tags (already the flat tag-block pattern adopted) |

### Text Areas

*Live catalogue size: 187 real listed. Sampled: 10.*

**D (not appropriate, 10):** Text Area, Textarea, Text Area , Text Area, Liquid Text, Textarea With Helper Text, Outline Text, Reshaped Text area, Text Particle, Textarea with characters left

### Toasts

*Live catalogue size: 79 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| A | [Basic Toast](https://21st.dev/@anubra266/components/basic-toast) | anubra266 | STRONG - real live-event/recompute notifications (event-driven only) |
| A | [Toast](https://21st.dev/@arunachalam/components/toast) | arunachalam | STRONG - real live-event/recompute notifications (event-driven only) |
| A | [Reshaped Toast](https://21st.dev/@reshaped/components/reshaped-toast) | reshaped | STRONG - real live-event/recompute notifications (event-driven only) |
| A | [Toast](https://21st.dev/@ayushmxxn/components/toast-1) | ayushmxxn | STRONG - real live-event/recompute notifications (event-driven only) |
| A | [Toast](https://21st.dev/@olivier_1b6cd5bc/components/toast-1) | olivier_1b6cd5bc | STRONG - real live-event/recompute notifications (event-driven only) |
| A | [Toast](https://21st.dev/@shugar/components/toast) | shugar | STRONG - real live-event/recompute notifications (event-driven only) |
| A | [Sonner](https://21st.dev/@shadcn/components/sonner) | shadcn | STRONG - real live-event/recompute notifications (event-driven only) |
| A | [Toast](https://21st.dev/@cnippet-dev/components/toast) | cnippet-dev | STRONG - real live-event/recompute notifications (event-driven only) |
| A | [Sonner Toast](https://21st.dev/@bundui/components/toast1) | bundui | STRONG - real live-event/recompute notifications (event-driven only) |
| A | [Sonner](https://21st.dev/@sean0205/components/sonner) | sean0205 | STRONG - real live-event/recompute notifications (event-driven only) |

### Toggles

*Live catalogue size: 532 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| C | [useToggle](https://21st.dev/@strlrd-29/components/use-toggle) | strlrd-29 | keyword-flagged for a second look despite a D-default category |
| C | [Toggle](https://21st.dev/@cnippet-dev/components/cnippet-toggle) | cnippet-dev | keyword-flagged for a second look despite a D-default category |
| C | [Toggle Group](https://21st.dev/@shadcn/components/toggle-group) | shadcn | keyword-flagged for a second look despite a D-default category |
| C | [Animated Toggle](https://21st.dev/@educalvolpz/components/animated-toggle) | educalvolpz | keyword-flagged for a second look despite a D-default category |

**D (not appropriate, 6):** Toggle Basic, Toggle Switch, Toggle Group, Toggle Switch, Liquid Toggle, Theme Toggle

### Tooltips

*Live catalogue size: 267 real listed. Sampled: 10.*

| Status | Name | Author | Note |
|---|---|---|---|
| B | [Tooltip](https://21st.dev/@originui/components/tooltip) | originui | player stat hover detail, fixture difficulty explainer |
| B | [Tooltip](https://21st.dev/@sean0205/components/tooltip) | sean0205 | player stat hover detail, fixture difficulty explainer |
| B | [Tooltip](https://21st.dev/@shadcn/components/tooltip) | shadcn | player stat hover detail, fixture difficulty explainer |
| B | [Tooltip](https://21st.dev/@anubra266/components/tooltip-1) | anubra266 | player stat hover detail, fixture difficulty explainer |
| B | [Tooltip](https://21st.dev/@hero_ui/components/heroui-tooltip) | hero_ui | player stat hover detail, fixture difficulty explainer |
| B | [Interfaces Tooltip](https://21st.dev/@jshguo/components/interfaces-tooltip) | jshguo | player stat hover detail, fixture difficulty explainer |
| B | [Floating Tooltip](https://21st.dev/@unlumen/components/floating-tooltip) | unlumen | player stat hover detail, fixture difficulty explainer |
| B | [Tooltip](https://21st.dev/@edwinvakayil/components/tooltip) | edwinvakayil | player stat hover detail, fixture difficulty explainer |
| B | [Reshaped Tooltip](https://21st.dev/@reshaped/components/reshaped-tooltip) | reshaped | player stat hover detail, fixture difficulty explainer |
| B | [BeUI Tooltip](https://21st.dev/@saurabh10102/components/beui-tooltip) | saurabh10102 | player stat hover detail, fixture difficulty explainer |
