---
name: ROM Apps
description: Signal in focus — expressive product chapters built around real app screens.
colors:
  bg: "#080f1e"
  text: "#f2f6ff"
  muted: "#b5c4db"
  dim: "#9eafca"
  signal-blue: "#91c5ff"
  signal-hover: "#c2dfff"
  stage: "#12223b"
  line: "#adc8ef26"
  line-strong: "#adc8ef4d"
  paper: "#edf3fc"
  paper-ink: "#152540"
  paper-link: "#23559c"
  paper-muted: "#425976"
  paper-hover: "#dce9fa"
  nova-cobalt: "#142fc4"
  nova-stage: "#0d1b50"
  nova-muted: "#d2ddff"
  white: "#ffffff"
typography:
  display:
    fontFamily: '"Space Grotesk", system-ui, sans-serif'
    fontSize: "clamp(60px, 6.1vw, 88px)"
    fontWeight: 500
    lineHeight: 0.99
    letterSpacing: "-0.04em"
  headline:
    fontFamily: '"Space Grotesk", system-ui, sans-serif'
    fontSize: "clamp(44px, 4.6vw, 66px)"
    fontWeight: 500
    lineHeight: 1.06
    letterSpacing: "-0.04em"
  platform-title:
    fontFamily: '"Space Grotesk", system-ui, sans-serif'
    fontSize: "29px"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "-0.03em"
  body:
    fontFamily: '"Segoe UI Variable", "Aptos", system-ui, sans-serif'
    fontSize: "16px"
    lineHeight: 1.75
  action:
    fontFamily: '"Segoe UI Variable", "Aptos", system-ui, sans-serif'
    fontSize: "13px"
    fontWeight: 650
  caption:
    fontFamily: '"Segoe UI Variable", "Aptos", system-ui, sans-serif'
    fontSize: "12px"
    lineHeight: 1.65
rounded:
  choice: "5px"
  control: "6px"
  frame: "12px"
  circle: "50%"
spacing:
  section: "104px"
  section-tablet: "75px"
  section-mobile: "65px"
  gutter: "48px"
  gutter-tablet: "32px"
  gutter-mobile: "20px"
  gutter-compact: "16px"
components:
  button-primary:
    backgroundColor: "{colors.signal-blue}"
    textColor: "#0b2343"
    typography: "{typography.action}"
    rounded: "{rounded.control}"
    padding: "14px 22px"
  button-primary-hover:
    backgroundColor: "{colors.signal-hover}"
  button-nova:
    backgroundColor: "{colors.white}"
    textColor: "#1832b3"
    typography: "{typography.action}"
    rounded: "{rounded.control}"
    padding: "14px 22px"
  nav-action:
    textColor: "{colors.signal-blue}"
    rounded: "{rounded.control}"
    padding: "10px 17px"
  preview-choice:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    rounded: "{rounded.choice}"
    padding: "8px 5px"
  preview-choice-selected:
    backgroundColor: "{colors.signal-blue}"
    textColor: "#0b2343"
    rounded: "{rounded.choice}"
    padding: "8px 5px"
  referral-code:
    textColor: "#0b2343"
    rounded: "{rounded.control}"
    padding: "8px 21px"
  platform-row:
    textColor: "{colors.paper-ink}"
    typography: "{typography.platform-title}"
    padding: "22px 0"
  faq-disclosure:
    textColor: "{colors.text}"
    backgroundColor: "{colors.bg}"
---

# Design System: ROM Apps

## Overview

**Creative North Star: "Signal in focus"**

ROM Apps pairs oversized, compact display type with real product screens and broad changes of color. A midnight navy opening gives ice blue actions and the dimensional Polybot preview prominence. A ice blue referral ribbon, ice-white download section, and cobalt Nova chapter establish distinct landmarks before the quieter FAQ and footer.

Depth belongs to the product imagery. Thin geometric signal arcs draw once behind the opening composition; Nova uses static circular outlines. These shapes are decoration, not market data. Product interfaces stay recognizable, and short captions explain what each screenshot actually shows. The verification, changelog, and 404 pages reuse the homepage header, footer, and stylesheet; the 404 page uses root-absolute URLs for nested paths.

**Key Characteristics:**

- Large, tightly set Space Grotesk headlines with restrained body copy.
- Ice blue, ice-white, and cobalt chapters within a midnight navy page.
- Real product screenshots in gently dimensional frames.
- A single entrance composition followed by a still page.
- Native links, buttons, disclosures, scrolling, and modal behavior.

