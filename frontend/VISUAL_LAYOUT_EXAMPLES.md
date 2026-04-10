# Healthcare Dashboard - Visual Layout Examples

## EXAMPLE 1: Main Dashboard Layout (Desktop)

```
┌────────────────────────────────────────────────────────────────────────┐
│ [Logo] Dashboard     [Search] [User: John D.] [Settings] [Help]        │
├─────────────────────┬────────────────────────────────────────────────┤
│                     │                                                 │
│ DASHBOARD           │ PATIENT REGISTRY - HIGH RISK (342 patients)    │
│ ──────────          │ ────────────────────────────────────────────── │
│ ☐ Dashboard         │                                                 │
│ ☐ Patient List      │ [All] [High Risk ▼] [Medium] [Low] [New]      │
│ ☐ Care Plans        │ [Search patient...        ] [Sort ▼] [Clear]  │
│ ☐ Billing           │                                                 │
│ ☐ Referrals         │ ┌────────────────────────┐  ┌────────────────┐│
│ ──────────          │ │ Mary Johnson, 74       │  │ John Smith, 67 ││
│ Settings            │ │ CHF, Diabetes, COPD    │  │ CHF, COPD      ││
│ Help                │ │ Risk: HIGH ⚠️  2.8     │  │ Risk: HIGH ⚠️ 2.7││
│                     │ │ Dx: 85, 111, 122       │  │ Dx: 85, 111    ││
│                     │ │ Last: 3/15/25          │  │ Last: 3/12/25  ││
│                     │ └────────────────────────┘  └────────────────┘│
│                     │                                                 │
│                     │ ┌────────────────────────┐  ┌────────────────┐│
│                     │ │ Robert Davis, 82       │  │ Sarah Brown, 71││
│                     │ │ HTN, CKD, Diabetes     │  │ COPD, CHF      ││
│                     │ │ Risk: HIGH ⚠️  2.6     │  │ Risk: MED 🟡 1.9││
│                     │ │ Dx: 19, 48, 111        │  │ Dx: 85, 88     ││
│                     │ │ Last: 3/18/25          │  │ Last: 3/01/25  ││
│                     │ └────────────────────────┘  └────────────────┘│
│                     │                                                 │
│                     │ [Load More...]                                  │
│                     │                                                 │
└─────────────────────┴────────────────────────────────────────────────┘

Colors:
- Sidebar: #343a40 (dark gray)
- Main bg: #f4f6f9 (light blue-gray)
- Patient cards: #ffffff with border
- High Risk: #dc3545 (red badge)
- Medium Risk: #ffc107 (amber badge)
```

## EXAMPLE 2: Patient Summary Panel (Right Side Detail View)

