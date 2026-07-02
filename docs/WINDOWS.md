# HEYOU on Windows 10

The same codebase runs on Windows 10. The only platform-specific piece is **printing**:
on Windows, HEYOU prints to the **system printer** (via `win32print` + GDI). The macOS-only
`pixcut` backend (UI-automating the Liene Photo app) is **not used on Windows** — instead you
install the PixCut S1 as a normal Windows printer and use `backend: system`.

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

> No Liene/PixCut Windows driver? Then it can't be a system printer — you'd need a different
> approach (e.g. porting the UI-automation to Windows). Ask before going down that path.

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
- **`pixcut` backend is macOS-only.** Selecting `backend: pixcut` on Windows returns a clear
  error; use `backend: system`.
- **Camera** uses the DirectShow backend on Windows (more reliable than MSMF). If the camera
  won't open: allow camera access in **Settings → Privacy & security → Camera** (including
  "Let desktop apps access your camera"), close any app already using it, and check
  `camera.device_index`.
- **GPU (optional, DirectML)** — for onnxruntime GPU acceleration on Windows:
  `uv pip uninstall onnxruntime && uv pip install onnxruntime-directml`, then set
  `recognition.providers: [DmlExecutionProvider, CPUExecutionProvider]`. CPU is fine for the
  recognition workload, so this is optional.
- **Logs** rotate under `data\logs\` exactly as on macOS (self-cleaning, no disk fill-up).

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Windows 打印需要 pywin32` | `uv sync` (or `pip install pywin32`) — it's installed only on Windows |
| `没有可用的系统打印机` | Install the printer driver; set it default or fill `printer_name` exactly |
| Camera won't open | Privacy settings (above); close other apps; try another `device_index` |
| `onnxruntime` / InsightFace model download slow | First run downloads `buffalo_l` (~300MB) to `~/.insightface`; let it finish once |
| Wrong physical print size | Set the **paper size** in the printer's Printing preferences (HEYOU fits-to-page) |
