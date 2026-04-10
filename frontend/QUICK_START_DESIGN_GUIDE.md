# Healthcare Dashboard Design - Quick Start Guide

## TL;DR - Copy These Exact Values

### Color Palette (Paste into your CSS variables)
```css
:root {
  /* Light Mode */
  --bg-page: #f4f6f9;
  --bg-card: #ffffff;
  --bg-sidebar: #343a40;
  --text-primary: #212529;
  --text-secondary: #6c757d;
  --border: #dee2e6;

  /* Dark Mode */
  --dark-bg-page: #121212;
  --dark-bg-card: #1e1e1e;
  --dark-bg-sidebar: #0d1117;
  --dark-text-primary: #e1e1e1;
  --dark-text-secondary: #8b949e;
  --dark-border: #30363d;

  /* Semantic Colors */
  --color-success: #198754;
  --color-danger: #dc3545;
  --color-warning: #ffc107;
  --color-info: #0dcaf0;
  --color-primary: #0d6efd;

  /* Risk Scores */
  --risk-critical: #dc3545;  /* RED */
  --risk-high: #ff6b35;      /* ORANGE */
  --risk-medium: #ffc107;    /* AMBER */
  --risk-low: #20c997;       /* GREEN */
  --risk-baseline: #adb5bd;  /* GRAY */
}
```

### Typography (Font sizes in px)
```css
h1 { font-size: 32px; font-weight: 600; }
h2 { font-size: 24px; font-weight: 600; }
h3 { font-size: 18px; font-weight: 600; }
.large { font-size: 16px; font-weight: 400; }
body { font-size: 14px; font-weight: 400; }  /* DEFAULT */
.small { font-size: 12px; font-weight: 400; }
.label { font-size: 12px; font-weight: 500; }
.footnote { font-size: 11px; font-weight: 400; }
```

### Spacing Scale (Use these values)
```css
--space-xs: 4px;
--space-sm: 8px;
--space-md: 16px;
--space-lg: 24px;
--space-xl: 32px;
--space-xxl: 48px;
```

---

## Layout Architecture (Fastest Setup)

### Sidebar + Content Layout
```html
<body style="display: flex; height: 100vh;">
  <!-- Sidebar: 280px fixed, dark #343a40 -->
  <aside style="width: 280px; background: #343a40; color: white;">
    <!-- Logo, Menu, Settings -->
  </aside>

  <!-- Content: Flex, light #f4f6f9 -->
  <main style="flex: 1; background: #f4f6f9; overflow-y: auto;">
    <!-- Header: 56-64px, navigation -->
    <!-- Content: Cards, panels, patient list -->
  </main>
</body>
```

### Responsive: Hide sidebar on mobile
```css
@media (max-width: 768px) {
  aside { position: absolute; left: -280px; transition: left 0.3s; }
  aside.open { left: 0; }
}
```

---

## Patient Card Component (Copy This)

```html
<!-- Patient List Item / Card -->
<div class="patient-card">
  <img src="avatar.jpg" alt="Patient" class="patient-avatar">
  <div class="patient-info">
    <h3 class="patient-name">Mary Johnson, 74</h3>
    <p class="patient-condition">CHF, Diabetes, COPD</p>
    <span class="patient-date">Last: 3/15/25</span>
  </div>
  <span class="risk-badge risk-high">
    <span class="badge-icon">⚠️</span>
    <span class="badge-value">2.8</span>
  </span>
</div>
```

```css
.patient-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  background: #ffffff;
  border: 1px solid #dee2e6;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  height: 100px;
}

.patient-card:hover {
  background: #f0f4f8;
}

.patient-card.active {
  background: #e7f0ff;
  border-left: 4px solid #0057ff;
}

.patient-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
}

.patient-info {
  flex: 1;
}

.patient-name {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #212529;
}

.patient-condition {
  margin: 4px 0;
  font-size: 14px;
  color: #6c757d;
}

.patient-date {
  font-size: 11px;
  color: #6c757d;
}

.risk-badge {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 4px 12px;
  border-radius: 6px;
  font-weight: 600;
  font-size: 14px;
}

.risk-high {
  background: #fff5f5;
  color: #dc3545;
  border: 1px solid #f5c2c7;
}
```

---

## Risk Score Display (Copy This)

```html
<!-- Large Risk Score -->
<div class="risk-score-display risk-high">
  <div class="risk-value">2.8</div>
  <div class="risk-label">HIGH RISK</div>
  <div class="risk-explanation">Requires Action</div>
</div>
```

