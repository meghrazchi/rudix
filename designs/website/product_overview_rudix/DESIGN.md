---
name: Rudix Enterprise Design System
colors:
  surface: '#faf9ff'
  surface-dim: '#dad9df'
  surface-bright: '#faf9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f4f3f9'
  surface-container: '#eeedf3'
  surface-container-high: '#e8e7ed'
  surface-container-highest: '#e3e2e8'
  on-surface: '#1a1b20'
  on-surface-variant: '#464555'
  inverse-surface: '#2f3035'
  inverse-on-surface: '#f1f0f6'
  outline: '#777587'
  outline-variant: '#c7c4d8'
  surface-tint: '#4d44e3'
  primary: '#3525cd'
  on-primary: '#ffffff'
  primary-container: '#4f46e5'
  on-primary-container: '#dad7ff'
  inverse-primary: '#c3c0ff'
  secondary: '#5f5d64'
  on-secondary: '#ffffff'
  secondary-container: '#e2dee6'
  on-secondary-container: '#646169'
  tertiary: '#00542a'
  on-tertiary: '#ffffff'
  tertiary-container: '#006f3a'
  on-tertiary-container: '#8af1a8'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#e2dfff'
  primary-fixed-dim: '#c3c0ff'
  on-primary-fixed: '#0f0069'
  on-primary-fixed-variant: '#3323cc'
  secondary-fixed: '#e5e1e9'
  secondary-fixed-dim: '#c9c5cd'
  on-secondary-fixed: '#1c1b21'
  on-secondary-fixed-variant: '#47464d'
  tertiary-fixed: '#91f8ae'
  tertiary-fixed-dim: '#75db94'
  on-tertiary-fixed: '#00210d'
  on-tertiary-fixed-variant: '#005229'
  background: '#faf9ff'
  on-background: '#1a1b20'
  surface-variant: '#e3e2e8'
  enterprise-navy: '#0A0A0F'
  git-orange: '#E24329'
  success-green: '#108548'
  glass-border: rgba(255, 255, 255, 0.1)
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  display-lg-mobile:
    fontFamily: Inter
    fontSize: 36px
    fontWeight: '700'
    lineHeight: 44px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 30px
    fontWeight: '600'
    lineHeight: 38px
  headline-sm:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  code-sm:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-caps:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.05em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  base: 4px
  gutter: 24px
  margin-mobile: 16px
  margin-desktop: 40px
  max-width: 1440px
---

## Brand & Style
The design system embodies the intersection of **Infrastructure-as-Code** and **Premium Enterprise SaaS**. The brand personality is technical, reliable, and high-fidelity, designed to instill immediate trust in CTOs and DevOps Architects.

The aesthetic follows a **Modern Corporate** approach with **Glassmorphic** accents. It prioritizes clarity and structured information density, utilizing heavy whitespace and surgical precision in alignment. The visual language suggests a robust engine under a refined, high-performance exterior. It is built to handle complex RAG (Retrieval-Augmented Generation) workflows while maintaining the elegance of a top-tier productivity tool.

## Colors
The palette is anchored by **Deep Indigo**, signaling intelligence and connectivity. 

- **Primary:** Deep Indigo (#4F46E5) is used for primary actions, active states, and brand-critical indicators.
- **Surface Strategy:** While the application defaults to a clean light mode, "Enterprise Navy" (#0A0A0F) is the mandatory surface for Hero sections and sidebar navigations to establish a premium, developer-centric "IDE-plus" feel.
- **Accents:** We retain "Git-Orange" from the source for status warnings and "Success Green" for deployment confirmations, grounding the system in familiar DevOps semiotics.
- **Glassmorphism:** Overlays and floating panels should utilize a blur effect (12px-20px) with a subtle white or navy tint at 60-70% opacity.

## Typography
We utilize **Inter** for all UI elements to ensure maximum legibility across dense data tables and technical documentation. 

For technical parameters, API keys, and logs, the system integrates **JetBrains Mono** to reinforce the "Infrastructure" narrative. Headlines should use tighter letter-spacing to maintain a "locked-in" professional appearance. Body text adheres to a comfortable 1.5x line height to ensure readability during long research sessions.

## Layout & Spacing
The layout follows a **Fixed-Fluid Hybrid** model. The main content container is capped at 1440px for readability, centered on the screen. 

- **Grid:** A 12-column grid is used for marketing and dashboard views. 
- **Rhythm:** An 8px linear scale governs all padding and margins (4, 8, 16, 24, 32, 48, 64). 
- **Reflow:** On mobile, margins shrink to 16px and the 12-column grid collapses into a single-column stack. Sidebar navigation in the app transforms into a bottom-anchored sheet or a full-screen overlay to maintain technical depth accessibility.

## Elevation & Depth
Depth is communicated through **Ambient Shadows** and **Tonal Layering**. 

1.  **Base Layer:** Solid neutral surfaces (#F1F0F6).
2.  **Mid Layer:** Cards and containers use a subtle 1px border (#E2E2E9) with a very soft, diffused shadow (0px 4px 20px rgba(0,0,0,0.04)).
3.  **Top Layer:** Modals and dropdowns utilize **Glassmorphism**. High-blur (20px) backdrops with a 1px semi-transparent white stroke create a "floating glass" effect that feels premium and modern.
4.  **Diagram Elevation:** Technical RAG flow diagrams should use "Elevated Lines"—subtle 2px strokes with a soft glow effect in Primary Indigo to indicate active data paths.

## Shapes
This design system uses a **Soft (0.25rem)** shape language. This "semi-sharp" approach maintains the precision expected from an enterprise tool while avoiding the aggressive feel of 90-degree corners. 

- **Buttons & Inputs:** 4px (0.25rem) radius.
- **Cards & Modals:** 8px (0.5rem) radius.
- **Search Bars/Tags:** 24px (Pill) for high contrast against structural elements.

## Components
- **Buttons:** Primary buttons use a solid Indigo fill with white text. Secondary buttons use a ghost style with a 1px border. "Infrastructure" buttons (e.g., Deploy) may feature a subtle interior gradient.
- **Inputs:** Fields are minimal, using a light gray fill (#F8F8FA) that shifts to a white background with an Indigo border on focus. Labels are always positioned above the input in `label-caps`.
- **Chips/Status:** Used for RAG state indicators (e.g., "Indexing," "Retrieved," "Failed"). These use a "Soft Background" style—low-opacity versions of the status color with high-contrast text.
- **Technical Cards:** Cards housing JSON snippets or Vector DB stats should use a dark background (#1F1E24) even in light mode to differentiate "Data" from "Interface."
- **Diagram Nodes:** Rectangular with 4px corners, using thin connector lines with directional arrows. Active paths should be animated with a subtle "flow" pulse in Indigo.