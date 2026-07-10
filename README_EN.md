<h1 align="center">🎭 HEYOU</h1>

<p align="center"><a href="README.md">中文</a> | <b>English</b></p>

<p align="center"><b>Bar regulars · Scan your face, get a personalized AI cartoon figurine · Printed on the spot</b></p>

<p align="center">
  <img src="https://img.shields.io/badge/Stage-MVP_Validated-50C878" alt="Stage">
  <img src="https://img.shields.io/badge/Architecture-Edge_+_Cloud-4A90E2" alt="Architecture">
  <img src="https://img.shields.io/badge/Face_Recognition-InsightFace_ArcFace-EA4C89" alt="Recognition">
  <img src="https://img.shields.io/badge/Generation-RunningHub_ComfyUI-9B59B6" alt="Generation">
  <img src="https://img.shields.io/badge/Platform-macOS_Python_3.11-50C878" alt="Platform">
</p>

When a regular walks in, the camera recognizes them and the system instantly generates a personalized cartoon figurine that's **unmistakably them — yet different every time**, then **prints it on the spot** as a keepsake to take home.

In short: turn a **face-scan** into a personalized, scarce, take-home, share-worthy surprise gift — a **memorable, shareable** differentiator for brick-and-mortar venues.

```text
Customer arrives  →  📷 Recognize regular  →  🗓 Once per day  →  🎨 Cloud-generate personalized cartoon (same identity · never repeats)  →  🖨 Print keepsake on the spot
```