```css
.risk-score-display {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 140px;
  height: 140px;
  border-radius: 12px;
  padding: 20px;
  font-weight: 600;
}

.risk-score-display.risk-high {
  background: #fff5f5;
  border: 2px solid #dc3545;
  color: #dc3545;
}

.risk-score-display.risk-medium {
  background: #fffbeb;
  border: 2px solid #ffc107;
  color: #ffc107;
}

.risk-score-display.risk-low {
  background: #f0fdf4;
  border: 2px solid #20c997;
  color: #20c997;
}

.risk-value {
  font-size: 48px;
  line-height: 1;
  margin-bottom: 8px;
}

.risk-label {
  font-size: 14px;
  margin-bottom: 2px;
}

.risk-explanation {
  font-size: 12px;
  opacity: 0.8;
}
```

---

## Vital Signs Tile (Copy This)

```html
<div class="vital-tile vital-high">
  <div class="vital-title">BP (Blood Pressure)</div>
  <div class="vital-value">152 / 88</div>
  <div class="vital-trend trend-up">↑ +8 mmHg</div>
  <div class="vital-status">HIGH</div>
  <div class="vital-timestamp">Last: 2:30pm</div>
</div>
```

```css
.vital-tile {
  background: #ffffff;
  border: 1px solid #dee2e6;
  border-radius: 8px;
  padding: 16px;
  text-align: center;
  flex: 0 0 calc(25% - 12px);
  min-width: 120px;
}

.vital-title {
  font-size: 14px;
  color: #6c757d;
  margin-bottom: 8px;
  font-weight: 500;
}

.vital-value {
  font-size: 36px;
  font-weight: 600;
  color: #212529;
  margin: 12px 0;
  font-family: monospace;
}

.vital-trend {
  font-size: 14px;
  margin-bottom: 8px;
  font-weight: 500;
}

.trend-up {
  color: #dc3545;
}

.trend-down {
  color: #198754;
}

.vital-status {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  margin: 8px 0;
}

.vital-tile.vital-high .vital-status {
  background: #fff5f5;
  color: #dc3545;
}

.vital-tile.vital-normal .vital-status {
  background: #f0fdf4;
  color: #20c997;
}

.vital-timestamp {
  font-size: 11px;
  color: #6c757d;
  margin-top: 8px;
  font-style: italic;
}
```

---

## Badge/Pill Component (Copy This)

```html
<!-- Risk Status Badge -->
<span class="badge badge-high">⚠️ HIGH RISK</span>
<span class="badge badge-medium">🟡 MEDIUM</span>
<span class="badge badge-low">✓ LOW RISK</span>

<!-- Documentation Status Badge -->
<span class="badge badge-documented">✓ Documented</span>
<span class="badge badge-gap">✗ Gap</span>
<span class="badge badge-pending">? Pending</span>
```

```css
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.badge-high {
  background: #fff5f5;
  color: #dc3545;
  border: 1px solid #f5c2c7;
}

.badge-medium {
  background: #fffbeb;
  color: #ffc107;
  border: 1px solid #ffe69c;
}

.badge-low {
  background: #f0fdf4;
  color: #20c997;
  border: 1px solid #d1fae5;
}

.badge-documented {
  background: #f0fdf4;
  color: #20c997;
}

.badge-gap {
  background: #fff5f5;
  color: #dc3545;
}

.badge-pending {
  background: #fffbeb;
  color: #ffc107;
}
```

---

## Care Gap Alert Card (Copy This)

```html
<div class="care-gap-card gap-critical">
  <div class="gap-header">
    <span class="gap-icon">⚠️</span>
    <h3 class="gap-title">Missing Nephrology Follow-up</h3>
  </div>
  <p class="gap-description">
    Patient needs evaluation for CKD Stage 3b
  </p>
  <div class="gap-impact">
    Risk Impact: +0.15 to RAF Score
  </div>
  <div class="gap-actions">
    <button class="btn btn-primary">Schedule Appointment</button>
    <button class="btn btn-secondary">Create Referral</button>
  </div>
</div>
```

```css
.care-gap-card {
  background: #ffffff;
  border-left: 4px solid;
  border-radius: 4px;
  padding: 16px;
  margin-bottom: 16px;
}

.care-gap-card.gap-critical {
  border-left-color: #dc3545;
  background: #fff5f5;
}

.care-gap-card.gap-high {
  border-left-color: #ff6b35;
  background: #fff8f0;
}

.care-gap-card.gap-medium {
  border-left-color: #ffc107;
  background: #fffbeb;
}

.gap-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.gap-icon {
  font-size: 20px;
}

.gap-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #212529;
}

.gap-description {
  margin: 8px 0;
  font-size: 14px;
  color: #6c757d;
}

.gap-impact {
  margin: 8px 0;
  font-size: 12px;
  font-weight: 600;
  color: #dc3545;
}

.gap-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
```