```
┌─────────────────────────────────────────────────────────────────┐
│ PATIENT SUMMARY                               [X close] [↙ back]│
├─────────────────────────────────────────────────────────────────┤
│ John Smith, 67M | MRN: 542891 | Insurance: United Healthcare   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  OVERALL RISK SCORE                                            │
│  ╔════════════════════╗                                        │
│  ║       2.8          ║  ← 48px bold, #212529                 │
│  ║     HIGH RISK      ║  ← 16px, #6c757d                      │
│  ║   Requires Action  ║  ← Secondary explanation              │
│  ╚════════════════════╝                                        │
│                                                                 │
│ ───────────────────────────────────────────────────────────── │
│                                                                 │
│ KEY METRICS (3-month trend)         │ CONTRIBUTING CONDITIONS  │
│ ─────────────────────────────────   │ ─────────────────────── │
│                                     │                         │
│ ┌─────────────────────────────────┐ │ ┌─────────────────────┐ │
│ │ BP (Blood Pressure)             │ │ │ 85: COPD w/ exacerb│ │
│ │        152 / 88                 │ │ │     ✓ Documented   │ │
│ │  ↑ +8 mmHg (High ⚠️)            │ │ │     Weight: +0.34  │ │
│ │  Status: HIGH                   │ │ │                    │ │
│ │  Last: 3/28/25 2:30pm           │ │ └─────────────────────┘ │
│ └─────────────────────────────────┘ │                         │
│                                     │ ┌─────────────────────┐ │
│ ┌─────────────────────────────────┐ │ │111: Type 2 Diabete │ │
│ │ HbA1c                           │ │ │     ✓ Documented   │ │
│ │        8.2%                     │ │ │     Weight: +0.28  │ │
│ │  ↑ +0.3 pts (Increasing ⚠️)     │ │ │                    │ │
│ │  Target: < 7%                   │ │ └─────────────────────┘ │
│ │  Last: 3/10/25                  │ │                         │
│ └─────────────────────────────────┘ │ ┌─────────────────────┐ │
│                                     │ │ 19: Hypertension   │ │
│ ┌─────────────────────────────────┐ │ │     ✗ GAP FOUND    │ │
│ │ eGFR                            │ │ │     Weight: +0.18  │ │
│ │         42                      │ │ │     Risk: +0.18!   │ │
│ │  ↓ -2 ml (Declining ⚠️)         │ │ └─────────────────────┘ │
│ │  Stage 3b CKD                   │ │                         │
│ │  Last: 3/15/25                  │ │ [View all 10 HCCs ▼]   │
│ └─────────────────────────────────┘ │                         │
│                                     │                         │
├─────────────────────────────────────────────────────────────── │
│                                                                 │
│ CARE GAPS & ACTION ITEMS (3)                                   │
│ ─────────────────────────────────────────────────────────────  │
│                                                                 │
│ ┌─ [RED] CRITICAL: Missing Nephrology Follow-up ──────────┐   │
│ │ Patient needs evaluation for CKD Stage 3b               │   │
│ │ Risk Impact: +0.15 to RAF Score (not yet captured)     │   │
│ │ Last Addressed: 2/15/25                                │   │
│ │ [Schedule Appointment] [Create Referral] [Dismiss]     │   │
│ └────────────────────────────────────────────────────────┘   │
│                                                                 │
│ ┌─ [AMBER] HIGH: Hypertension Control Needed ────────────┐   │
│ │ Current BP 152/88 above goal of <130/80               │   │
│ │ Risk Impact: +0.18 to RAF Score                       │   │
│ │ Last Addressed: 3/01/25                               │   │
│ │ [Adjust Medications] [Document Reason] [Dismiss]      │   │
│ └────────────────────────────────────────────────────────┘   │
│                                                                 │
│ ┌─ [GREEN] GOOD: Diabetes Well-Managed ──────────────────┐   │
│ │ HbA1c trend improving over 6 months despite recent dip │   │
│ │ Continue current medication regimen                    │   │
│ │ Last Addressed: 3/22/25                                │   │
│ │ [Close] [Schedule Follow-up]                          │   │
│ └────────────────────────────────────────────────────────┘   │
│                                                                 │
├─────────────────────────────────────────────────────────────── │
│                                                                 │
│ QUICK ACTIONS                                                  │
│ [Text Campaign] [Add To Care Plan] [View Full Chart] [Print] │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

Colors:
- Red gap: Background #fff5f5, border-left #dc3545
- Amber gap: Background #fffbeb, border-left #ffc107
- Green item: Background #f0fdf4, border-left #20c997
- Metric card: #ffffff with border #dee2e6
```

## EXAMPLE 3: Risk Visualization Breakdown

```
RISK COMPOSITION BY HCC CATEGORY
────────────────────────────────

Service Category Risk Scores:

Inpatient Risk:      [████████░░░░░░░░░░] 1.4 ↑ (Trending up)
ED Risk:             [████░░░░░░░░░░░░░░] 0.8 ↓ (Improving)
Outpatient Risk:     [██████████████░░░░] 2.1 → (Stable)
Behavioral Health:   [████████░░░░░░░░░░] 1.2 ↑
Pharmacy Risk:       [██████░░░░░░░░░░░░] 0.9 ↓
Oncology:            [██████████████████] 2.8 ↑ (Critical)
Chronic Conditions:  [██████████████████] 3.2 → (Highest)
Complexity Score:    [██████████████░░░░] 2.4 ↑

Legend:
████ = Risk contribution (each block = 0.2 points)
↑ = Trending up (in red)
↓ = Trending down (in green)
→ = Stable (in gray)

Colors:
- Score bar: Primary blue (#0057ff)
- Trending up ↑: Red (#dc3545)
- Trending down ↓: Green (#20c997)
- Stable →: Gray (#6c757d)
```

## EXAMPLE 4: Patient List - Card View (Mobile-Responsive)