> 📖 **Reading guide** — Owners: [What it delivers](#-what-it-delivers-for-your-venue) · [Quick Start](#-quick-start) · [How to Use](#-how-to-use) · [FAQ](#-faq). Investors: [Value & Moat](#-business-value--moat) · [Roadmap](#-roadmap).

<!-- Tip: drop a console screenshot / a face-scan→print demo GIF here — most compelling -->

## 📋 Recent Updates

- ✅ **2026-07-10** **Windows PixCut real printing works**: the `pixcut` backend is now **cross-platform** — Windows can also drive the official Liene app for real output (AI figurine sticker filled to 4×7 paper and die-cut), completing the fully-automated recognize → generate → print loop. It's a **hybrid driver**: the official app is a Flutter shell + WebView2 web hybrid where synthesized mouse/keyboard is ignored by the web but works on Flutter — so the home web page is clicked via the **Chrome DevTools Protocol (CDP)** and the Flutter editor via **SendInput** pixel clicks; upload goes through the native file dialog, sizing via the "Advanced (mm)" fields to fill the sheet, the cut preview is awaited by polling, and it returns home after each print. Driver: `pixcut-probe/pixcut_win.py`; details in [docs/WINDOWS.md](docs/WINDOWS.md).
- ✅ **2026-06-29** **Windows 10 support**: one cross-platform codebase; the print backend is chosen by OS — Windows can use the system printer (`win32print`) or the PixCut UI-automation; the camera uses DirectShow on Windows. See [docs/WINDOWS.md](docs/WINDOWS.md).
- ✅ **2026-06-23** Printing upgraded to the **Liene PixCut S1 cut-printer**: real printing by driving the official app, with **AI die-cut** (sticker cut along the subject's contour) or plain full-bleed printing, switchable in config; the print backend toggles between `lp` (system CUPS printer) and `pixcut` (PixCut S1). Added a **debug mode** (runs the whole print flow but never clicks "Cut" — no print, no ribbon, logs success) and **continuous-print self-healing** (restart the print app every N prints to clear accumulated canvases / avoid tab buildup).
- ✅ **2026-06-23** Log hygiene: service logs now **rotate by size** into `data/logs/` (default 5MB×5 ≈ 25MB cap, oldest auto-deleted) plus an age-based prune on startup — **so long runs never fill the disk**; the print path also cleans up the print app's own accumulated logs.
- ✅ **2026-06-05** "Standing figurine" template fix: removed stray shoes, force full-body output with a built-in round base, and added exclude-tags to the auto-tagger (blocking "half-body / held-object" tags from polluting the template) — fixing the "half-body output, stray props" issue.
- ✅ **2026-06-04** New "Cross-legged" pose template: a precise pose tag (`indian style`) controls the seated pose; the base is rendered as part of the 3D output — no external overlay image needed.
- ✅ **2026-06-03** Console upgrades: paginated regulars management, generation history (configurable retention), a "Generate / Regenerate" state button, and a **manual-print fallback**.
- ✅ **2026-06-02** Dark "nightclub" demo console launched; face recognition auto-starts/stops with the server and auto-releases the camera during enrollment (avoiding conflicts).
- ✅ **2026-06-01** Cloud pipeline live end-to-end on RunningHub (upload → create task → inject portrait + random seed → poll → download, ≈2.3 min per image); fixed Cute You 2's implicit wiring so it runs reliably via API.
- ✅ **Late May 2026** Phase 1 face-recognition loop: InsightFace detection + ArcFace embeddings, cosine matching, daily dedup.

## 🎯 What It Delivers for Your Venue

| Pain point | How HEYOU solves it |
| --- | --- |
| Homogeneous experience, nothing memorable | A **personalized cartoon** that's unmistakably them and one-of-a-kind — perfect for photos and social check-ins |
| No hook to bring regulars back | A **regulars-only, once-a-day** scarce gift that builds a "come back for today's drop" habit |
| Campaigns are hard and costly to run | Enroll once, then **auto-recognize and auto-generate** — zero staff effort, zero learning curve |
| Online spread is hit-or-miss | A take-home physical card = a **social-sharing vehicle** that carries your brand (branded card template on the roadmap) |

**For staff**: enroll a regular's photo once; everything after is automatic — with a "manual reprint" fallback when things get busy.
**For owners**: runs on an ordinary Mac + a camera + a printer, with heavy compute in the cloud — **launch and validate with minimal investment**.

## ✨ Highlights

- ✅ **Recognizes regulars** — InsightFace (SCRFD detection + ArcFace embeddings) + cosine matching; tunable threshold, "**better to miss than to misidentify**".
- ✅ **Same identity · never the same twice** — PuLID + InstantID lock the facial features (**unmistakably them**); a random seed makes **every render different** — no duplicates.
- ✅ **Multiple pose templates** — "Standing figurine" and "Cross-legged" already supported, each with a display base; templates are extensible.
- ✅ **Once per person per day** — automatic dedup; controls cost and creates scarcity (count configurable).
- ✅ **Owner console (dark nightclub style)** — enroll / paginated management / generation history / one-click regenerate / **manual-print fallback** / live status.
- ✅ **Async generation, never blocks** — each ≈2.3 min cloud render is handled by a dedicated worker, **never blocking the camera loop**; in-flight & same-day guards.
- ✅ **Edge + Cloud architecture** — the local Mac only runs recognition and scheduling; heavy generation lives in the cloud — **flexible, controllable compute cost**.
- ✅ **Pluggable generation backend** — switch between `mock` (offline self-test, free) and `runninghub` (real generation) in one setting.
- ✅ **Real printing · die-cut stickers** — supports the **Liene PixCut S1 cut-printer** (drives the official app, AI die-cut along the subject's contour) and system CUPS printers, switchable in one setting; includes a **debug mode** (runs the full flow without printing / consuming ribbon) and continuous-print self-healing.
- ✅ **Status at a glance** — three top indicators: Recognition (one-click toggle) / Engine (cloud connectivity) / Printer (connected & ready; the PixCut backend shows whether the official app is online).

## 📊 How It Works

<img src="static/images/ChatGPT_Image_202601_51_23.png" alt="How it works"/>

A four-step loop: **recognize → daily dedup → identity-consistent + random generation → print on the spot.** Every step is configurable and swappable (recognition threshold, generation template, print toggle).

## 🖼 Examples

> A plain front-facing photo in, an "unmistakably them, with a base" cartoon figurine out.

<table>
<tr>
<td width="50%" align="center"><b>Real Photo (input)</b><br/><sub>enrolled regular's portrait</sub></td>
<td width="50%" align="center"><b>Personalized Cartoon Figurine (output)</b><br/><sub>same identity · random every time</sub></td>
</tr>
<tr>
<td align="center"><img src="static/images/request-001.jpg" alt="input portrait"/></td>
<td align="center"><img src="static/images/result-001.png" alt="cartoon output"/></td>
</tr>
</table>

<table>
<tr>
<td width="50%" align="center">🧍 <b>Standing template</b><br/><sub>full body + round display base</sub><br/><img src="static/images/10_282773838.png" alt="standing figurine"/></td>
<td width="50%" align="center">🧘 <b>Cross-legged template</b><br/><sub>seated pose + integrated base</sub><br/><img src="static/images/result-002.png" alt="cross-legged figurine"/></td>
</tr>
</table>

## 🚀 Quick Start

```bash
# 1) Install dependencies (auto-creates .venv, Python 3.11)
uv sync

# 2) Start the demo console (also auto-starts face recognition)
uv run python scripts/run_server.py
#    → opens http://127.0.0.1:8000

# (optional) self-check before going live: recognition / DB / generation backend
uv run python scripts/smoke_test.py
```

After launch: enroll regulars' photos on the **Enroll** tab → recognition triggers automatically when they arrive → view results, regenerate, or manually print on the **Regulars** tab.

> 🪟 **Windows 10**: the same codebase runs on Windows (printing via the system printer *or* the PixCut die-cut UI-automation, camera via DirectShow) — see **[docs/WINDOWS.md](docs/WINDOWS.md)** for setup and printer configuration.

## ⚙️ Configuration

Global configuration lives in `config.yaml`.

| Key | Description |
| --- | --- |
| `generation.backend` | `mock` (offline self-test, free) \| `runninghub` (real cloud generation) |
| `generation.runninghub.workflow_id` | which workflow (standing / cross-legged use different IDs) |
| `recognition.match_threshold` | cosine similarity threshold; higher = stricter (better to miss than to misidentify) |
| `orchestration.daily_limit` | max generations per person per day (default `1`) |
| `storage.history_retention_days` | days to keep generation history (default `3`) |
| `printing.enabled` | auto-print toggle (currently `false`; manual print as fallback, enable once hardware is finalized) |
| `printing.backend` | print backend: `system` (cross-platform OS printer: CUPS on mac/Linux, win32print on Windows) \| `pixcut` (drives the official app for die-cut stickers, **mac + Windows**) |
| `printing.pixcut.cutout` | PixCut: apply **AI die-cut** each print (sticker cut along the contour; consumes a die-cut credit) |
| `printing.pixcut.dry_run` | PixCut **debug mode**: run the whole flow but never click "Cut" — no print, no ribbon, logs success |
| `printing.pixcut.restart_every` | PixCut: restart the app every N prints to clear accumulated canvases (default `10`, `0` = off) |
| `logging.max_bytes` · `backup_count` | service-log rotation size · kept rotations (default `5MB × 5` ≈ 25MB hard cap) |
| `logging.retention_days` | prune logs older than N days on startup (default `7`, `0` = off) |

## 💻 How to Use

The console has two tabs — **Enroll** and **Regulars** — with three live status indicators on top.

### Top status indicators
- **Recognition** — online / paused / off (click to toggle)
- **Engine** — RunningHub cloud connectivity
- **Printer** — connected and ready or not

### Enroll (add a regular)
- Supports **drag-and-drop / click-to-upload / live capture** (capturing auto-pauses recognition to release the camera)
- The system auto-detects the face, extracts embeddings, and stores them; one clear front-facing photo is enough

### Regulars (day-to-day operations)
- **Paginated list**, each regular showing their portrait; those generated today also show the latest cartoon
- **State button**: not generated today → `Generate`; already generated → `Regenerate`; in progress → disabled
- **Manual print**: a fallback when auto-print fails — reprint the latest output with one click
- **Generation history**: view the last N days (retention configurable)
- **Delete**: remove a regular and their portrait

### Customer arrives (fully automatic)
No staff action needed: recognition detects the regular → if not yet generated today, it auto-queues generation → (once auto-print is enabled) it prints automatically.

## ❓ FAQ

**Q: What about non-regulars (strangers)?**
A: Only **enrolled regulars** trigger it; strangers are ignored — nothing is generated or printed.

**Q: Why only once per day per person?**
A: It controls cloud cost and creates an "exclusive scarcity" that encourages return visits. The count is configurable in `config.yaml`.

**Q: How close is the likeness?**
A: InstantID + PuLID lock the facial features — **unmistakably them**; a random seed varies the pose and details each time — **same identity, never a repeat**.

**Q: Could it misidentify someone?**
A: It uses a high threshold and a "better to miss than to misidentify" policy; tune via `match_threshold`.

**Q: How is privacy handled?**
A: Face **embeddings** and portraits are stored **locally** in SQLite and never leave the machine; only the portrait is sent to RunningHub at generation time.

**Q: Roughly how much does it cost?**
A: Local recognition is free; each generation consumes RunningHub paid credits, capped at one per person per day — overall controllable. Use the `mock` backend for zero-cost self-testing.

**Q: Any printer requirements?**
A: Two backends, switched via `printing.backend` in `config.yaml`: `lp` uses a system CUPS printer (any system printer); `pixcut` drives the **Liene PixCut S1 cut-printer**'s official app, supporting **AI die-cut** stickers (cut along the subject's contour). To validate the whole chain without consuming ribbon, use `printing.pixcut.dry_run` (runs the full flow but doesn't really print). Auto-print (`printing.enabled`) is off by default with manual fallback, to be enabled once the on-site setup is finalized.

> PixCut backend note: it prints by UI-automating the official Liene Photo app (which talks to the printer over Bluetooth), so that app must be open and signed in, and the terminal that launches the server needs Accessibility + Screen Recording permission; a print takes over the mouse/screen for 1–2 minutes.

## 💎 Business Value & Moat

**Why now**

- Mature generative AI + the rise of the offline experience economy — "scan your face, get a personalized IP" is finally low-friction to deploy
- A venue only needs an ordinary Mac + camera + printer, with heavy compute in the cloud — **validate first, invest later**

**The hook**

- **Personalized** (unmistakably them) × **Scarce** (once a day) × **Take-home** (physical card) × **Shareable** (social spread)

**Technical moat (not "just a filter")**

- **Identity-consistent, controllable, templated generation**: lock the face (InstantID/PuLID) + lock pose & base (prompt engineering, ControlNet next) + controlled randomness — "different every time, yet unmistakably them"
- **Edge–cloud decoupling + pluggable backend**: switch scenes by swapping templates; flexible compute cost
- **Productized end-to-end loop**: recognize → dedup → async generate → print, with scheduling, status monitoring and fallbacks — already validated on real hardware

**Transferability**

- The same engine ports to **restaurants / livehouses / expos / pop-ups / attractions / brand events** — a general "scan-to-personalized-avatar" capability

**Potential business models**

- All-in-one hardware + consumables (stickers) + SaaS subscription / per-print revenue share; a unified multi-store platform for chains; venue-owned IP skins / collaborations / seasonal editions

## 🔮 Roadmap

### 🟢 Next Version (Planned)

- **Branded card template** — composite **logo + customer nickname + date (+ QR code)** onto the output — a ready-to-share branded sticker/card
- **Enable auto-print** — the PixCut S1 real-print chain is **already wired into the console** (with AI die-cut, debug mode, and continuous-print self-healing); flip `printing.enabled` on once the on-site setup is finalized for a hands-free "recognize → print" loop
- **ControlNet pose locking** — lock "full body + pose + base" with a full-body skeleton, **fully solving the occasional "half-body output" from front/half-body inputs**; pose templates become freely extensible
- **Pose/style template library** — beyond standing and cross-legged, add more poses and **seasonal/themed skins**
- **Monitoring platform + auth** — multi-device/remote view of runtime status, generation and print counts; owner login (the console is currently local and unauthenticated)

### 🟡 To Be Decided (after a demo round)

- **Deployment hardware** — external camera (USB / IP), deployment PC (Mac / Windows), printer choice (color vs. **B&W thermal sticker** — thermal would need a line-art workflow swap)
- **Throughput** — currently single cloud concurrency (limit = 1); decide a peak-time queuing / multi-concurrency strategy
- **New-customer flow** — QR self-enrollment, first-visit onboarding

### 🔵 Long-term Vision

- Grow from "bar-regular gifts" into a **general "scan-to-personalized-IP" engine** spanning offline venues
- Accumulate **visit-frequency / activity / retention** dashboards to power venue operations
- **IP-ification and social virality**: venue-owned skins, collaborations, seasonal limited editions — shareable content assets

## 🧱 Tech Architecture (for technical due diligence)

| Layer | Components |
| --- | --- |
| **Edge (macOS)** | InsightFace (buffalo_l: SCRFD + ArcFace, CPU/onnxruntime) · FastAPI console + async generation worker · SQLite (WAL) · printing: CUPS/`lp` system printer or Liene PixCut S1 (UI-automation of the official app, Bluetooth transport + AI die-cut) · size-rotating self-cleaning logs |
| **Cloud (RunningHub)** | OpenAPI async REST · Cute You 2 workflow (PuLID + InstantID + IPAdapter + blind-box figurine LoRA) |
| **Engineering** | uv / Python 3.11 · pydantic config · pluggable backend (`mock` \| `runninghub`) · centralized `config.yaml` (gitignored) |

## 📌 Progress

- [x] Solution design & RunningHub API research
- [x] **Phase 1** face-recognition loop: recognition / DB / enrollment web / mock output (`smoke_test.py`, `smoke_server.py` pass)
- [x] Phase 1 on-device: camera recognition loop (sim ≈ 0.90–0.95, daily dedup works)
- [x] **Phase 2** real cloud generation: full RunningHub pipeline (upload → create → inject portrait + random seed → poll → download, ≈2.3 min/image), async worker / same-day dedup / in-flight guard
- [x] Phase 2 end-to-end on-device: recognize → real cartoon → print (output as expected)
- [x] Demo console: dark nightclub style (enroll / paginated regulars / state button / history / manual-print fallback / status monitoring)
- [x] Pose templates: standing figurine, cross-legged (both with a base)
- [ ] Next (see [Roadmap](#-roadmap)): branded card composition, enable auto-print, ControlNet pose locking, monitoring platform + auth, deployment hardware