---

## Button Styles (Copy This)

```html
<button class="btn btn-primary">Primary Action</button>
<button class="btn btn-secondary">Secondary</button>
<button class="btn btn-danger">Delete</button>
<button class="btn btn-small">Small Button</button>
```

```css
.btn {
  padding: 10px 20px;
  border: none;
  border-radius: 4px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary {
  background: #0d6efd;
  color: white;
}

.btn-primary:hover {
  background: #0b5ed7;
}

.btn-primary:active {
  background: #0a58ca;
}

.btn-secondary {
  background: #f8f9fa;
  color: #212529;
  border: 1px solid #dee2e6;
}

.btn-secondary:hover {
  background: #e9ecef;
}

.btn-danger {
  background: #dc3545;
  color: white;
}

.btn-danger:hover {
  background: #bb2d3b;
}

.btn-small {
  padding: 6px 12px;
  font-size: 12px;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

---

## Table Styling (Copy This)

```html
<table class="data-table">
  <thead>
    <tr>
      <th>Patient Name</th>
      <th>Age</th>
      <th>Risk</th>
      <th>Actions</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Mary Johnson</td>
      <td>74</td>
      <td><span class="badge badge-high">HIGH</span></td>
      <td><button class="btn btn-small">View</button></td>
    </tr>
    <tr class="striped">
      <td>John Smith</td>
      <td>67</td>
      <td><span class="badge badge-high">HIGH</span></td>
      <td><button class="btn btn-small">View</button></td>
    </tr>
  </tbody>
</table>
```

```css
.data-table {
  width: 100%;
  border-collapse: collapse;
  background: #ffffff;
  border: 1px solid #dee2e6;
  border-radius: 4px;
  overflow: hidden;
}

.data-table thead {
  background: #f8f9fa;
  border-bottom: 2px solid #dee2e6;
}

.data-table th {
  padding: 12px 16px;
  text-align: left;
  font-weight: 600;
  font-size: 14px;
  color: #212529;
}

.data-table td {
  padding: 12px 16px;
  border-bottom: 1px solid #dee2e6;
  font-size: 14px;
  color: #212529;
}

.data-table tbody tr:hover {
  background: #f0f4f8;
}

.data-table tbody tr.striped {
  background: #f8f9fa;
}

.data-table tbody tr.striped:hover {
  background: #f0f4f8;
}
```

---

## Quick Implementation Order

1. **Colors First** - Define CSS variables (5 min)
2. **Layout** - Sidebar + content grid (10 min)
3. **Patient List** - Card component (15 min)
4. **Risk Score** - Display component (10 min)
5. **Patient Summary** - Panel layout (20 min)
6. **Vital Signs** - Tile grid (15 min)
7. **Care Gaps** - Alert cards (10 min)
8. **Buttons & Forms** - Interactive elements (15 min)
9. **Table** - If needed for dense view (15 min)
10. **Dark Mode** - Toggle CSS variables (10 min)

**Total: ~2 hours for a working MVP dashboard**

---

## Testing Checklist

- [ ] Colors render correctly (check each color code)
- [ ] Typography sizes are readable (especially 14px body text)
- [ ] Spacing looks balanced (no cramped elements)
- [ ] Sidebar width is 280px on desktop
- [ ] Patient cards are 100px tall
- [ ] Risk badges are color-coded
- [ ] Buttons are clickable and have hover states
- [ ] Mobile view collapses sidebar (< 768px)
- [ ] Dark mode variables work
- [ ] Contrast passes WCAG AA (4.5:1)

---

## Files in This Project

1. **HEALTHCARE_UI_DESIGN_REFERENCE.md** - Complete design system (comprehensive)
2. **UI_IMPLEMENTATION_CHECKLIST.md** - Detailed checklist (validation)
3. **VISUAL_LAYOUT_EXAMPLES.md** - ASCII mockups (visualization)
4. **QUICK_START_DESIGN_GUIDE.md** - THIS FILE (quick reference)

Use this file for rapid prototyping. Reference the full guide when you need comprehensive details.

---

**Last Updated:** March 31, 2026
**Based on:** Real healthcare SaaS platforms (Arcadia, Innovaccer, Epic, Cerner)
**Status:** Production-ready color codes and layouts