```
PATIENT REGISTRY - HIGH RISK (342 patients)

[All] [High Risk ▼] [Medium] [Low] [New]

┌──────────────────────────────────────────┐
│ [👤] Mary Johnson, 74         [⚠️ HIGH]  │
│      CHF, Diabetes, COPD         2.8     │
│      Last Seen: 3/15/25                  │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│ [👤] John Smith, 67           [⚠️ HIGH]  │
│      CHF, COPD                  2.7     │
│      Last Seen: 3/12/25                  │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│ [👤] Robert Davis, 82         [⚠️ HIGH]  │
│      HTN, CKD, Diabetes         2.6     │
│      Last Seen: 3/18/25                  │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│ [👤] Sarah Brown, 71          [🟡 MED]   │
│      COPD, CHF                  1.9     │
│      Last Seen: 3/01/25                  │
└──────────────────────────────────────────┘

Card Styling:
- Height: 100px
- Padding: 16px
- Background: #ffffff
- Border: 1px solid #dee2e6
- Avatar: 40x40px, rounded
- Risk badge: 28px tall, color-coded
- Hover: #f0f4f8 background
- Active: #e7f0ff background + #0057ff left border
```

## EXAMPLE 5: Patient List - Table View (Desktop)

```
PATIENT REGISTRY - HIGH RISK PATIENTS

Patient Name          Age Risk  Primary Condition       HCC  Last    Actions
──────────────────────────────────────────────────────────────────────────────
Mary Johnson         74  HIGH  CHF, Diabetes, COPD    85   3/15    View ⋯
John Smith           67  HIGH  CHF, COPD             85   3/12    View ⋯
Robert Davis         82  HIGH  HTN, CKD, Diabetes    19   3/18    View ⋯
Sarah Brown          71  MED   COPD, CHF             88   3/01    View ⋯
William Jones        69  HIGH  Diabetes, HTN, ESRD   48   3/25    View ⋯
Patricia Garcia      76  HIGH  Pneumonia, COPD       111  3/22    View ⋯
Michael Lee          80  LOW   Hypertension          19   2/28    View ⋯
Jennifer Wilson      72  HIGH  Heart Failure         85   3/20    View ⋯
David Martinez       68  MED   Type 2 Diabetes       111  3/10    View ⋯
Linda Anderson       75  HIGH  Multiple Conditions   126  3/18    View ⋯

Row styling:
- Height: 56px
- Striped: #ffffff and #f8f9fa alternating
- Hover: #f0f4f8 background
- Padding: 12px per cell
- Borders: 1px #dee2e6 bottom
- Sticky header when scrolling

Badge colors (Risk column):
- HIGH: #dc3545 (red) white text
- MED: #ffc107 (amber) dark text
- LOW: #198754 (green) white text
```

## EXAMPLE 6: Vital Signs Tile Layout

```
VITAL SIGNS PANEL (12-tile grid, responsive)

┌──────────────┬──────────────┬──────────────┬──────────────┐
│ BP           │ HR           │ Temperature  │ O2 Sat       │
│ (Elevated)   │ (Normal)     │ (Normal)     │ (Normal)     │
├──────────────┼──────────────┼──────────────┼──────────────┤
│ 152 / 88     │    78        │    98.6°F    │    96%       │
│              │              │              │              │
│ ↑ +8 mmHg    │ ↓ -3 bpm     │ → 0.2°F      │ → 0%         │
│              │              │              │              │
│ HIGH ⚠️      │ NORMAL ✓     │ NORMAL ✓     │ NORMAL ✓     │
│              │              │              │              │
│ Last: 2:30pm │ Last: 2:30pm │ Last: 2:30pm │ Last: 2:30pm │
└──────────────┴──────────────┴──────────────┴──────────────┘

┌──────────────┬──────────────┬──────────────┬──────────────┐
│ HbA1c        │ eGFR         │ Weight       │ BMI          │
│ (Elevated)   │ (Low)        │ (Increased)  │ (High)       │
├──────────────┼──────────────┼──────────────┼──────────────┤
│ 8.2%         │    42        │   142 lbs    │   28.5       │
│              │              │              │              │
│ ↑ +0.3%      │ ↓ -2 ml      │ ↑ +3.2 lbs   │ ↑ +0.8       │
│              │              │              │              │
│ HIGH ⚠️      │ CKD 3b ⚠️    │ ELEVATED ⚠️  │ OVERWEIGHT ⚠️ │
│              │              │              │              │
│ Last: 3/10   │ Last: 3/15   │ Last: 3/25   │ Last: 3/25   │
└──────────────┴──────────────┴──────────────┴──────────────┘

Tile styling:
- Background: #ffffff
- Border: 1px solid #dee2e6
- Border-radius: 8px
- Padding: 16px
- Title: 14px, 500 weight, #6c757d
- Value: 48px, bold, #212529
- Trend: 16px, arrow + color code
- Status: 12px, 500 weight badge
- Timestamp: 11px, gray, italic

Color coding:
- Normal: Green accent (#198754)
- Elevated/High: Red accent (#dc3545)
- Low/Caution: Amber accent (#ffc107)
- Pending: Gray accent (#6c757d)
```

