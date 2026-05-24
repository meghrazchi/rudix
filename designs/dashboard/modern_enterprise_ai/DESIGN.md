---
name: Modern Enterprise AI
colors:
  surface: '#fcf8ff'
  surface-dim: '#dcd8e5'
  surface-bright: '#fcf8ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f5f2ff'
  surface-container: '#f0ecf9'
  surface-container-high: '#eae6f4'
  surface-container-highest: '#e4e1ee'
  on-surface: '#1b1b24'
  on-surface-variant: '#464555'
  inverse-surface: '#302f39'
  inverse-on-surface: '#f3effc'
  outline: '#777587'
  outline-variant: '#c7c4d8'
  surface-tint: '#4d44e3'
  primary: '#3525cd'
  on-primary: '#ffffff'
  primary-container: '#4f46e5'
  on-primary-container: '#dad7ff'
  inverse-primary: '#c3c0ff'
  secondary: '#505f76'
  on-secondary: '#ffffff'
  secondary-container: '#d0e1fb'
  on-secondary-container: '#54647a'
  tertiary: '#7e3000'
  on-tertiary: '#ffffff'
  tertiary-container: '#a44100'
  on-tertiary-container: '#ffd2be'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#e2dfff'
  primary-fixed-dim: '#c3c0ff'
  on-primary-fixed: '#0f0069'
  on-primary-fixed-variant: '#3323cc'
  secondary-fixed: '#d3e4fe'
  secondary-fixed-dim: '#b7c8e1'
  on-secondary-fixed: '#0b1c30'
  on-secondary-fixed-variant: '#38485d'
  tertiary-fixed: '#ffdbcc'
  tertiary-fixed-dim: '#ffb695'
  on-tertiary-fixed: '#351000'
  on-tertiary-fixed-variant: '#7b2f00'
  background: '#fcf8ff'
  on-background: '#1b1b24'
  surface-variant: '#e4e1ee'
typography:
  h1:
    fontFamily: Inter
    fontSize: 30px
    fontWeight: '600'
    lineHeight: 38px
    letterSpacing: -0.02em
  h2:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  h3:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-caps:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.05em
  mono-data:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '450'
    lineHeight: 20px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  gutter: 16px
  margin-page: 32px
---

## Brand & Style

The design system is engineered for high-performance RAG operations where precision and reliability are paramount. The brand personality is "The Expert Partner"—authoritative yet accessible, translating complex data structures into actionable insights. 

The aesthetic follows a **Modern Corporate** movement with a focus on data density and modularity. It prioritizes clarity through a limited color palette, generous use of white space on surface layers, and a systematic approach to component layout. The goal is to evoke a sense of "organized intelligence," where the UI fades into the background to let the AI-generated content and retrieval metrics take center stage.

## Colors

The palette is anchored by **Deep Indigo**, used strategically for primary calls to action and global navigation to signify intent and focus. **Slate** serves as the backbone for the interface's structural elements, providing a neutral foundation for text and iconography that doesn't compete for attention.

Functional states are clearly delineated: **Emerald** signifies successful indexing and verified data paths, **Amber** highlights low-confidence scores requiring human-in-the-loop review, and **Rose** marks critical system failures or destructive actions. The background utilizes a two-tier system: a soft **Slate-50** canvas with pure white surfaces to create a clear visual hierarchy for data containers.

## Typography

This design system utilizes **Inter** for all primary interface text, leveraging its high x-height and technical neutrality to maintain readability in data-dense environments. Headings are set with semi-bold weights and slight negative letter-spacing to create a "compact" enterprise feel.

For technical metadata, confidence scores, and RAG retrieval chunks, **JetBrains Mono** is introduced. This monospaced secondary font provides a distinct visual bridge between natural language outputs and the underlying data structures, allowing users to scan technical strings and IDs with greater precision.

## Layout & Spacing

The design system employs a **Fluid-Fixed Hybrid Grid**. The primary navigation sidebar is fixed, while the content area utilizes a fluid 12-column grid. Spacing is strictly governed by an 8px base unit to ensure a mathematical rhythm across all views.

In data-heavy views (such as document indexing tables or prompt traces), a "compact" mode is preferred, reducing vertical padding to 8px (`sm`) to maximize information density. Standard dashboards and configuration pages use 16px (`md`) or 24px (`lg`) increments to improve focus and reduce cognitive load during complex setup tasks.

## Elevation & Depth

Depth in this design system is achieved through **Tonal Layering** and subtle, diffused shadows. Surfaces are not "floating" in a void but are logically stacked:

1.  **Level 0 (Canvas):** The base `#F8FAFC` background.
2.  **Level 1 (Cards/Surfaces):** Pure white containers with a 1px `Slate-200` border. This is the primary work surface.
3.  **Level 2 (Dropdowns/Modals):** Elements that require immediate focus utilize a soft, multi-layered shadow (Y: 4px, Blur: 12px, Color: `Slate-900` at 5% opacity) to provide elevation without creating harsh visual breaks.

We avoid heavy gradients or high-opacity shadows to keep the interface feeling light and "engineered."

## Shapes

The shape language is **Soft and Precise**. A consistent 4px (0.25rem) radius is applied to standard components like buttons, input fields, and tags. This slight rounding softens the enterprise "edge" while maintaining a professional, structured appearance.

Larger containers like cards or dashboard widgets use 8px (0.5rem) to create a clear containment feel. Interactive elements never exceed these values; pill shapes are reserved exclusively for status badges (chips) to differentiate them from actionable buttons.

## Components

### Buttons
Primary buttons use the Deep Indigo background with white text. Secondary buttons use a white background with a 1px `Slate-200` border and `Slate-700` text. Ghost buttons are reserved for tertiary actions or within toolbars.

### Input Fields
Fields are white with a 1px `Slate-200` border. On focus, the border transitions to Deep Indigo with a subtle 2px outer glow of the same color at 10% opacity. Labels always sit above the field in `body-sm` semi-bold.

### Chips & Status Badges
Status indicators use a subtle background tint (10% opacity of the status color) and a dark foreground text of the same hue. For example, an "Indexed" state uses a light Emerald background with dark Emerald text.

### Data Tables
Tables are the heart of the platform. They utilize a flat header with a `Slate-50` background and `label-caps` typography. Rows use a 1px bottom border only; alternating row stripes are avoided in favor of a hover-state highlight.

### Data-Dense Components
- **Trace Logs:** Uses a monospaced font in a scrollable container with a `Slate-900` background for high-contrast code/log readability.
- **Score Cards:** Large numerical displays for "Confidence" or "Latency" metrics, using semi-bold `h2` typography with a colored top-border indicating health status.