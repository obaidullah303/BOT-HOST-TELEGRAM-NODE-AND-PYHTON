# ElevateX Host V9 — Python + Node.js Stability Pro

Telegram hosting manager for Python and Node.js projects with premium admin controls, recovery tooling, backups and diagnostics.

## V9 highlights

- Python (`.py`) and Node.js (`.js`, `.mjs`, `.cjs`) scripts, plus `.zip` projects of either kind.
- SQLite snapshot/migration database (`elevatex_v9.db`) alongside backward-compatible JSON state.
- Internal watchdog with configurable interval and crash-loop protection.
- Scheduled project restarts and startup recovery.
- Per-user storage quotas with upload enforcement.
- Project backup, admin backup listing and confirmation-gated restore.
- Automatic log rotation, log size and log clear tools.
- Common-error diagnostics for project logs.
- Project dependency/compatibility tools: `/requirements`, `/piplist`, `/checkcompat`, `/repairenv`.
- Delegated read-only admin roles while destructive actions stay owner-only.
- Redeem-code manager: list, info, disable/enable and delete.
- Analytics dashboard.
- Runtime force-join toggle and brand/footer controls.
- Admin panel visit reminder every 72 hours by default. Use `/panelvisited` after manually visiting the hosting panel.
- External URL keep-alive remains available for optional health checks but is OFF by default.

## New V9 commands

### Stability / projects
`/watchdog [on|off]`
`/setwatchdog SECONDS`
`/watchdogstatus`
`/schedulerestart PROJECT 6h|30m|1d`
`/scheduleremove PROJECT`
`/autostart PROJECT on|off`
`/diagnose PROJECT`
`/logsize PROJECT`
`/clearlogs PROJECT`
`/requirements PROJECT`
`/piplist PROJECT`
`/checkcompat PROJECT`
`/repairenv PROJECT`

### Storage / backup
`/storage`
`/setstorage USER_ID MB`
`/projectbackup PROJECT`
`/backups`
`/restorebackup FILENAME.zip CONFIRM`

### Admin / analytics
`/analytics`
`/addadmin USER_ID support|moderator|superadmin`
`/deladmin USER_ID`
`/admins`
`/codes`
`/codeinfo CODE`
`/disablecode CODE`
`/deletecode CODE`
`/forcejoin on|off`
`/setbrand NAME`
`/setfooter TEXT`

### Panel reminder
`/panelreminder [on|off]`
`/panelvisited`

The reminder defaults to 72 hours. It only reminds the owner to manually visit the hosting panel; it does not automate third-party login.

## Deployment

Create a file named `.env` next to `main.py` (copy `.env.example`) and set at least:

```bash
BOT_TOKEN=your_new_bot_token
OWNER_ID=your_telegram_user_id
```

Install:

```bash
pip install -r requirements.txt
python main.py
```

## Node.js support

- Upload a `.js` file or a `.zip` (with `package.json` or `index.js` / `bot.js` / `app.js`). The entry file is read from `package.json` (`scripts.start` or `main`).
- `npm install` runs automatically when `package.json` exists. For a single `.js` file with no `package.json`, the packages it `require`s / `import`s are detected and installed automatically.
- No Node.js on the VPS? Owner sends `/nodeinstall` (or Admin Center → 🟩 Node.js). A portable official build is downloaded into `runtime/node` — no root needed. Set `NODE_VERSION` in `.env` to pick another version.
- `/npminstall PROJECT PACKAGE…` adds npm packages to a project. `/piplist`, `/requirements`, `/checkcompat`, `/repairenv` and `/diagnose` understand Node projects too.
- Env variables set for a project are available as `process.env.NAME` (Node) or `os.environ` (Python).

## Project buttons

Open **📂 My Projects → (project)**:

- 🔄 **Update Code** — send a new `.py`/`.js`/`.zip`; files are overwritten, env variables and installed packages are kept, a running project restarts automatically. `/cancel` aborts (expires after 5 minutes).
- 📦 **Reinstall deps** — rebuilds `.venv` or `node_modules`.
- 🩺 **Diagnose**, 📊 **Stats**, 💾 **Backup** (sends a zip), ♻️ **Auto-restart on/off**.
- 🔐 **Env** — add variables by pasting `KEY=VALUE` lines (your message is deleted afterwards).
- Project list: ▶️ **Start All** · 🛑 **Stop All** · 🔁 **Restart All**.

For arbitrary user-uploaded code, run ElevateX Host inside an isolated container/VM. Static scanning and process monitoring are not a complete sandbox.