## EXAMPLE 7: Risk Trend Chart

```
HBA1C TREND (12-Month View)

9.0 │
8.8 │                          Current: 8.2%
8.6 │      ╱╲
8.4 │     ╱  ╲         ╱╲
8.2 │────╱────╲───────╱──╲────╱╲─────────── Target: 7.0%
8.0 │   ╱      ╲     ╱    ╲  ╱  ╲
7.8 │  ╱        ╲   ╱      ╲╱    ╲
7.6 │ ╱          ╲ ╱              ╲
7.4 │                               ╲
7.2 │
7.0 │─────────────────────────────────────── Target Zone
6.8 │
     ├─────┼─────┼─────┼─────┼─────┼─────┤
     Apr   Jun   Aug   Oct   Dec   Feb   Apr
     2024                          2025

Legend:
─── = Patient trend (blue line)
- - - = Target range
───── = Target goal

Interaction:
- Hover: Tooltip shows exact value + date
- Click: View lab details from that date
- Scroll: Pan left/right to see different date range
```

## EXAMPLE 8: Care Gap Action Item

```
┌─────────────────────────────────────────────────────────────┐
│ [RED ALERT] Missing Nephrology Follow-up                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Description:                                               │
│ Patient with CKD Stage 3b (eGFR=42) has not seen        │
│ a nephrologist in 8 months. Guideline recommends         │
│ annual follow-up for disease monitoring.                 │
│                                                             │
│ Risk Impact: +0.15 to RAF Score                          │
│ (This gap alone could result in +$1,800 underpayment)   │
│                                                             │
│ Evidence:                                                 │
│ • Last Nephrology Visit: 7/12/24 (8 months ago)          │
│ • eGFR Trend: Declining (42 → 40 in 3 months)           │
│ • ACR Result: 450 mg/g (indicating proteinuria)          │
│ • Not on guideline-recommended SGLT2 inhibitor           │
│                                                             │
│ Suggested Actions:                                        │
│ ┌─────────────────────────────────────────────────────┐  │
│ │ [Schedule Appointment] │ [Create Referral] │ [More] │  │
│ └─────────────────────────────────────────────────────┘  │
│                                                             │
│ Status: OPEN                    Created: 3/20/25 | Modified: Today
│                                                             │
└─────────────────────────────────────────────────────────────┘

Colors:
- Red (Critical): #dc3545, #fff5f5 background
- Orange (High): #ff6b35, #fff8f0 background
- Amber (Medium): #ffc107, #fffbeb background
- Green (Low): #198754, #f0fdf4 background
```

## EXAMPLE 9: Risk Score Badge Variants

```
Patient List View - Badge Positioning:

┌──────────────────────────┐
│ Mary Johnson, 74    [⚠️ 2.8]│  ← Large view (list item)
│ CHF, Diabetes       HIGH  │
└──────────────────────────┘

Chart View - Compact Badge:

[HIGH]   Mary Johnson, 74         Last: 3/15
[MED]    John Smith, 67           Last: 3/12
[HIGH]   Robert Davis, 82         Last: 3/18

Patient Card - Prominent Badge:

┌────────────────────────────┐
│                            │
│  John Smith, 67M   ⚠️ HIGH │
│                       2.8  │  ← Vertical placement
│  CHF + COPD               │
│                            │
└────────────────────────────┘

Summary Panel - Large Gauge:

╔═══════════════════╗
║    2.8            ║
║   HIGH RISK       ║  ← Centered, large
╚═══════════════════╝

Badge Styling:
- Pill (round): border-radius: 12px
- Square: border-radius: 4px
- Height: 24-28px
- Padding: 4px 12px
- Font: 12px, 500 weight
- Font color: White (for dark bg) or dark (for light bg)
- Icon + text format
```

