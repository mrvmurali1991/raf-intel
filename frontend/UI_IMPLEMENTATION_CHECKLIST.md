# Healthcare Dashboard UI Implementation Checklist

## COLOR PALETTE IMPLEMENTATION

- [ ] Light mode base colors set
  - [ ] Page background: #f4f6f9
  - [ ] Card/surface: #ffffff
  - [ ] Sidebar: #343a40
  - [ ] Primary text: #212529
  - [ ] Secondary text: #6c757d
  - [ ] Borders: #dee2e6

- [ ] Dark mode colors configured
  - [ ] Page background: #121212
  - [ ] Card surface: #1e1e1e
  - [ ] Sidebar: #0d1117
  - [ ] Primary text: #e1e1e1
  - [ ] Secondary text: #8b949e
  - [ ] Borders: #30363d

- [ ] Semantic colors defined
  - [ ] Success (Green): #198754
  - [ ] Danger (Red): #dc3545
  - [ ] Warning (Amber): #ffc107
  - [ ] Info (Light Blue): #0dcaf0
  - [ ] Primary (Blue): #0d6efd

- [ ] Risk scoring colors implemented
  - [ ] Critical (Red): #dc3545
  - [ ] High (Orange): #ff6b35
  - [ ] Medium (Amber): #ffc107
  - [ ] Low (Green): #20c997
  - [ ] Baseline (Gray): #adb5bd

## TYPOGRAPHY SETUP

- [ ] Font families loaded
  - [ ] Primary (Headlines): Segoe UI or Roboto
  - [ ] Secondary (Body): Open Sans or Inter
  - [ ] Monospace: Monaco or SF Mono

- [ ] Type scale established
  - [ ] H1: 32px, 600 weight
  - [ ] H2: 24px, 600 weight
  - [ ] H3: 18px, 600 weight
  - [ ] Body Large: 16px, 400 weight
  - [ ] Body Regular: 14px, 400 weight (default)
  - [ ] Small: 12px, 400 weight
  - [ ] Label/Badge: 12px, 500 weight
  - [ ] Footnote: 11px, 400 weight

- [ ] Line heights configured
  - [ ] Headlines: 1.2
  - [ ] Body: 1.5
  - [ ] Small text: 1.4

## SPACING SYSTEM

- [ ] Spacing scale defined
  - [ ] xs: 4px
  - [ ] sm: 8px
  - [ ] md: 16px
  - [ ] lg: 24px
  - [ ] xl: 32px
  - [ ] xxl: 48px

- [ ] Component padding applied
  - [ ] Button: 12px 16px
  - [ ] Card: 24px all sides
  - [ ] Input field: 10px 12px
  - [ ] Badge: 4px 12px

- [ ] Gap/margin spacing
  - [ ] Section spacing: 24-32px
  - [ ] Component spacing: 16px
  - [ ] List item spacing: 8px
  - [ ] Page margins: 32-48px

## LAYOUT ARCHITECTURE

- [ ] Main layout grid created
  - [ ] Sidebar width: 280px (fixed)
  - [ ] Content area: Remaining width (responsive)
  - [ ] Sidebar color: #343a40 (dark)
  - [ ] Content background: #f4f6f9

- [ ] Top navigation bar
  - [ ] Height: 56-64px
  - [ ] Logo placement (left)
  - [ ] Page title (center)
  - [ ] User menu (right)
  - [ ] Background: #ffffff with bottom border

- [ ] Sidebar navigation
  - [ ] Logo at top
  - [ ] Menu items with hover states
  - [ ] Active state indicator (left border)
  - [ ] Settings/Help at bottom
  - [ ] Icons for each menu item

- [ ] Responsive breakpoints
  - [ ] Desktop (1200px+): Full sidebar visible
  - [ ] Tablet (768px-1199px): Sidebar collapsible
  - [ ] Mobile (<768px): Sidebar hidden, hamburger menu

## PATIENT LIST VIEW

### Card-Based Layout (Recommended for Responsive)
- [ ] Patient card component created
  - [ ] Height: 80-100px
  - [ ] Avatar image (left, 40px square)
  - [ ] Name + age (bold, 16px)
  - [ ] Primary condition (14px, gray)
  - [ ] Risk badge (right side, color-coded)
  - [ ] Last visit date (small, gray)
  - [ ] Hover state: #f0f4f8 background
  - [ ] Active state: #e7f0ff background + left border

- [ ] Patient list filtering
  - [ ] Filter tabs: All, High Risk, Medium, Low, New
  - [ ] Search bar with auto-suggest
  - [ ] Sort options (by risk, by name, by date)
  - [ ] Clear filters button

- [ ] Patient list scrolling
  - [ ] Virtual scrolling for 1000+ patients
  - [ ] Loading indicator at bottom
  - [ ] Empty state message

