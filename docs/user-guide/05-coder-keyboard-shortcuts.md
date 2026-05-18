# Keyboard shortcuts: A / D / R + g-prefix nav

> Audience: Coder  •  Time: 5 min

Power coders work without a mouse. RAF Intelligence ships two shortcut systems: the
**single-key triage keys** (A/D/R/J/K) and the Gmail-style **g-prefix navigation**.
This tutorial gets you fluent in both and shows the cheat sheet you can pin.

## Prerequisites

- Tutorials 1–4 completed; you understand accept, decline, and reverse.
- The page focus is **not** inside a text input — shortcuts are suppressed when typing.

## Step 1 — Open the shortcut cheat sheet

Press `?` (Shift + /) anywhere in the app. A modal lists every shortcut, grouped by
section. Close it with `Esc`. The list also lives at the bottom of `/settings/profile`.

## Step 2 — Triage keys on the suspect list

Navigate to `/suspects`. The first row is highlighted with a blue left border. Try:

| Key | Action |
|---|---|
| `J` | Move highlight down one row |
| `K` | Move highlight up one row |
| `A` | Accept the highlighted suspect |
| `D` | Decline / dismiss the highlighted suspect |
| `R` | Reverse (only on already-accepted rows) |
| `Enter` | Open the suspect drawer |
| `Esc` | Close the drawer |

Workflow: `J` to scan, `Enter` to expand evidence, `A` or `D` to act, the highlight
moves to the next row automatically.

**Expected outcome:** you can clear a 20-row screen in under a minute without touching
the mouse.

## Step 3 — g-prefix navigation

Pressing `g` arms a 1-second window for a second key that jumps to a section:

| Combo | Destination |
|---|---|
| `g` then `w` | `/worklist` |
| `g` then `s` | `/suspects` |
| `g` then `p` | `/patients` |
| `g` then `r` | `/review-queue` |
| `g` then `d` | `/documents` |
| `g` then `a` | `/audit` |
| `g` then `h` | Home (role-based redirect) |

If the second key arrives after 1 second the prefix is dropped. The current armed
state shows as a small chip in the bottom-right corner.

## Step 4 — Modifier combos

A few global combos use the Cmd/Ctrl modifier and work everywhere:

| Combo | Action |
|---|---|
| `Cmd / Ctrl + K` | Open the command palette (search any page, patient, or suspect) |
| `Cmd / Ctrl + .` | Toggle the right-hand activity panel |
| `Cmd / Ctrl + /` | Focus the search box |
| `Cmd / Ctrl + Enter` | Submit the current modal (accept, dismiss, save) |

The command palette is the fastest way to jump to a specific patient ID: open it
(`Cmd K`), type `p 3`, press `Enter`, and you land on `/patients/3`.

## Step 5 — Build the muscle memory drill

Run this for 60 seconds, twice a day for a week:

1. `g w` — worklist.
2. `J J J J` — scan four rows.
3. `Enter` — open evidence.
4. `A` or `D` — act.
5. Repeat from step 2 until the screen is empty.
6. `g s` — switch to suspects, repeat.

Most coders cut their per-suspect time from ~45 s to ~12 s after a week.

## Step 6 — Disable shortcuts if needed

Some screen readers conflict with single-key shortcuts. Open
`/settings/profile/accessibility` and toggle **Single-key shortcuts**. The g-prefix nav
and modifier combos still work.

## Common pitfalls

- **Shortcuts fire while typing** — they shouldn't. If they do, your focus is on a
  button rather than the input; click into the input first.
- **`A` accepts the wrong row** — make sure the blue highlight is on the row you
  intend. Use `J`/`K` to confirm before pressing the action key.
- **`g` combos randomly fire** — you held `g` too long. The combo expects a quick tap.

## Troubleshooting

- **`?` does nothing** — your browser may be intercepting Shift+/ for search-in-page.
  Try `Cmd K` then type "shortcuts".
- **No highlight on the suspect list** — click the table once to give it focus.
- **Shortcut chip not showing** — accessibility mode is on; turn it off in profile.

## Next step

You've completed the coder track! If you also wear a clinical hat, continue with the
MD path:

[Tutorial 6 — Run your morning huddle on `/md/today`](06-md-huddle.md)