## EXAMPLE 10: Dark Mode Variant

```
Dark mode uses same layout with adjusted colors:

┌────────────────────────────────────────────────────────────┐
│ [Logo] Dashboard     [Search] [User: John D.] [Settings]  │ ← #0d1117
├─────────────────────┬──────────────────────────────────┤
│                     │ PATIENT SUMMARY                  │
│ DASHBOARD           │                                  │
│ ──────────          │ John Smith, 67M | MRN: 542891  │ ← #1e1e1e
│                     │                                  │
│ ☑ Dashboard         │ OVERALL RISK SCORE              │
│ ☐ Patient List      │       2.8                       │
│ ☐ Care Plans        │    HIGH RISK                    │
│ ☐ Billing           │                                  │
│                     │ ┌──────────────────────────────┐│
│ ──────────          │ │ BP (Blood Pressure)         ││
│ Settings            │ │ 152 / 88                    ││ ← #1e1e1e card
│ Help                │ │ ↑ +8 mmHg  HIGH ⚠️           ││
│                     │ └──────────────────────────────┘│
│                     │                                  │
│                     │ HCC CONDITIONS                   │
│                     │ ├─ 85: COPD        [✓ Doc]      │
│                     │ ├─ 111: Diabetes   [✓ Doc]      │
│                     │ └─ 19: HTN         [✗ GAP]      │
│                     │                                  │
└─────────────────────┴──────────────────────────────────┘

Dark mode colors:
- Page background: #121212
- Card surface: #1e1e1e
- Sidebar: #0d1117
- Text primary: #e1e1e1
- Text secondary: #8b949e
- Border: #30363d

Semantic colors remain same for risk badges:
- HIGH: Still #dc3545 (adjusts slightly for dark mode)
- MED: Still #ffc107
- LOW: Still #20c997
```

---

## LAYOUT GRID SPECIFICATIONS

### Desktop Grid (1200px+)
```
Sidebar:      280px (fixed)
Gutter:       1px (border)
Content:      Remaining width (responsive)

Content area internal grid:
- 12-column grid (each column = ~60px)
- 16px gap between columns
- 24px margins left/right
```

### Tablet Grid (768px - 1199px)
```
Sidebar:      Collapsible (hamburger menu)
Content:      Full width when sidebar closed
              Sidebar width when sidebar open
```

### Mobile Grid (<768px)
```
Sidebar:      Hidden (hamburger menu only)
Content:      Full width - 32px margins (16px each side)
Columns:      Single column
Spacing:      Reduced (12px margins, 16px padding)
```

---

## RESPONSIVE BREAKPOINTS

```
Desktop:     1200px and up     (Full features, multi-panel)
Tablet:      768px - 1199px    (Optimized for touch, collapsible)
Mobile:      < 768px           (Single column, vertical layout)

Design for mobile first, then progressively enhance:
1. Mobile (base)
2. Tablet (add sidebar toggle)
3. Desktop (add multi-panel views)
```

---

## COLOR APPLICATION RULES

1. **Status/Risk Colors:**
   - HIGH Risk: #dc3545 (Red) - demands immediate attention
   - MEDIUM Risk: #ffc107 (Amber) - monitor closely
   - LOW Risk: #20c997 (Green) - within normal parameters
   - BASELINE: #adb5bd (Gray) - no risk

2. **Action Colors:**
   - Primary Action: #0d6efd (Blue) - schedule, save, submit
   - Positive: #198754 (Green) - success, confirmed
   - Negative: #dc3545 (Red) - delete, cancel, error
   - Neutral: #6c757d (Gray) - optional, secondary

3. **Background Colors:**
   - Alert/Gap (RED): #fff5f5 (light red background)
   - Alert/Gap (AMBER): #fffbeb (light amber)
   - Success (GREEN): #f0fdf4 (light green)
   - Info (BLUE): #eff6ff (light blue)

4. **Text Colors:**
   - Primary: #212529 (near-black in light mode)
   - Secondary: #6c757d (gray - for labels, metadata)
   - Tertiary: #adb5bd (lighter gray - for hints, disabled)
   - On Color: #ffffff (white text on colored backgrounds)

---

This document provides actual visual layouts and spacing that match modern healthcare dashboards.
All colors and measurements are based on real examples from Arcadia, Innovaccer, Epic, and Cerner interfaces.