### Table-Based Layout (For Desktop/Dense Data)
- [ ] Table columns defined
  - [ ] Name (25-30% width, sortable)
  - [ ] Age (5%)
  - [ ] Risk Level (8%, color-coded)
  - [ ] Primary Condition (25-30%)
  - [ ] HCC Code (10%)
  - [ ] Last Seen (12%)
  - [ ] Actions (10%, fixed width)

- [ ] Table styling
  - [ ] Row height: 52-56px
  - [ ] Striped rows: Alternate #ffffff and #f8f9fa
  - [ ] Hover row: #f0f4f8 background
  - [ ] Selected row: #e7f0ff background + left border
  - [ ] Border: 1px solid #dee2e6

- [ ] Table interactions
  - [ ] Click row to view patient details
  - [ ] Sortable columns (click header)
  - [ ] Column resizing (drag header border)
  - [ ] Sticky header when scrolling

## PATIENT SUMMARY CARD

- [ ] Card layout structure
  - [ ] Background: #ffffff
  - [ ] Border: 1px solid #dee2e6
  - [ ] Border-radius: 4-8px
  - [ ] Padding: 24px
  - [ ] Box-shadow: 0 1px 3px rgba(0,0,0,0.08)

- [ ] Patient demographics section
  - [ ] Name, Age, MRN displayed
  - [ ] Insurance information
  - [ ] Contact method

- [ ] Overall risk score display
  - [ ] Large centered number (48px bold)
  - [ ] Risk category label
  - [ ] Color-coded background based on risk
  - [ ] Brief explanation below

- [ ] Key metrics section
  - [ ] HbA1c, BP, eGFR, etc. (varies by patient)
  - [ ] 3-month trending indicator
  - [ ] Normal range reference (small, gray)

- [ ] HCC Conditions section
  - [ ] List of 5-10 relevant HCCs
  - [ ] Condition name and code
  - [ ] Documentation status (✓, ✗, ?)
  - [ ] Weight contribution to risk
  - [ ] "View All" if 10+ conditions

- [ ] Care Gaps section
  - [ ] List of identified gaps
  - [ ] Color severity (Red, Amber, Green)
  - [ ] Action items linked
  - [ ] Schedule, Referral, Dismiss buttons

## RISK SCORE VISUALIZATION

- [ ] Risk display options implemented
  - [ ] Option 1: Circular gauge (large, centered)
  - [ ] Option 2: Horizontal bar (segments by risk zone)
  - [ ] Option 3: Badge pills (for patient lists)
  - [ ] Consistent across all views

- [ ] Risk breakdown table
  - [ ] Condition name | HCC # | Status | Weight
  - [ ] Status icons: ✓ (green), ✗ (red), ? (amber)
  - [ ] Sortable by weight
  - [ ] Click to see condition details

- [ ] Risk trend display
  - [ ] Trend arrow: ↑ (red) ↓ (green)
  - [ ] Percentage change (e.g., +0.2)
  - [ ] Time period shown (3 months, 6 months, 1 year)
  - [ ] Mini chart optional (tiny sparkline)

- [ ] Service category breakdown (Milliman pattern)
  - [ ] 8 categories listed
  - [ ] Inpatient, ED, Outpatient, Behavioral, Pharmacy, Oncology, Chronic, Complexity
  - [ ] Each with risk score and trend
  - [ ] Color-coded by severity
  - [ ] Click to drill down

## BADGE & STATUS INDICATORS

- [ ] Risk status badges
  - [ ] Height: 24-28px
  - [ ] Padding: 4px 12px
  - [ ] Border-radius: 4px (square) or 12px (pill)
  - [ ] Font: 12px, 500 weight, bold color text
  - [ ] Background: Semantic color + low opacity

- [ ] Badge variants
  - [ ] High Risk: Red background, white text
  - [ ] Medium Risk: Amber background, dark text
  - [ ] Low Risk: Green background, white text
  - [ ] Documentation Status: Green (✓), Red (✗), Amber (?)

- [ ] Icons with badges
  - [ ] Alert icon for high risk
  - [ ] Checkmark for completed/documented
  - [ ] X for gap/missing
  - [ ] Arrow for trending up/down

## VITAL SIGNS TILES

- [ ] Tile component structure
  - [ ] Width: ~150px (responsive)
  - [ ] Height: ~180px
  - [ ] Background: #ffffff
  - [ ] Border: 1px solid #dee2e6
  - [ ] Border-radius: 8px
  - [ ] Padding: 16px

- [ ] Tile content sections
  - [ ] Title bar: #f8f9fa background, 14px bold
  - [ ] Large value: 48px bold, dark text
  - [ ] Unit: 16px, secondary text
  - [ ] Trend: Arrow + value, color-coded
  - [ ] Status: Badge with status
  - [ ] Timestamp: 11px, gray, italic

