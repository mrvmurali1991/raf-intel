# Get oriented in RAF Intelligence as a coder

> Audience: Coder  •  Time: 5 min

This tutorial walks you through your first login, the left sidebar, and the four pages
you will use every day. By the end you will know where suspects live, where evidence
lives, and how to find your queue.

## Prerequisites

- A coder account (or the demo `admin@raf.health` / `Admin@123` shared admin login).
- The web app reachable at `http://localhost:3000` (or your tenant URL).
- Backend running on `http://localhost:8500` — confirm with:

```bash
curl -s http://localhost:8500/health
# Expected output: {"status":"ok","time":"..."}
```

## Step 1 — Log in

Open `http://localhost:3000/login`. Enter `admin@raf.health` and `Admin@123`. Press
**Sign in**.

You will land on `/` which redirects to the role-appropriate home — for a coder this is
the worklist. The session uses a short-lived access JWT and a longer refresh JWT stored
in an HTTP-only cookie. Don't worry about that yet — see Tutorial 14 for the gory
details.

**Expected outcome:** the URL becomes `/worklist` and you see a top bar with your name
and a sidebar on the left.

## Step 2 — Tour the sidebar

The sidebar groups pages by job-to-be-done. As a coder you will live in the top five
items:

| Item | Path | What it does |
|---|---|---|
| Worklist | `/worklist` | Your personal queue of items assigned by the auto-router |
| Suspects | `/suspects` | All open AI-surfaced HCC suspects across patients |
| Patients | `/patients` | Search and open any patient chart |
| Review Queue | `/review-queue` | Items returned to you for more information |
| Documents | `/documents` | Charts, progress notes, and attachments |

The lower half of the sidebar (Reports, RAF Calculate, Submissions, Settings) is mostly
read-only for coders. Admins use them daily — see the admin tutorials.

## Step 3 — Open your worklist

Click **Worklist**. You see a table with columns: Patient, Suspect HCC, Confidence,
Source, Status, Assigned at. The list comes from `GET /api/worklist`. Try it directly:

```bash
TOKEN=$(curl -s -X POST http://localhost:8500/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@raf.health","password":"Admin@123"}' | jq -r .access_token)

curl -s "http://localhost:8500/api/worklist?limit=5" \
  -H "Authorization: Bearer $TOKEN" | jq '.items[0]'
```

You should see a single worklist item JSON with `patient_id`, `suspect_hcc_code`,
`confidence`, and `status: "queued"`.

## Step 4 — Open a patient chart

In the worklist, click the **patient name** for any row (patient 3 if you can find it).
You arrive at `/patients/3`. The patient chart has:

- A hero strip with name, DOB, MA plan, and current RAF.
- Tabs: **Suspects**, **MEAT**, **Documents**, **Claims**, **Activity**.
- A right-side panel showing recent activity from
  `GET /api/patients/3/activity`.

You won't touch anything yet — Tutorial 2 will walk through accepting a suspect from
this page.

## Step 5 — Find the Suspects page

Click **Suspects** in the sidebar. This is the cross-patient view, sorted by
confidence and dollar impact. Each row is one suspect from
`GET /api/suspects/{pid}` (the page fans out across patients on the backend).

## Troubleshooting

- **Blank page after login** — check that the backend is reachable. The frontend reads
  `NEXT_PUBLIC_API_URL`. If empty, it will silently fail.
- **"401 Unauthorized" in the network tab** — your refresh cookie expired. Log out and
  back in.
- **No worklist items** — the demo seed assigns items to the user it creates. If you
  logged in as a brand-new account it will be empty; switch to `admin@raf.health`.

## Next step

You now know where things live. In the next tutorial you will accept your first HCC
suspect end-to-end:

[Tutorial 2 — Accept your first HCC suspect](02-coder-first-suspect.md)
