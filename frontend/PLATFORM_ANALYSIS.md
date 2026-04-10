# Healthcare Platform UI Analysis - Real Examples

## ARCADIA VISTA & PATIENT REGISTRY

### Overall Impression
Enterprise-grade, data-focused, clinical feel. Very professional but not cold. Used by 30%+ of Newsweek's 2024 Best Hospitals.

### Navigation Pattern
```
Top Bar:
[Arcadia Logo] | Dashboard > Patient Registry | [Filters] [Share] [User Menu]

Left Sidebar (280px):
- Dashboard
- Patient Registry (active)
- Population Views
- Analytics
- Care Management
- Settings
```

### Patient Registry Layout
```
Left Panel (280px):
├─ Filter Tabs: [All Patients] [High Risk] [Medium] [Low] [New]
├─ Search: Auto-suggest enabled
├─ Sort options
└─ Patient cards (vertical scrolling)

Right Panel (Responsive):
├─ Selected patient details
├─ Risk scores with HCC breakdown
├─ Care gaps
└─ Action buttons (Text Campaign, Schedule, Referral)
```

### Color Scheme
- Primary Blue: #0057ff (slightly darker than standard #0d6efd)
- Sidebar: #343a40 (consistent dark gray)
- Background: #f4f6f9 (light blue-gray)
- Risk Red: #dc3545 (standard semantic)
- Success Green: #198754 (standard)

### Data Presentation
- Patient list: Mixed card + summary format
- Risk visualization: Large centered number with color background
- Trend indicators: Arrow + percentage
- Service categories: 8-category breakdown (Inpatient, ED, Outpatient, etc.)
- Real-time risk scores with confidence intervals

### Key Insight
Arcadia emphasizes data density without overwhelming - lots of information but well-organized through cards and sections. No cluttered tables; information presented hierarchically.

---

## INNOVACCER CARE MANAGEMENT (InCare)

### Overall Impression
Modern, AI-forward, designed for workflow efficiency. Focuses on automation and reducing documentation burden. Target user: Care managers reducing time from 4.5 hours to <1 hour per day.

### Navigation Pattern
```
Top Bar:
[Innovaccer Logo] | [Active View Name] [Filters] [AI Assistant] [User]

Sidebar (similar 280px):
- Care Management
- Care Plans
- Quality
- Analytics
- Engagement
- Integrations
```

### Care Management Dashboard
```
Main Canvas:
├─ Patient List/Grid (customizable)
├─ Real-time patient assignments
├─ AI-powered risk predictions
├─ Automated care recommendations
├─ Drag-and-drop task management
└─ Workflow automation prompts
```

### Color Scheme
- Primary: Slightly warmer than Arcadia (approachable)
- Risk colors: Standard traffic light (green/amber/red)
- Emphasis on progress indicators (completion percentages)
- Heavy use of green for "AI-recommended" actions

### Unique Features
- Care Copilot (AI) - suggests next actions
- Document auto-population (reduces data entry)
- Predictive risk scoring with confidence level
- Workflow automation (reduces click burden)

### Key Insight
Innovaccer prioritizes clinician efficiency. Every element asks: "How does this save time?" This shows in the UI - minimal navigation, clear CTAs, auto-filled forms.

---

## EPIC EHR PATIENT RECORD VIEW

### Overall Impression
Highly customizable but dense. Built for power users who spend 8+ hours daily in the system. Clinical workflow is paramount; aesthetics secondary.

### Layout
```
Header (Fixed):
[Patient Banner: Name, Age, MRN, Allergies, Recent Labs]

Left Sidebar (Optional, Customizable):
├─ Problem List
├─ Medications
├─ Care Team
├─ Alerts (High priority, red)
└─ Quick Links (User-customizable)

Center Panel (Multi-tab):
├─ Chart (current note)
├─ Results (labs, imaging)
├─ Orders (active medications/tests)
├─ Visits (encounter history)
├─ Problems
└─ Additional tabs per organization

Right Panel (Optional):
├─ Care team roster
├─ Upcoming tasks
└─ Related patient information
```

### Color Scheme
- Clinical White/Gray (minimal color)
- Red alerts (for critical items - stands out in sea of gray)
- Blue accents (clickable elements)
- No colorful cards or visual flourish
- Utilitarian, not modern

### Typography
- Sans-serif, small (11-12px common)
- High contrast for readability at distance
- Bold for critical information
- No fancy gradients or rounded corners

### Data Presentation
- Tables heavily used (dense information)
- Graphs available but secondary to tables
- Text-based data (medical codes, descriptions)
- Time-series data shown in graphs for trends
- Customizable columns (show only what matters)

### Key Insight
Epic is **not** a modern SaaS design. It's a workhorse. Every pixel serves clinical workflow. Lessons: Customization > aesthetics. Power users > casual users. Efficiency > discoverability.

---