- [ ] Tile colors
  - [ ] Normal: Green accent
  - [ ] Elevated: Amber accent
  - [ ] Critical: Red accent
  - [ ] Pending: Gray accent

- [ ] Tile interactions
  - [ ] Hover: Subtle shadow increase
  - [ ] Click: Open detail view
  - [ ] Tooltip: Show full context

## CHART & DATA VISUALIZATION

- [ ] Line chart (for trends)
  - [ ] Purpose: HbA1c, Weight, BP trends
  - [ ] X-axis: Monthly labels, 12-month window
  - [ ] Y-axis: Actual values, show range
  - [ ] Line color: Primary blue (#0057ff)
  - [ ] Area fill: Light blue (opacity 0.1)
  - [ ] Grid: Light gray (#e9ecef)
  - [ ] Hover: Tooltip with exact values
  - [ ] Responsive: Mobile-friendly sizing

- [ ] Bar chart (for comparisons)
  - [ ] Purpose: Service category risk scores
  - [ ] Color: Risk-based semantic colors
  - [ ] Labels: Centered above bars
  - [ ] Interactive: Click for drill-down
  - [ ] Y-axis: Risk score or percentage

- [ ] Donut/Pie chart (for compositions)
  - [ ] Purpose: Risk composition by HCC category
  - [ ] Color: Semantic colors
  - [ ] Legend: Below chart, clickable
  - [ ] Tooltip: Show percentage on hover

## BUTTONS & ACTIONS

- [ ] Primary button
  - [ ] Background: #0d6efd (blue)
  - [ ] Text: White, 14px, 500 weight
  - [ ] Padding: 10px 20px
  - [ ] Border-radius: 4px
  - [ ] Hover: Darker blue (#0b5ed7)
  - [ ] Active: Even darker (#0a58ca)
  - [ ] Disabled: Gray, reduced opacity

- [ ] Secondary button
  - [ ] Background: #f8f9fa
  - [ ] Text: #212529, 14px, 500 weight
  - [ ] Border: 1px solid #dee2e6
  - [ ] Padding: 10px 20px
  - [ ] Hover: #e9ecef background
  - [ ] Active: #dee2e6 background

- [ ] Danger button (for destructive actions)
  - [ ] Background: #dc3545 (red)
  - [ ] Text: White, 14px, 500 weight
  - [ ] Hover: Darker red (#bb2d3b)
  - [ ] Confirmation modal required

- [ ] Action buttons on cards
  - [ ] "Schedule Appointment"
  - [ ] "Send Referral"
  - [ ] "Text Campaign"
  - [ ] "View Chart"
  - [ ] Size: Compact (12px font, smaller padding)

## FORMS & INPUTS

- [ ] Text input styling
  - [ ] Height: 36-40px
  - [ ] Padding: 10px 12px
  - [ ] Border: 1px solid #dee2e6
  - [ ] Border-radius: 4px
  - [ ] Font: 14px, #212529
  - [ ] Placeholder: #6c757d (gray)
  - [ ] Focus: Blue border (#0d6efd), box-shadow
  - [ ] Disabled: #f8f9fa background, cursor not-allowed

- [ ] Dropdown/Select
  - [ ] Same dimensions as text input
  - [ ] Arrow icon (right aligned)
  - [ ] Option list: Standard menu styling
  - [ ] Selected option: Blue background

- [ ] Checkboxes & Radio buttons
  - [ ] Size: 18x18px
  - [ ] Border: 2px solid #dee2e6
  - [ ] Checked: Blue background with checkmark
  - [ ] Focus: Blue outline

- [ ] Form labels
  - [ ] Font: 14px, 500 weight
  - [ ] Color: #212529
  - [ ] Margin-bottom: 8px
  - [ ] Required indicator: Red asterisk

## ALERTS & NOTIFICATIONS

- [ ] Alert component
  - [ ] Background: Semantic color (low opacity)
  - [ ] Text: Semantic color (dark)
  - [ ] Border-left: 4px semantic color
  - [ ] Padding: 12px 16px
  - [ ] Border-radius: 4px
  - [ ] Icon: Left-aligned, semantic
  - [ ] Close button: Optional (X icon)

- [ ] Alert types
  - [ ] Success: Green (#198754)
  - [ ] Error: Red (#dc3545)
  - [ ] Warning: Amber (#ffc107)
  - [ ] Info: Blue (#0dcaf0)

- [ ] Toast notifications
  - [ ] Position: Top-right corner
  - [ ] Animation: Slide in from top
  - [ ] Auto-close: 4-5 seconds
  - [ ] Can close manually
  - [ ] Icon + message + optional action button

## ACCESSIBILITY REQUIREMENTS

- [ ] Color contrast
  - [ ] Text: 4.5:1 minimum (WCAG AA)
  - [ ] Text large (18px+): 3:1 minimum
  - [ ] UI components: 3:1 minimum
  - [ ] Recommended: 7:1 for AAA compliance

- [ ] Keyboard navigation
  - [ ] Tab order logical
  - [ ] Focus indicators visible
  - [ ] Enter to activate buttons
  - [ ] Arrow keys for lists/tables
  - [ ] Escape to close modals

- [ ] Screen reader support
  - [ ] Semantic HTML (not divs for everything)
  - [ ] ARIA labels where needed
  - [ ] Form labels associated with inputs
  - [ ] Images have alt text
  - [ ] Icons have aria-label

- [ ] Visual accessibility
  - [ ] Don't rely on color alone
  - [ ] Use icons + text for status
  - [ ] Sufficient font size (14px minimum)
  - [ ] Readable line length (50-75 characters)
  - [ ] Adequate line spacing (1.5x)

## RESPONSIVE DESIGN

- [ ] Mobile layout (< 768px)
  - [ ] Single column layout
  - [ ] Sidebar hidden (hamburger menu)
  - [ ] Full-width cards
  - [ ] Stacked patient list
  - [ ] Touch-friendly button sizes (44px minimum)

- [ ] Tablet layout (768px - 1199px)
  - [ ] Optional sidebar (can toggle)
  - [ ] 2-column patient data view
  - [ ] Responsive cards
  - [ ] Grid adjustments

- [ ] Desktop layout (1200px+)
  - [ ] Full sidebar always visible
  - [ ] Multi-panel layout available
  - [ ] Optimized spacing and sizing
  - [ ] Hover states active

## DARK MODE IMPLEMENTATION

- [ ] CSS variables for theming
  - [ ] Light mode values defined
  - [ ] Dark mode values defined
  - [ ] System preference detection
  - [ ] Toggle switch component

- [ ] Component theming
  - [ ] Cards: Light in light mode, dark in dark mode
  - [ ] Text: Dark in light mode, light in dark mode
  - [ ] Borders: Subtle in both modes
  - [ ] Shadows: Adjusted for dark mode

- [ ] Specific components
  - [ ] Sidebar: Dark in both (may not change)
  - [ ] Top nav: Light in light mode, slightly darker in dark mode
  - [ ] Patient cards: Adjust background and text
  - [ ] Charts: Adjust grid colors and text

## PERFORMANCE & OPTIMIZATION

- [ ] Image optimization
  - [ ] Avatars: Optimized, cached
  - [ ] Icons: SVG format (not raster)
  - [ ] Charts: SVG or Canvas for rendering

- [ ] Component optimization
  - [ ] Virtual scrolling for long lists (1000+ items)
  - [ ] Lazy loading for images/charts
  - [ ] Memoization of expensive components
  - [ ] Code splitting by route

- [ ] Data loading
  - [ ] Skeleton screens while loading
  - [ ] Progressive data loading
  - [ ] Pagination or infinite scroll
  - [ ] Caching strategy

## TESTING CHECKLIST

- [ ] Visual testing
  - [ ] Color contrast checker (axe DevTools)
  - [ ] Responsive design (Chrome DevTools)
  - [ ] Dark mode appearance
  - [ ] Print stylesheet

- [ ] Interaction testing
  - [ ] All buttons clickable
  - [ ] Forms submittable
  - [ ] Filters working
  - [ ] Sorting working

- [ ] Accessibility testing
  - [ ] Keyboard-only navigation
  - [ ] Screen reader testing
  - [ ] WCAG compliance check
  - [ ] Focus indicators visible

- [ ] Cross-browser testing
  - [ ] Chrome, Firefox, Safari, Edge
  - [ ] Mobile browsers (iOS Safari, Chrome Mobile)
  - [ ] Dark mode in each browser

## DESIGN SYSTEM DOCUMENTATION

- [ ] Component library documented
  - [ ] Color palette with hex codes
  - [ ] Typography scale
  - [ ] Spacing scale
  - [ ] Button variants
  - [ ] Badge styles
  - [ ] Card layouts
  - [ ] Alert styles
  - [ ] Form inputs
  - [ ] Icons library

- [ ] Usage guidelines
  - [ ] When to use each component
  - [ ] Do's and don'ts
  - [ ] Real-world examples
  - [ ] Code snippets

- [ ] Figma or Storybook setup
  - [ ] All components in design tool
  - [ ] Interactive documentation
  - [ ] Component variations
  - [ ] Code/design sync

---

## NOTES

- Color codes are hex format for CSS/Figma compatibility
- All spacing values use pixel units (convert to rem if using fluid typography)
- Consider using CSS custom properties (variables) for easier theming
- Accessibility checklist uses WCAG 2.1 Level AA as baseline
- Dark mode should be progressively enhanced, not required