This documents the homepage implementation in `index.html`, `assets/market-stage.css`, and `assets/market-stage.js`. The independently deployed Nova application has its own styling. `PRODUCT.md` owns product truth; this file owns its visual expression. Token primitives above are normative. The companion `.impeccable/design.json` holds motion, depth, breakpoints, component previews, and narrative metadata.

## Colors

Ice blue supplies the opening's visual energy, blue-tinted paper makes downloads easy to scan, and saturated cobalt gives Nova a separate identity.

### Primary

- **Signal Blue** supplies Polybot actions, the selected preview choice, highlighted headline words, focus rings, and the full-width referral ribbon.
- **Signal Hover** lightens the primary action on hover.
- The stylesheet uses `--blue` for shared links and `--accent` for highlights. Both resolve to Signal Blue at the root, with readable local colors on paper and cobalt sections.

### Secondary

- **Nova Cobalt** fills the Nova chapter. **Nova Stage** supports its actual radar screenshot; **Nova Muted** and **White** distinguish supporting copy and primary content.
- Nova locally changes the shared accent roles to white. Its launch action is white with cobalt text.

### Neutral

- **Background**, **Text**, **Muted**, and **Dim** provide the midnight navy page and its reading hierarchy.
- **Stage** is the Polybot preview frame. **Line** and **Line Strong** separate navigation, controls, downloads, and FAQ rows without heavy card outlines.
- **Paper**, **Paper Ink**, **Paper Link**, and **Paper Muted** form the download section's light theme. **Paper Hover** gives the entire platform row a hover response.

**The Chapter Color Rule.** Resolve shared colors in the section's context: deep blue links and focus on paper, white actions on cobalt, ice blue accents on midnight navy. Do not apply the root ice blue blindly to every section.

## Typography

**Display Font:** self-hosted Space Grotesk, with system sans-serif fallback. The variable font covers weights 400–700 and uses `font-display: swap`.

**Body Font:** Segoe UI Variable, Aptos, then the platform sans-serif stack. The homepage does not use a separate monospace family.

The display face carries the identity through compact line height, modest weight, and tight tracking. Body text remains calmer and more open. Headlines use balanced wrapping; paragraphs use pretty wrapping with ordinary browser fallbacks.

- **Display:** the hero uses the frontmatter display role and a short measure (8ch on larger layouts). Tablet and phone sizes are explicitly adjusted with media queries.
- **Headline:** major section headings use the headline role. Nova has its own fluid size (46–69px); FAQ is quieter (40–55px).
- **Platform title:** download rows use the platform-title role, with a separate circular arrow.
- **Body:** opening copy is 16px with a 39ch maximum measure. Other section paragraphs are 14–15px depending on viewport, with generous line height.
- **Action and caption:** actions are medium-to-semibold; support copy, captions, status text, and version labels are 12px. Version numerals use tabular spacing.

**The Screenshot Context Rule.** Keep the short screenshot caption and state description beside the image. Display type must never replace the explanation of what is shown.

## Layout

The main container is capped at 1320px. It uses 48px side gutters by default, 32px at 1150px and below, 20px at 650px and below, and 16px at 360px and below. Section padding steps from 104px to 75px and then 65px.

Above 900px, the opening places its text stack and product preview in two columns, with the preview given more width. At 900px and below, the preview moves beneath a two-column text introduction; this is the 768px layout. At 650px and below, the introduction becomes one column, the preview uses the full container width, and its perspective tilt is removed. The compact 360px layout makes the main hero action full width.

The referral ribbon spans the viewport. Its copy, linked code, and disclosure occupy three columns on desktop, then reflow into fewer columns. On phones the terms occupy a full-width row beneath the code. Downloads place introductory copy beside equally weighted Windows and Mac rows. Nova pairs copy with its screen; FAQ pairs a short introduction with native disclosures. Downloads, Nova, and FAQ become single-column sections at 650px.

The header is sticky, with visible product navigation and a Get Polybot action. On phones, the redundant Polybot link and APPS suffix are hidden while Nova and the download action remain visible. Anchor scroll padding accounts for the header. The footer closes with a large ice blue signoff and a compact link row.

## Elevation & Depth

The Polybot frame uses a broad black shadow, a 1400px perspective context, a slight Y rotation, and a one-degree Z rotation. Nova's frame has a blue-tinted shadow and a two-degree tilt. These are object treatments for screenshots; download and FAQ rows remain flat. At 900px and below both product frames are level.