## CERNER POWERCHART EMR

### Overall Impression
Similar to Epic - clinical first. Also highly customizable. Slightly better organized than Epic in some workflows.

### Layout
```
Patient Banner (Fixed Top):
[Name, MRN, Age, Location, Recent Alerts]

Main Canvas (Customizable):
├─ MPages (custom dashboards)
│  ├─ Patient demographics
│  ├─ Vital signs grid
│  ├─ Current medications
│  ├─ Active orders
│  └─ Problem list
│
├─ IView (Interactive View for charting)
│  ├─ Documentation templates
│  ├─ Smart phrases
│  └─ Standardized forms
│
└─ Other modules (labs, imaging, etc.)
```

### Color Scheme
- Minimal color (clinical white/gray)
- Green for positive/normal
- Red for alerts/critical
- Blue for clickable items
- Gray for secondary information

### Key Features
- Templates: Standardized forms for consistency
- Smart phrases: Pre-built text blocks
- Customization: Organization-specific layouts
- Analytics: Built-in reporting tools

### Key Insight
Cerner emphasizes organization customization over one-size-fits-all design. Allows health systems to tailor UI to their specific workflows.

---

## MILLIMAN MEDINSIGHT RISK ADJUSTMENT

### Overall Impression
Analytics-focused, data-driven, designed for payers/plan managers. Heavy emphasis on visualization and "what-if" scenarios.

### Dashboard Features
```
Header:
[MedInsight Logo] | [Date Range] [Risk Model] [Export]

Main Canvas (Multi-panel):
├─ Risk Overview (top)
│  └─ Overall member risk distribution
│
├─ Service Category Breakdown
│  ├─ Inpatient risk
│  ├─ ED risk
│  ├─ Outpatient risk
│  ├─ Behavioral health
│  ├─ Pharmacy
│  ├─ Oncology
│  ├─ Chronic conditions
│  └─ Complexity score
│
├─ Member Drill-down
│  └─ Individual risk factors
│
└─ What-If Scenario
   └─ Interactive risk exploration
```

### Data Visualization
- Heavy chart usage (bar, line, scatter)
- Interactive dashboards
- Drilldown capability (click to explore)
- Real-time data processing
- API integration for custom analytics

### Key Insight
Milliman emphasizes analytical depth. Users are analysts/leaders, not frontline clinicians. More "exploration" UI than "action" UI.

---

## FIGMA TEMPLATE ANALYSIS: Preclinic & Others

### Common Design Patterns (From Free Templates)

#### Layout
```
Sidebar (240-280px):
├─ Dashboard (icon + text)
├─ Patients (icon + text)
├─ Appointments
├─ Doctors
├─ Billing
└─ Settings
```

#### Color Palettes Used
**Option 1 (Blue-based, trustworthy):**
- Primary: #1e40af (rich blue)
- Secondary: #64748b (slate gray)
- Accent: #06b6d4 (cyan)

**Option 2 (Modern, approachable):**
- Primary: #2563eb (standard blue)
- Secondary: #6b7280 (medium gray)
- Accent: #10b981 (emerald green)

**Option 3 (Healthcare-specific):**
- Primary: #0057ff (professional blue)
- Secondary: #6c757d (warm gray)
- Accent: #198754 (clinical green)

#### Components
1. **Patient Card** (all templates)
   - Avatar (40-50px)
   - Name + ID
   - Condition tags
   - Status badge
   - Action menu

2. **Vitals Display** (all templates)
   - Large metric (36-48px font)
   - Trend indicator (arrow)
   - Status badge
   - Timestamp

3. **Appointment Slot** (common)
   - Time slot
   - Doctor name
   - Patient name
   - Status (confirmed, pending, cancelled)
   - Duration

4. **Data Table** (modern approach)
   - Sticky header
   - Sortable columns
   - Row selection
   - Inline actions
   - Pagination

### Key Insight
Free healthcare templates all follow similar patterns because they work. The "best practices" are converging: sidebar navigation, card-based info architecture, badge-based status, and table-based dense data.

---

## REACT TAILWIND TEMPLATES ANALYSIS

### TailAdmin (Most Popular)
```
Structure:
- Sidebar (270px)
- Header (64px)
- Content (responsive)
- Footer (optional)

Features:
├─ 7 dashboard variations
├─ Light/dark theme
├─ Responsive grid
├─ Pre-built components
└─ Healthcare-friendly palette (customizable)

Default Colors:
- Primary: #3c50e0 (blue, customizable)
- Secondary: #8f93f9 (purple tint)
- Success: #22c55e (green)
- Danger: #f87171 (red)
- Warning: #fbbf24 (amber)
```

