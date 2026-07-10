# HEYOU on Windows 10

The same codebase runs on Windows 10. The only platform-specific piece is **printing**, and on
Windows you have **two** options:

- **`backend: system`** (simplest) — print to the PixCut S1 as a normal **Windows printer**
  (`win32print` + GDI). No die-cut; the sticker prints as a plain rectangle. See §2–§4.
- **`backend: pixcut`** (real die-cut) — UI-automate the official **极印/Liene Photo** app the
  same way macOS does, so you get the true **AI 抠图 cut around the subject** on 4×7 sticker
  paper. This is now supported on Windows via `pixcut-probe/pixcut_win.py`. See **§5**.

> Everything below assumes a 64-bit Windows 10, an attached webcam, and the PixCut S1 (or any
> printer) installed in Windows.

## 0. One-click: `run_windows.bat` (recommended)

On a **fresh** Windows 10, just **double-click `run_windows.bat`** in the project root. It
bootstraps everything and starts the app:

1. installs **uv** (if missing) via the official installer;
2. creates `config.yaml` from the example (if missing) — defaults to `generation: mock`, so it
   runs without an API key;
3. installs **Python 3.11 + all dependencies** (`uv python install` + `uv sync`, incl. `pywin32`);
4. starts the server, forcing **UTF-8** so Chinese/arrows never crash the console.

It writes the **entire run (stdout + stderr, including any crash traceback)** to
`logs\run_<timestamp>.log`, and the window stays open. **If anything fails, send me that log.**

You still need to do two things by hand for a *real* deployment (not needed just to boot):

- **Install the printer** (§2) so it appears as a Windows printer.
- **Edit `config.yaml`** to set your RunningHub API key and `generation.backend: runninghub`
  (§3) for real generation instead of `mock`.

The manual steps below are the same thing, spelled out — use them if you'd rather not use the
`.bat`, or to understand what it does.

## 1. Install Python 3.11 + uv (manual)

```powershell
# Install uv (https://docs.astral.sh/uv/). In PowerShell:
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# In the project folder:
uv sync
```