The signal arcs draw once over 4.4 seconds. The desktop Polybot frame enters over 1.5 seconds; the level tablet frame uses a 1.1-second upward entrance. Lower sections move upward once as they enter the viewport over 0.8 seconds, with their content always visible. Screenshot switching fades over 0.4 seconds. Nova's image grows slightly inside its fixed boundary on hover.

The native image viewer uses a dark surface, a broad shadow, and a blurred backdrop. Its brief opening transition does not change the page's scroll position. Exact motion and shadow values are in the sidecar.

**The Motion Settles Rule.** Motion finishes: no automatic screenshot cycling, continuous decorative loop, pointer tracking, or replay control. Reduced-motion disables the signal and preview entrance animations, removes the Polybot tilt, and makes smooth scrolling immediate; other transitions are reduced to near-instant changes.

## Shapes

Controls and image openings have small corners (6px); screenshot frames and the shared viewer use larger corners (12px). Preview choices are slightly tighter (5px). The linked referral code has a dashed rectangular outline. Download arrows use circles, and Nova's background uses large circular outlines.

Thin dividers structure the flat sections. Preserve recognizable product icons; do not turn every content block into an elevated or rounded card. In forced-color mode, decorative arcs and circles are hidden and important controls gain system-color borders.

## Components

### Actions and navigation

Primary links have a solid ice blue fill, compact semibold labels, and a directional icon. They rise 3px on hover and return on press. The secondary hero link stays unfilled. The navigation download action uses a thin ice blue outline. Nova uses the same action geometry with its local white-and-cobalt colors. Links and buttons retain visible focus outlines and native activation. The selected ice blue preview choice uses a dark focus outline so its focused state stays distinguishable.

### Product preview

The Polybot preview uses native buttons for Workspace, Practice & risk, and Evidence. Each stays in the tab order, works with Enter/Space, and exposes `aria-pressed`. Controls appear only after JavaScript enables them. The 8:5 image area stays stable while the next screenshot decodes offscreen; a failure keeps the current working image and reports an error. The newest selection wins, and the image, alt text, caption, and original-image links change together.

Only the real screens in `assets/` are used. Practice shows setup; Evidence shows the initial state before settled samples. The decorative signal paths are hidden from assistive technology.

### Referral ribbon

The ROMANR code is a real link to the current Polymarket US offer, displayed within the full-width ice blue ribbon. Its adjacent reward disclosure remains readable at all sizes. Hover adds a light wash within the dashed code outline.

### Download rows and disclosures

Windows and Mac use equally prominent full-row links, separated by thin rules. Platform requirements sit beneath each name. Hover changes the row background without shifting its text. Unsigned and non-notarized status remains visible beside the downloads. Installation guidance and checksums use a native details disclosure; API keys and release notes remain ordinary links.

On phones, the share section offers the native share sheet when available, clipboard copying as a fallback, and a visible address if neither is available. Without JavaScript the address remains usable and the inactive share button is hidden.

### FAQ and image viewer

FAQ rows are native details/summary elements with a plus that rotates when open. They preserve keyboard behavior and work without JavaScript.

Both products share a native modal image viewer when supported. It has a visible title, Close and Zoom in / Fit screen controls, an initial Close focus, Escape and backdrop closing, and focus restoration. The background is inert while open. A zoomed image uses native scrolling in a keyboard-focusable region. Loading and failure messages preserve the frame, and Open image remains available. Pending loads are ignored after closing or reopening. Modified/new-tab clicks and unsupported-dialog or no-JavaScript cases keep the original image links.

## Do's and Don'ts

### Do

- Keep the website focused on ROM Polybot and ROM Nova.
- Use actual product screens with accurate, nearby state captions.
- Preserve the distinct midnight navy, ice blue, paper, and cobalt chapters.
- Keep referral terms, platform requirements, and download verification readable.
- Preserve native navigation, disclosures, keyboard focus, and image-link fallbacks.
- Keep the 320px layout usable and respect reduced-motion preferences.

### Don't

- Present decorative signal arcs as prices, performance, or live market data.
- Invent returns, customer counts, testimonials, or successful live-trading claims.
- Imply that the Practice setup screen is an active simulation or that the initial Evidence screen contains settled results.
- Add automatic screenshot cycling or continuously looping decoration.
- Hide essential download information behind JavaScript or change the independent Nova application's visual system here.