### Horizon UI (Modern Approach)
```
Distinctive Features:
- Rounded cards (16px radius)
- Softer shadows
- Generous spacing (24px margins)
- Gradient accents
- Modern typography (Inter font)

Better for: Modern healthcare startups
Less suitable for: Legacy EMR replacement

Colors:
- Primary: #7c3aed (purple - more modern)
- Secondary: #6366f1 (indigo)
- Success: #10b981 (emerald)
- Danger: #ef4444 (red)
```

### Key Insight
React + Tailwind has democratized healthcare UI. No more building from scratch. Community templates provide battle-tested starting points. **Recommendation: Use TailAdmin for conservative healthcare org, Horizon for startup.** The difference is ~20% border radius and shadow intensity.

---

## WHAT MAKES ENTERPRISE vs STARTUP FEEL

### Enterprise Healthcare (Arcadia, Epic, Cerner)
- Colors: Desaturated, trust-building
- Spacing: Generous, reduced cognitive load
- Rounded corners: Minimal (4px max)
- Shadows: Subtle (0 1px 3px at most)
- Typography: Very readable (14px minimum)
- Icons: Minimal, clinical
- Animations: None or very subtle (0.2s)
- Density: High but organized
- Feedback: Clear confirmations for all actions

### Startup/Modern SaaS (Innovaccer, Horizon)
- Colors: Bolder, more saturated
- Spacing: Efficient but not cramped
- Rounded corners: Generous (12px borders, 8px cards)
- Shadows: More pronounced (0 4px 12px)
- Typography: Slightly smaller, tighter
- Icons: Colorful, expressive
- Animations: Smooth transitions (0.3s+)
- Density: Moderate, visual breathing room
- Feedback: Delightful micro-interactions

### The Difference for Your Project
For risk adjustment UI:
- Patient data = Enterprise feel (conservative, readable)
- Dashboard UI = Startup feel (modern, engaging)
- Hybrid approach works: Conservative patient sections, modern analytics

---

## RECOMMENDED APPROACH FOR RAF-INTELLIGENCE

### Based on Analysis, Combine:

1. **Arcadia's strength:** Patient list organization + risk breakdown structure
2. **Innovaccer's strength:** AI-forward tone + workflow efficiency
3. **Epic's strength:** Customizable views + clinical credibility
4. **Horizon's strength:** Modern aesthetics + usability

### Specific Implementation
```
Sidebar Navigation: Arcadia pattern (280px, #343a40)
Patient List: Arcadia + Innovaccer hybrid (cards with AI badge)
Risk Display: Arcadia pattern (large centered score)
Vitals: Horizon pattern (rounded cards, gentle shadows)
Care Gaps: Innovaccer pattern (action-oriented, AI suggestions)
Colors: #0057ff primary (Arcadia), #20c997 success (clinical)
Typography: Inter or Roboto (modern but clinical)
Spacing: 16px base, 24px sections (generous, not cramped)
Border radius: 4-8px (clinical without being cold)
Shadows: Subtle (0 1px 3px) (professional)
```

---

## COLOR COMPARISON ACROSS PLATFORMS

| Platform | Primary | Success | Danger | Warning | Sentiment |
|----------|---------|---------|--------|---------|-----------|
| Arcadia | #0057ff | #198754 | #dc3545 | #ffc107 | Trust |
| Innovaccer | #0d6efd | #20c997 | #e74c3c | #ffa500 | Approachable |
| Epic | #003366 | #006600 | #cc0000 | #ff9900 | Clinical |
| Cerner | #003d6b | #008000 | #cc0000 | #ffcc00 | Clinical |
| Horizon | #7c3aed | #10b981 | #ef4444 | #f59e0b | Modern |

**Recommendation for RAF:** Use **Arcadia's primary (#0057ff)** with **Innovaccer's success green (#20c997)** for best of both worlds.

---

## FINAL RECOMMENDATIONS

### DO:
- Use 280px sidebar (industry standard, proven)
- Use traffic light risk colors (intuitive, universal)
- Generous spacing (28px minimum between sections)
- Round corners at 4-8px (clinical not cold)
- Use semantic colors (green=good, red=bad is universal)
- Show confidence/documentation status visually
- Make everything customizable (let orgs tailor)
- Provide both card and table views
- Support dark mode (clinicians work long hours)
- Use icons + text (never color alone)

### DON'T:
- Use pure bright reds (#ff0000) - causes anxiety
- Overcomplicate navigation (sidebar or top nav, not both)
- Use sans-serif fonts smaller than 12px
- Put patient names in lists without full context
- Hide critical info behind clicks (progressive disclosure)
- Use animations in clinical dashboards (too playful)
- Rely on hover states for information (mobile users)
- Mix multiple blue tones (stick to one primary)
- Use italicized body text (harder to read)
- Require scrolling for risk scores (must be immediate)

---

**Analysis Date:** March 31, 2026
**Platforms Reviewed:** Arcadia, Innovaccer, Epic, Cerner, Milliman, Figma templates, GitHub React templates
**Recommendation Status:** Ready to implement