`uv sync` installs everything, and on Windows it **also installs `pywin32`** automatically
(it's a platform-conditional dependency). If you ever install with plain `pip`, run
`pip install pywin32` too. `uv` auto-downloads Python 3.11 if it isn't present.

## 2. Install the printer

1. Install Liene/PixCut's **Windows driver** so the printer appears in
   **Settings → Bluetooth & devices → Printers & scanners**.
2. Either make it the **default** printer, or note its **exact name** for `printer_name`.
3. In the printer's **Printing preferences**, set the **paper size** to your sticker size
   (e.g. 4×7). HEYOU scales each image to fit the page, centered, keeping aspect ratio — so the
   driver's paper size determines the physical output size.
4. Print a test page from Windows first, to confirm the driver works on its own.

> Want the **die-cut** (sticker cut to the subject's outline), not a plain rectangle? Skip the
> system-printer route and use the **`pixcut` backend** instead — see **§5**.

## 3. Configure

```powershell
copy config.example.yaml config.yaml
```

Edit `config.yaml`:

```yaml
recognition:
  providers: [CPUExecutionProvider]   # CPU works everywhere. For a GPU, see "DirectML" below.

camera:
  device_index: 0                     # 0 = first camera; try 1, 2… if the wrong one opens

printing:
  enabled: false                      # false = manual print only; true = auto-print after generation
  backend: system                     # IMPORTANT on Windows (NOT "pixcut")
  printer_name: ""                    # "" = Windows default printer, or the exact printer name
```

Put your `runninghub_api_key` in the `comfyui:` block as on macOS. `config.yaml` is gitignored.

## 4. Run

Easiest is the one-click **`run_windows.bat`** (see §0) — it also captures the full run to
`logs\run_<timestamp>.log`. To run manually instead:

```powershell
uv run python scripts\run_server.py
# → open http://127.0.0.1:8000
```

Enroll a regular on the **Enroll** tab; on the **Regulars** tab you can generate and **manually
print**. Flip `printing.enabled: true` for the hands-free recognize → generate → print loop.

## Notes & differences from macOS

- **Printing path** — Windows renders the image onto the printer's GDI device context, scaled
  to the printable page area (aspect-preserving, centered). Output size = the driver's paper
  size, so set that to your sticker size.
- **`pixcut` backend now works on Windows too** (§5) — it drives the official app for a real
  die-cut. Use `backend: system` only if you want the simpler plain-rectangle print.
- **Camera** uses the DirectShow backend on Windows (more reliable than MSMF). If the camera
  won't open: allow camera access in **Settings → Privacy & security → Camera** (including
  "Let desktop apps access your camera"), close any app already using it, and check
  `camera.device_index`.
- **GPU (optional, DirectML)** — for onnxruntime GPU acceleration on Windows:
  `uv pip uninstall onnxruntime && uv pip install onnxruntime-directml`, then set
  `recognition.providers: [DmlExecutionProvider, CPUExecutionProvider]`. CPU is fine for the
  recognition workload, so this is optional.
- **Logs** rotate under `data\logs\` exactly as on macOS (self-cleaning, no disk fill-up).

## 5. (optional) PixCut S1 real die-cut via UI-automation (`backend: pixcut`)

This drives the official **极印/Liene Photo** app so stickers are **cut to the subject's
outline** (not a plain rectangle), exactly like the macOS path. It uses
`pixcut-probe/pixcut_win.py` — no Windows print driver needed.

**Why it's built this way (for future maintainers).** The app is a *hybrid*: the home/community
screen is a **WebView2** web page, but the 创建设计 dialog and the whole editor are **native
Flutter**. Synthesized OS input (SendInput/pyautogui) is silently dropped by the *web* content
but works on *Flutter*. So the driver is hybrid too: it relaunches the app with WebView2 remote
debugging and clicks the home **画板** button over the **Chrome DevTools Protocol (CDP)**, then
drives the Flutter editor (canvas pick → upload → place → size → 制作 → 切割) with **SendInput**
pixel clicks. Text fields need the window forced foreground (AttachThreadInput) before typing.
Full reverse-engineering notes live in the code comments.

**Prerequisites:**

1. Install the **极印/Liene Photo** Windows app and **sign in** (the Creativerse account). The
   PixCut S1 connects over **USB** on Windows.
2. Load **4×7 背胶相纸** (adhesive sticker paper) in the printer — the cut preview warns if not.
3. `uv sync` installs the Windows automation deps (`pyautogui`, `pygetwindow`, `pyperclip`,
   `psutil`, `websocket-client`) automatically.

**Configure** `config.yaml`:

```yaml
printing:
  enabled: false      # false = manual print only; true = auto-print after generation
  backend: pixcut     # drive the Liene app for a real die-cut (mac + Windows)
  pixcut:
    dry_run: false    # true = run the whole flow but never click 切割 (no print, no ribbon)
    margin_in: 0.0    # shrink the fitted image by this margin per side
    timeout_sec: 300  # Windows uses max(this, 480) internally
```

**How it behaves each print:** the driver **restarts the app** for a guaranteed-clean start
(sign-in is preserved), runs home → new 4×7 canvas → upload the image → place → size it to fill
the sheet → 制作 → waits for the 切割预览 to finish loading → clicks **切割** (real print) →
polls the app log for completion → **returns to home** for the next print. It takes over the
screen for ~2–3 min — **don't touch the mouse/keyboard while it runs.**

**Try it first without wasting ribbon** — the standalone dry-run runs the entire flow but never
clicks 切割:

```powershell
uv run python pixcut-probe\pixcut_win.py dryrun pixcut-probe\samples\sample_4x7.jpg
```

It saves a screenshot of every step to `logs\cal_NN_*.png`. When that reaches the 切割预览
cleanly, a real print is `pixcut_win.py print <image>` (or just set `backend: pixcut` and let
HEYOU call it). Keyboard/screen permissions aren't needed on Windows (unlike macOS), but the
app window must stay at its normal size and not be minimized.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Windows 打印需要 pywin32` | `uv sync` (or `pip install pywin32`) — it's installed only on Windows |
| `Liene Photo 未运行` (pixcut backend) | Open + sign in to the 极印 Photo app first; keep its window at normal size, not minimized |
| pixcut dry-run stalls / wrong clicks | Don't touch mouse/keyboard while it runs; keep the app window un-resized; check `logs\cal_*.png` |
| `没有可用的系统打印机` | Install the printer driver; set it default or fill `printer_name` exactly |
| Camera won't open | Privacy settings (above); close other apps; try another `device_index` |
| `onnxruntime` / InsightFace model download slow | First run downloads `buffalo_l` (~300MB) to `~/.insightface`; let it finish once |
| Wrong physical print size | Set the **paper size** in the printer's Printing preferences (HEYOU fits-to-page) |
