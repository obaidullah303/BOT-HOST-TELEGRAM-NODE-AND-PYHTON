#!/usr/bin/env python3
"""
ElevateX Host V9 — Premium Python + Node.js Stability Hosting Manager

WARNING:
This bot executes uploaded Python and Node.js projects. Run it only inside an isolated
container or VM. It is not a security sandbox.

Recommended:
Python 3.11+
python-telegram-bot[job-queue]>=22,<23
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import shutil
import shlex
import signal
import subprocess
import secrets
import hashlib
import sqlite3
import platform
import sys
import time
import zipfile
import threading
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ═════════════════════════════════════════════════════════════════════════════
# CONFIGURATION — EDIT HERE
# ═════════════════════════════════════════════════════════════════════════════




def _load_dotenv() -> None:
    """Load KEY=VALUE pairs from a .env file next to main.py (real env vars win)."""
    env_file = Path(__file__).resolve().parent / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text("utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

# Secrets live in .env (or real environment variables) - never hardcode them.
# ══════════ PANEL .env LOCKED? PASTE YOUR VALUES HERE (inside the quotes) ══════════
MY_BOT_TOKEN = ""        # example: "123456:ABC-DEF..."
MY_OWNER_ID = ""         # example: "8936721340"  (leave empty to keep the default)
MY_ACCESS_PASSWORD = ""  # optional
# ═════════════════════════════════════════════════════════════════════════════════

TOKEN = os.getenv("BOT_TOKEN", "8848962072:AAGzonOgLpouMZ_mfbmb94Gdl8LKiBtNcgE").strip() or MY_BOT_TOKEN.strip()
OWNER_ID = int(os.getenv("OWNER_ID", "8936721340").strip() or MY_OWNER_ID.strip() or "8936721340")
# Optional: users who send this text get approved automatically. Empty = disabled.
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "xpobaid7879").strip() or MY_ACCESS_PASSWORD.strip()

BRAND_NAME = "XP OBAID X Host"
OWNER_NAME = "HOSTING By OBAID"
OWNER_USERNAME = "XP OBAID"

MAX_FILE_MB = 20
MAX_ZIP_EXPANDED_MB = 100

DEFAULT_CREDITS = 2
CREDIT_PER_UPLOAD = 1
PREMIUM_BONUS_CREDITS = 100

DAILY_UPLOAD_LIMIT = 1
PREMIUM_DAILY_UPLOAD_LIMIT = 50

MAX_RUNNING_PER_USER = 2
PREMIUM_MAX_RUNNING_PER_USER = 10

LAUNCH_CHECK_SECONDS = 2.0
MAX_LOG_CHARS = 3000
MAX_RESTARTS = 3
INSTALL_TIMEOUT_SECONDS = 180
MAX_INSTALL_OUTPUT_CHARS = 3500
DEPENDENCY_TIMEOUT_SECONDS = int(os.getenv("DEPENDENCY_TIMEOUT_SECONDS", "300"))
DEFAULT_PROJECT_RAM_MB = int(os.getenv("DEFAULT_PROJECT_RAM_MB", "256"))
DEFAULT_PROJECT_CPU_PERCENT = int(os.getenv("DEFAULT_PROJECT_CPU_PERCENT", "50"))
AUTO_INSTALL_DEPENDENCIES = os.getenv("AUTO_INSTALL_DEPENDENCIES", "1") == "1"
SECURITY_SCAN_ENABLED = os.getenv("SECURITY_SCAN_ENABLED", "1") == "1"
DOCKER_MODE = os.getenv("DOCKER_MODE", "0") == "1"
ENFORCE_RESOURCE_LIMITS = os.getenv("ENFORCE_RESOURCE_LIMITS", "1") == "1"
# RLIMIT_NPROC is counted per Linux UID on many hosts, not per project. A low
# value can prevent Telegram/httpx from creating DNS/helper threads when
# several bots share the same panel account. Keep it disabled by default.
PROJECT_PROCESS_LIMIT = int(os.getenv("PROJECT_PROCESS_LIMIT", "0"))
# RLIMIT_AS limits virtual address space rather than real RSS and can break
# modern Python runtimes even when actual RAM usage is low. Opt in explicitly.
ENFORCE_ADDRESS_SPACE_LIMIT = os.getenv("ENFORCE_ADDRESS_SPACE_LIMIT", "0") == "1"
PROJECT_OPEN_FILES_LIMIT = int(os.getenv("PROJECT_OPEN_FILES_LIMIT", "512"))
DOCKER_IMAGE_PYTHON = os.getenv("DOCKER_IMAGE_PYTHON", "python:3.11-slim")
BACKUP_INTERVAL_HOURS = int(os.getenv("BACKUP_INTERVAL_HOURS", "24"))
WATCHDOG_INTERVAL_DEFAULT = max(20, int(os.getenv("WATCHDOG_INTERVAL_SECONDS", "40")))
LOG_ROTATE_MAX_MB = max(1, int(os.getenv("LOG_ROTATE_MAX_MB", "2")))
LOG_ROTATE_KEEP_MB = max(1, int(os.getenv("LOG_ROTATE_KEEP_MB", "1")))
DEFAULT_STORAGE_QUOTA_MB = max(50, int(os.getenv("DEFAULT_STORAGE_QUOTA_MB", "500")))
PANEL_REMINDER_HOURS = max(24, int(os.getenv("PANEL_REMINDER_HOURS", "72")))
CRASH_WINDOW_SECONDS = max(60, int(os.getenv("CRASH_WINDOW_SECONDS", "600")))
CRASH_LIMIT = max(2, int(os.getenv("CRASH_LIMIT", "5")))

# Python + Node.js runtime + built-in health/keep-alive service
PYTHON_ONLY_MODE = False
HEALTH_PORT = int(os.getenv("PORT", os.getenv("HEALTH_PORT", "8080")))
KEEPALIVE_INTERVAL_DEFAULT = max(30, min(45, int(os.getenv("KEEPALIVE_INTERVAL_SECONDS", "40"))))
KEEPALIVE_URL_ENV = os.getenv("KEEPALIVE_URL", "").strip()

def _auto_public_url() -> str:
    direct = os.getenv("RENDER_EXTERNAL_URL", "").strip()
    if direct:
        return direct.rstrip("/") + "/health"
    for key in ("RAILWAY_PUBLIC_DOMAIN", "KOYEB_PUBLIC_DOMAIN"):
        domain = os.getenv(key, "").strip()
        if domain:
            if not domain.startswith(("http://", "https://")):
                domain = "https://" + domain
            return domain.rstrip("/") + "/health"
    fly = os.getenv("FLY_APP_NAME", "").strip()
    if fly:
        return f"https://{fly}.fly.dev/health"
    return ""

KEEPALIVE_URL_DEFAULT = KEEPALIVE_URL_ENV or _auto_public_url()

FORCE_JOIN_ENABLED = True
AUTO_RESTART_ENABLED = False
MAINTENANCE_MODE_DEFAULT = False

# ═════════════════════════════════════════════════════════════════════════════
# PATHS & LOGGING
# ═════════════════════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
DATA_FILE = BASE_DIR / "bot_data.json"
PROJECTS_FILE = BASE_DIR / "projects.json"
V7_DATA_FILE = BASE_DIR / "v7_data.json"
V9_DB_FILE = BASE_DIR / "elevatex_v9.db"
PROJECT_BACKUPS_DIR = BASE_DIR / "project_backups"
BACKUPS_DIR = BASE_DIR / "backups"
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
PROJECT_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

START_TIME = time.time()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("ElevateXHostV5")

# ═════════════════════════════════════════════════════════════════════════════
# NODE.JS SUPPORT
# ═════════════════════════════════════════════════════════════════════════════

NODE_VERSION = os.getenv("NODE_VERSION", "22.12.0")
NODE_RUNTIME_DIR = BASE_DIR / "runtime" / "node"
NPM_CACHE_DIR = BASE_DIR / "runtime" / "npm-cache"
PY_EXTS = {".py"}
NODE_EXTS = {".js", ".mjs", ".cjs"}
SUPPORTED_EXTS = PY_EXTS | NODE_EXTS
SKIP_DIRS = {"node_modules", ".venv", "__pycache__", ".git"}
_EXE = ".exe" if os.name == "nt" else ""
PY_PRIORITY = ("main.py", "bot.py", "app.py", "index.py", "server.py", "run.py")
JS_PRIORITY = ("index.js", "main.js", "bot.js", "app.js", "server.js", "start.js",
               "index.mjs", "main.mjs", "index.cjs")
NODE_BUILTINS = {
    "assert", "async_hooks", "buffer", "child_process", "cluster", "console", "constants",
    "crypto", "dgram", "diagnostics_channel", "dns", "domain", "events", "fs", "http",
    "http2", "https", "inspector", "module", "net", "os", "path", "perf_hooks", "process",
    "punycode", "querystring", "readline", "repl", "stream", "string_decoder", "sys",
    "timers", "tls", "trace_events", "tty", "url", "util", "v8", "vm", "wasi",
    "worker_threads", "zlib", "test",
}
NPM_SPEC_RE = re.compile(
    r"^(?:@[a-z0-9][a-z0-9._~-]*/)?[a-z0-9][a-z0-9._~-]*(?:@[A-Za-z0-9._^~<>=*+-]+)?$"
)
NPM_NAME_RE = re.compile(r"^(?:@[a-z0-9][a-z0-9._~-]*/)?[a-z0-9][a-z0-9._~-]*$")
_JS_IMPORT_RE = re.compile(
    r"""(?:require\s*\(\s*|import\s*\(\s*|from\s+|import\s+)(['"])([^'"\n]+)\1"""
)


def iter_project_files(folder: Path, suffixes: set[str] | None = None,
                       names: set[str] | None = None):
    """Walk a project, skipping node_modules/.venv/.git (fast, prunes directories)."""
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            if (suffixes and Path(fname).suffix.lower() in suffixes) or (names and fname in names):
                yield Path(root) / fname


def _depth(path: Path, folder: Path) -> int:
    try:
        return len(path.relative_to(folder).parts)
    except ValueError:
        return 99


def find_requirements(folder: Path) -> Path | None:
    files = list(iter_project_files(folder, names={"requirements.txt"}))
    return min(files, key=lambda x: (_depth(x, folder), str(x)), default=None)


def node_bin_dir() -> Path | None:
    configured = os.getenv("NODE_BIN", "").strip()
    if configured and Path(configured).is_file():
        return Path(configured).parent
    found = shutil.which("node")
    if found:
        return Path(found).parent
    local = NODE_RUNTIME_DIR / "bin" / f"node{_EXE}"
    if local.is_file():
        return local.parent
    return None


def node_path() -> str | None:
    folder = node_bin_dir()
    return str(folder / f"node{_EXE}") if folder else None


def npm_command() -> list[str] | None:
    folder = node_bin_dir()
    if folder:
        candidate = folder / ("npm.cmd" if os.name == "nt" else "npm")
        if candidate.exists():
            return [str(candidate)]
    found = shutil.which("npm")
    return [found] if found else None


def node_env() -> dict[str, str]:
    env = os.environ.copy()
    folder = node_bin_dir()
    if folder:
        env["PATH"] = str(folder) + os.pathsep + env.get("PATH", "")
    try:
        NPM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        env.setdefault("npm_config_cache", str(NPM_CACHE_DIR))
    except OSError:
        pass
    env.setdefault("npm_config_update_notifier", "false")
    env.setdefault("npm_config_fund", "false")
    return env


def node_version() -> str:
    node = node_path()
    if not node:
        return ""
    try:
        result = subprocess.run([node, "--version"], capture_output=True, text=True,
                                timeout=10, env=node_env())
        return (result.stdout or "").strip()
    except Exception:
        return ""


def install_node_runtime() -> str:
    """Download the official portable Node.js build into ./runtime/node (no root needed)."""
    import tarfile
    import tempfile

    if os.name == "nt":
        raise RuntimeError("Automatic install is Linux-only. Install Node.js from nodejs.org.")
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64",
            "arm64": "arm64", "armv7l": "armv7l"}.get(machine)
    if not arch:
        raise RuntimeError(f"Unsupported CPU architecture: {machine}")
    name = f"node-v{NODE_VERSION}-linux-{arch}"
    base_url = f"https://nodejs.org/dist/v{NODE_VERSION}"
    runtime_root = NODE_RUNTIME_DIR.parent
    runtime_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=runtime_root) as tmp:
        archive = Path(tmp) / f"{name}.tar.xz"
        headers = {"User-Agent": "ElevateXHost"}
        with urllib.request.urlopen(
            urllib.request.Request(f"{base_url}/{name}.tar.xz", headers=headers), timeout=180
        ) as resp, archive.open("wb") as fh:
            shutil.copyfileobj(resp, fh)
        try:
            with urllib.request.urlopen(
                urllib.request.Request(f"{base_url}/SHASUMS256.txt", headers=headers), timeout=30
            ) as resp:
                sums = resp.read().decode("utf-8", errors="replace")
            expected = next((ln.split()[0] for ln in sums.splitlines()
                             if ln.strip().endswith(f"{name}.tar.xz")), "")
        except Exception:
            expected = ""
        if expected and hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
            raise RuntimeError("Checksum mismatch - download was corrupted. Try again.")
        with tarfile.open(archive, "r:xz") as tar:
            if hasattr(tarfile, "data_filter"):
                tar.extractall(tmp, filter="data")
            else:
                tar.extractall(tmp)
        extracted = Path(tmp) / name
        if not (extracted / "bin" / "node").exists():
            raise RuntimeError("Downloaded archive looks invalid.")
        if NODE_RUNTIME_DIR.exists():
            shutil.rmtree(NODE_RUNTIME_DIR)
        shutil.move(str(extracted), str(NODE_RUNTIME_DIR))
    return node_version() or "installed"


def node_project_root(entry: Path, folder: Path) -> Path:
    """Closest folder (entry file upwards, inside the project) that holds package.json."""
    try:
        top = folder.resolve()
        current = entry.resolve().parent
    except OSError:
        return folder
    while True:
        if (current / "package.json").exists():
            return current
        if current == top or current.parent == current:
            break
        current = current.parent
    return folder


def package_json_entry(folder: Path) -> tuple[Path, Path] | None:
    pkgs = sorted(iter_project_files(folder, names={"package.json"}),
                  key=lambda x: (_depth(x, folder), str(x)))
    top = folder.resolve()
    for pkg in pkgs[:3]:
        try:
            data = json.loads(pkg.read_text("utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        candidates: list[str] = []
        scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
        match = re.search(
            r"\bnode\s+(?:-{1,2}[\w=.:-]+\s+)*([^\s&|;]+\.(?:c|m)?js)\b",
            str(scripts.get("start") or ""),
        )
        if match:
            candidates.append(match.group(1))
        if isinstance(data.get("main"), str):
            candidates.append(data["main"])
        for candidate in candidates:
            path = (pkg.parent / candidate).resolve()
            try:
                path.relative_to(top)
            except ValueError:
                continue
            if path.is_file() and path.suffix.lower() in NODE_EXTS:
                return path, pkg
    return None


def runtime_label(entry: Path) -> str:
    return "🟩 Node.js" if entry.suffix.lower() in NODE_EXTS else "🐍 Python"


def auto_install_node_imports(root: Path, log_path: Path) -> str:
    """Single-file Node scripts have no package.json: install the packages they import."""
    found: set[str] = set()
    for file in iter_project_files(root, suffixes=NODE_EXTS):
        try:
            if file.stat().st_size > 2_000_000:
                continue
            text = file.read_text("utf-8", errors="ignore")
        except OSError:
            continue
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        text = re.sub(r"(?m)^\s*//.*$", "", text)
        for _, spec in _JS_IMPORT_RE.findall(text):
            if spec.startswith((".", "/", "node:", "file:", "http")):
                continue
            parts = spec.split("/")
            pkg = "/".join(parts[:2]) if spec.startswith("@") else parts[0]
            if pkg in NODE_BUILTINS or not NPM_NAME_RE.fullmatch(pkg):
                continue
            found.add(pkg)
    packages = sorted(found)[:25]
    if not packages:
        return ""
    npm = npm_command()
    if not npm:
        return "npm missing - owner can send /nodeinstall"
    try:
        result = subprocess.run(
            npm + ["install", "--no-audit", "--no-fund", "--no-progress", *packages],
            cwd=root, env=node_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=DEPENDENCY_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return "auto npm install timed out"
    out = result.stdout.decode("utf-8", errors="replace")
    with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
        log_file.write("\n\n===== Auto-detected npm packages =====\n" + out + "\n")
    if result.returncode != 0:
        return "auto npm install failed (see runtime.log)"
    return "auto-installed npm packages: " + ", ".join(packages)

# ═════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class ScriptProcess:
    display_name: str
    entry_file: str
    folder: str
    log_path: str
    proc: subprocess.Popen[Any] | None = None
    started_at: float = field(default_factory=time.time)
    restarts: int = 0
    auto_restart: bool = AUTO_RESTART_ENABLED
    desired_running: bool = False

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def pid(self) -> str:
        return str(self.proc.pid) if self.proc else "—"

    @property
    def exit_code(self) -> str:
        if self.proc is None:
            return "Not started"
        if self.proc.poll() is None:
            return "Running"
        return str(self.proc.returncode)

    def serialize(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "entry_file": self.entry_file,
            "folder": self.folder,
            "log_path": self.log_path,
            "started_at": self.started_at,
            "restarts": self.restarts,
            "auto_restart": self.auto_restart,
            "was_running": bool(self.running or self.desired_running),
        }


approved_users: set[int] = set()
premium_users: set[int] = set()
banned_users: set[int] = set()

user_stats: dict[str, dict[str, Any]] = {}
user_credits: dict[str, int] = {}
custom_daily_limits: dict[str, int] = {}
custom_running_limits: dict[str, int] = {}

maintenance_mode = MAINTENANCE_MODE_DEFAULT

# V7 premium state (kept separately for safe migration from V6)
premium_expiry: dict[str, str] = {}
user_plans: dict[str, str] = {}
redeem_codes: dict[str, dict[str, Any]] = {}
project_envs: dict[str, dict[str, str]] = {}
project_settings: dict[str, dict[str, Any]] = {}
audit_log: list[dict[str, Any]] = []
admin_roles: dict[str, str] = {}
user_storage_limits: dict[str, int] = {}
watchdog_enabled: bool = True
watchdog_interval: int = WATCHDOG_INTERVAL_DEFAULT
watchdog_last_epoch: float = 0.0
watchdog_restarts: int = 0
panel_reminder_enabled: bool = True
panel_last_confirmed_at: float = time.time()
panel_last_reminder_at: float = 0.0
brand_footer: str = "⚡ Powered by XP OBAID⚡ "

keepalive_enabled: bool = False
keepalive_url: str = KEEPALIVE_URL_DEFAULT
keepalive_interval: int = KEEPALIVE_INTERVAL_DEFAULT
keepalive_last_status: str = "Not run yet"
keepalive_last_at: str = "—"
keepalive_failures: int = 0
keepalive_last_epoch: float = 0.0
health_server_started: bool = False

running_scripts: dict[int, list[ScriptProcess]] = {}
pending_project_names: dict[int, ScriptProcess] = {}
pending_updates: dict[int, tuple[ScriptProcess, float]] = {}
pending_env: dict[int, tuple[ScriptProcess, float]] = {}
user_locks: dict[int, asyncio.Lock] = {}

# ═════════════════════════════════════════════════════════════════════════════
# STORAGE
# ═════════════════════════════════════════════════════════════════════════════

def lock_for(user_id: int) -> asyncio.Lock:
    return user_locks.setdefault(user_id, asyncio.Lock())


def load_data() -> None:
    global approved_users, premium_users, banned_users
    global user_stats, user_credits
    global custom_daily_limits, custom_running_limits, maintenance_mode

    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text("utf-8"))
            approved_users = {int(x) for x in data.get("approved_users", [])}
            premium_users = {int(x) for x in data.get("premium_users", [])}
            banned_users = {int(x) for x in data.get("banned_users", [])}
            user_stats = dict(data.get("user_stats", {}))
            user_credits = {
                str(k): int(v)
                for k, v in data.get("user_credits", {}).items()
            }
            custom_daily_limits = {
                str(k): int(v)
                for k, v in data.get("custom_daily_limits", {}).items()
            }
            custom_running_limits = {
                str(k): int(v)
                for k, v in data.get("custom_running_limits", {}).items()
            }
            maintenance_mode = bool(
                data.get("maintenance_mode", MAINTENANCE_MODE_DEFAULT)
            )
        except Exception:
            logger.exception("Could not load bot data")

    if PROJECTS_FILE.exists():
        try:
            data = json.loads(PROJECTS_FILE.read_text("utf-8"))
            for uid, rows in data.items():
                items: list[ScriptProcess] = []
                for row in rows:
                    entry = Path(row["entry_file"])
                    folder = Path(row["folder"])
                    if entry.exists() and folder.exists():
                        items.append(
                            ScriptProcess(
                                display_name=row.get(
                                    "display_name", entry.name
                                ),
                                entry_file=str(entry),
                                folder=str(folder),
                                log_path=row.get(
                                    "log_path",
                                    str(folder / "runtime.log"),
                                ),
                                started_at=float(
                                    row.get("started_at", time.time())
                                ),
                                restarts=int(row.get("restarts", 0)),
                                auto_restart=bool(
                                    row.get(
                                        "auto_restart",
                                        AUTO_RESTART_ENABLED,
                                    )
                                ),
                                desired_running=bool(row.get("was_running", False)),
                            )
                        )
                running_scripts[int(uid)] = items
        except Exception:
            logger.exception("Could not load project registry")


def save_data() -> None:
    payload = {
        "approved_users": sorted(approved_users),
        "premium_users": sorted(premium_users),
        "banned_users": sorted(banned_users),
        "user_stats": user_stats,
        "user_credits": user_credits,
        "custom_daily_limits": custom_daily_limits,
        "custom_running_limits": custom_running_limits,
        "maintenance_mode": maintenance_mode,
    }

    temp = DATA_FILE.with_suffix(".tmp")
    try:
        temp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            "utf-8",
        )
        temp.replace(DATA_FILE)
        if V9_DB_FILE.exists(): sync_v9_database()
    except Exception:
        logger.exception("Could not save bot data")
        temp.unlink(missing_ok=True)


def save_projects() -> None:
    payload = {
        str(uid): [item.serialize() for item in items]
        for uid, items in running_scripts.items()
    }

    temp = PROJECTS_FILE.with_suffix(".tmp")
    try:
        temp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            "utf-8",
        )
        temp.replace(PROJECTS_FILE)
        if V9_DB_FILE.exists(): sync_v9_database()
    except Exception:
        logger.exception("Could not save project registry")
        temp.unlink(missing_ok=True)


def load_v7_data() -> None:
    global premium_expiry, user_plans, redeem_codes, project_envs
    global project_settings, audit_log, admin_roles
    global keepalive_enabled, keepalive_url, keepalive_interval
    global user_storage_limits, watchdog_enabled, watchdog_interval
    global panel_reminder_enabled, panel_last_confirmed_at, panel_last_reminder_at, brand_footer
    if not V7_DATA_FILE.exists():
        return
    try:
        data = json.loads(V7_DATA_FILE.read_text("utf-8"))
        premium_expiry = dict(data.get("premium_expiry", {}))
        user_plans = dict(data.get("user_plans", {}))
        redeem_codes = dict(data.get("redeem_codes", {}))
        project_envs = {str(k): dict(v) for k, v in data.get("project_envs", {}).items()}
        project_settings = {str(k): dict(v) for k, v in data.get("project_settings", {}).items()}
        audit_log = list(data.get("audit_log", []))[-2000:]
        admin_roles = dict(data.get("admin_roles", {}))
        user_storage_limits = {str(k): int(v) for k, v in data.get("user_storage_limits", {}).items()}
        wd = data.get("watchdog", {})
        watchdog_enabled = bool(wd.get("enabled", True))
        watchdog_interval = max(20, int(wd.get("interval", WATCHDOG_INTERVAL_DEFAULT)))
        pr = data.get("panel_reminder", {})
        panel_reminder_enabled = bool(pr.get("enabled", True))
        panel_last_confirmed_at = float(pr.get("last_confirmed_at", time.time()))
        panel_last_reminder_at = float(pr.get("last_reminder_at", 0.0))
        brand_footer = str(data.get("brand_footer", brand_footer))
        ka = data.get("keepalive", {})
        keepalive_enabled = bool(ka.get("enabled", False))
        keepalive_url = str(ka.get("url", KEEPALIVE_URL_DEFAULT) or KEEPALIVE_URL_DEFAULT)
        keepalive_interval = max(30, min(45, int(ka.get("interval", KEEPALIVE_INTERVAL_DEFAULT))))
    except Exception:
        logger.exception("Could not load V7 data")


def save_v7_data() -> None:
    payload = {
        "premium_expiry": premium_expiry,
        "user_plans": user_plans,
        "redeem_codes": redeem_codes,
        "project_envs": project_envs,
        "project_settings": project_settings,
        "audit_log": audit_log[-2000:],
        "admin_roles": admin_roles,
        "user_storage_limits": user_storage_limits,
        "watchdog": {"enabled": watchdog_enabled, "interval": watchdog_interval},
        "panel_reminder": {
            "enabled": panel_reminder_enabled,
            "last_confirmed_at": panel_last_confirmed_at,
            "last_reminder_at": panel_last_reminder_at,
        },
        "brand_footer": brand_footer,
        "keepalive": {
            "enabled": keepalive_enabled,
            "url": keepalive_url,
            "interval": keepalive_interval,
        },
    }
    temp = V7_DATA_FILE.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), "utf-8")
        temp.replace(V7_DATA_FILE)
        if V9_DB_FILE.exists(): sync_v9_database()
    except Exception:
        logger.exception("Could not save V7 data")
        temp.unlink(missing_ok=True)



def init_v9_database() -> None:
    """Create a durable SQLite mirror while retaining JSON backward compatibility."""
    try:
        with sqlite3.connect(V9_DB_FILE) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS snapshots (name TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, actor INTEGER, action TEXT, target TEXT, detail TEXT)")
            db.commit()
    except Exception:
        logger.exception("Could not initialize V9 SQLite database")


def sync_v9_database() -> None:
    try:
        snapshots = {
            "users": {
                "approved_users": sorted(approved_users), "premium_users": sorted(premium_users),
                "banned_users": sorted(banned_users), "user_stats": user_stats,
                "user_credits": user_credits, "custom_daily_limits": custom_daily_limits,
                "custom_running_limits": custom_running_limits, "maintenance_mode": maintenance_mode,
            },
            "projects": {str(uid): [x.serialize() for x in rows] for uid, rows in running_scripts.items()},
            "premium": {
                "premium_expiry": premium_expiry, "user_plans": user_plans,
                "redeem_codes": redeem_codes, "project_envs": project_envs,
                "project_settings": project_settings, "admin_roles": admin_roles,
                "user_storage_limits": user_storage_limits,
            },
        }
        now = datetime.now().isoformat(timespec="seconds")
        with sqlite3.connect(V9_DB_FILE) as db:
            for name, payload in snapshots.items():
                db.execute(
                    "INSERT INTO snapshots(name,payload,updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
                    (name, json.dumps(payload, ensure_ascii=False), now),
                )
            db.commit()
    except Exception:
        logger.exception("Could not sync V9 SQLite database")


def db_event(actor: int, action: str, target: str = "", detail: str = "") -> None:
    try:
        with sqlite3.connect(V9_DB_FILE) as db:
            db.execute(
                "INSERT INTO events(created_at,actor,action,target,detail) VALUES(?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), actor, action, target, detail[:1000]),
            )
            db.commit()
    except Exception:
        logger.exception("Could not write V9 database event")


def user_storage_mb(user_id: int) -> float:
    total = 0
    for item in scripts_for(user_id):
        folder = Path(item.folder)
        if not folder.exists():
            continue
        try:
            for f in folder.rglob("*"):
                if f.is_file() and ".venv" not in f.parts and "node_modules" not in f.parts:
                    total += f.stat().st_size
        except OSError:
            pass
    return total / (1024 * 1024)


def storage_limit_mb(user_id: int) -> int:
    if is_owner(user_id):
        return 999999
    return int(user_storage_limits.get(str(user_id), DEFAULT_STORAGE_QUOTA_MB))


def project_setting(item: ScriptProcess) -> dict[str, Any]:
    return project_settings.setdefault(project_key(item), {})


def clean_project_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_. -]+", "_", value).strip()[:80] or "project"


def diagnose_log_text(text: str) -> list[str]:
    checks = [
        ("ModuleNotFoundError", "Missing Python package — repair/reinstall requirements."),
        ("SyntaxError", "Syntax error — inspect the referenced file/line."),
        ("event loop is already running", "Async startup conflict — avoid nesting run_polling() inside asyncio.run()."),
        ("can't start new thread", "Host thread/process resource pressure detected."),
        ("InvalidToken", "Telegram bot token is invalid or revoked."),
        ("Unauthorized", "Authentication/token permission error detected."),
        ("Conflict", "Another instance may already be polling with the same Telegram token."),
        ("PermissionError", "Project tried to access a path/resource without permission."),
        ("No space left on device", "Server disk is full or quota is exhausted."),
        ("MemoryError", "Project ran out of available Python memory."),
        ("Cannot find module", "Missing Node package — tap 📦 Reinstall deps or use /npminstall PROJECT PACKAGE."),
        ("ERR_MODULE_NOT_FOUND", "Missing Node package or wrong import path."),
        ("ERR_REQUIRE_ESM", "ESM/CommonJS mismatch — rename to .mjs or add \"type\": \"module\" to package.json."),
        ("EADDRINUSE", "Port already in use — read the port from the PORT environment variable."),
        ("heap out of memory", "Node ran out of memory — reduce memory use."),
        ("npm ERR!", "npm install failed — check package.json and the runtime log."),
        ("node: not found", "Node.js is missing on the host — owner should send /nodeinstall."),
    ]
    found = [msg for key, msg in checks if key.casefold() in text.casefold()]
    return found or ["No known signature detected. Review the latest runtime log manually."]


def audit(actor: int, action: str, target: str = "", detail: str = "") -> None:
    audit_log.append({
        "time": datetime.now().isoformat(timespec="seconds"),
        "actor": actor,
        "action": action,
        "target": target,
        "detail": detail[:500],
    })
    save_v7_data()
    db_event(actor, action, target, detail)


def project_key(item_or_folder: Any) -> str:
    folder = item_or_folder.folder if hasattr(item_or_folder, "folder") else str(item_or_folder)
    return hashlib.sha256(str(Path(folder).resolve()).encode()).hexdigest()[:24]


def expiry_active(user_id: int) -> bool:
    raw = premium_expiry.get(str(user_id), "")
    if not raw or raw == "lifetime":
        return bool(raw == "lifetime" or user_id in premium_users)
    try:
        return datetime.fromisoformat(raw) > datetime.now()
    except ValueError:
        return False


def expire_plans() -> None:
    changed = False
    for uid, raw in list(premium_expiry.items()):
        if raw in ("", "lifetime"):
            continue
        try:
            if datetime.fromisoformat(raw) <= datetime.now():
                premium_users.discard(int(uid))
                user_plans[uid] = "free"
                premium_expiry.pop(uid, None)
                changed = True
        except (ValueError, TypeError):
            premium_expiry.pop(uid, None)
            changed = True
    if changed:
        save_data(); save_v7_data()


def parse_duration(value: str) -> timedelta | None:
    m = re.fullmatch(r"(\d+)([mhd])", value.strip().lower())
    if not m:
        return None
    amount, unit = int(m.group(1)), m.group(2)
    return {"m": timedelta(minutes=amount), "h": timedelta(hours=amount), "d": timedelta(days=amount)}[unit]


def plan_limits(user_id: int) -> tuple[int, int, int]:
    plan = user_plans.get(str(user_id), "premium" if user_id in premium_users else "free")
    table = {
        "free": (DAILY_UPLOAD_LIMIT, MAX_RUNNING_PER_USER, 128),
        "basic": (5, 3, 256),
        "premium": (25, 10, 512),
        "business": (100, 30, 1024),
        "lifetime": (100, 30, 1024),
    }
    return table.get(plan, table["free"])


def scan_project(folder: Path) -> tuple[str, list[str]]:
    findings: list[str] = []
    py_patterns = {
        "Shell execution": r"(?:os\.system|subprocess\.(?:Popen|run|call))",
        "Dynamic code execution": r"(?:\beval\s*\(|\bexec\s*\(|Function\s*\()",
        "Environment access": r"(?:os\.environ|os\.getenv)",
        "Encoded payload": r"(?:base64\.(?:b64decode|decodebytes))",
        "Reverse-shell indicator": r"(?:/bin/sh|/bin/bash|nc\s+-e|socket\.socket)",
        "Destructive filesystem operation": r"(?:shutil\.rmtree|rm\s+-rf|os\.remove)",
        "Crypto-mining indicator": r"(?:xmrig|stratum\+tcp|monero)",
    }
    js_patterns = {
        "Shell execution": r"child_process",
        "Dynamic code execution": r"(?:\beval\s*\(|\bnew\s+Function\s*\()",
        "Environment access": r"process\.env",
        "Encoded payload": r"Buffer\.from\([^)]*['\"]base64['\"]",
        "Reverse-shell indicator": r"(?:/bin/sh|/bin/bash|nc\s+-e|new\s+net\.Socket)",
        "Destructive filesystem operation": r"(?:fs\.rm(?:dir)?(?:Sync)?\s*\(|rm\s+-rf)",
        "Crypto-mining indicator": r"(?i:xmrig|stratum\+tcp|monero|coinhive)",
    }
    for file in iter_project_files(folder, suffixes=SUPPORTED_EXTS):
        try:
            if file.stat().st_size > 2_000_000:
                continue
            text = file.read_text("utf-8", errors="ignore")
        except OSError:
            continue
        is_js = file.suffix.lower() in NODE_EXTS
        for label, pattern in (js_patterns if is_js else py_patterns).items():
            if re.search(pattern, text, 0 if is_js else re.I):
                findings.append(f"{label}: {file.relative_to(folder)}")
    findings = sorted(set(findings))
    high = any("Reverse" in x or "mining" in x or "Destructive" in x for x in findings)
    risk = "HIGH" if high else ("MEDIUM" if findings else "LOW")
    return risk, findings[:20]


def prepare_compatible_requirements(req: Path, folder: Path) -> tuple[Path, list[str]]:
    """Create a runtime-compatible requirements file without modifying user files."""
    notes: list[str] = []
    try:
        lines = req.read_text("utf-8", errors="replace").splitlines()
    except OSError:
        return req, notes

    # python-telegram-bot 20.x has a known slots/Updater initialization failure on
    # Python 3.13. Keep the user's API generation close while selecting a release
    # that officially added Python 3.13 support.
    if sys.version_info >= (3, 13):
        changed = False
        output: list[str] = []
        ptb_pattern = re.compile(r"^\s*python-telegram-bot(?:\[[^]]+\])?\s*(?:==|~=|<=|<)\s*20(?:\.[^;\s]+)?(.*)$", re.I)
        for line in lines:
            stripped = line.strip()
            match = ptb_pattern.match(stripped)
            if match and not stripped.startswith("#"):
                extras_match = re.match(r"^\s*python-telegram-bot(\[[^]]+\])?", stripped, re.I)
                extras = extras_match.group(1) if extras_match and extras_match.group(1) else ""
                marker = match.group(1) or ""
                output.append(f"python-telegram-bot{extras}>=21.4,<22{marker}")
                changed = True
            else:
                output.append(line)
        if changed:
            compatible = folder / ".elevatex-requirements.txt"
            compatible.write_text("\n".join(output) + "\n", encoding="utf-8")
            notes.append("python-telegram-bot 20.x adjusted to >=21.4,<22 for Python 3.13 compatibility")
            return compatible, notes

    return req, notes

def install_project_dependencies(folder: Path, entry: Path, log_path: Path) -> str:
    notes: list[str] = []
    ext = entry.suffix.lower()

    def write_log(title: str, out: str) -> None:
        with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
            log_file.write(f"\n\n===== {title} =====\n")
            log_file.write(out)
            if out and not out.endswith("\n"):
                log_file.write("\n")

    if ext == ".py":
        req = find_requirements(folder)
        if req and AUTO_INSTALL_DEPENDENCIES:
            install_req, compatibility_notes = prepare_compatible_requirements(req, folder)
            notes.extend(compatibility_notes)
            venv_dir = folder / ".venv"
            subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True, timeout=60)
            py = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            result = subprocess.run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "-r", str(install_req)], cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=DEPENDENCY_TIMEOUT_SECONDS)
            out = result.stdout.decode("utf-8", errors="replace")
            write_log("Dependency Installation", out)
            if result.returncode != 0:
                raise RuntimeError("requirements.txt installation failed; check runtime.log")
            notes.append("Python dependencies installed in private .venv")
    elif ext in NODE_EXTS and AUTO_INSTALL_DEPENDENCIES:
        root = node_project_root(entry, folder)
        if (root / "package.json").exists():
            if (root / "node_modules").exists():
                notes.append("node_modules already present (use Reinstall deps to rebuild)")
            else:
                npm = npm_command()
                if not npm:
                    raise RuntimeError("npm was not found. Owner: send /nodeinstall.")
                result = subprocess.run(
                    npm + ["install", "--omit=dev", "--no-audit", "--no-fund", "--no-progress"],
                    cwd=root, env=node_env(), stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, timeout=DEPENDENCY_TIMEOUT_SECONDS,
                )
                write_log("Node Dependency Installation", result.stdout.decode("utf-8", errors="replace"))
                if result.returncode != 0:
                    raise RuntimeError("npm install failed; check runtime.log")
                notes.append("Node dependencies installed with npm")
        else:
            auto = auto_install_node_imports(root, log_path)
            if auto:
                notes.append(auto)
    return "; ".join(notes) or "No dependency manifest detected"


def project_resources(item: ScriptProcess) -> dict[str, str]:
    result = {"cpu": "N/A", "ram": "N/A", "disk": "0 MB"}
    try:
        total = sum(f.stat().st_size for f in Path(item.folder).rglob("*") if f.is_file())
        result["disk"] = f"{total / 1024 / 1024:.1f} MB"
    except OSError:
        pass
    if item.running and item.proc:
        try:
            import psutil  # optional
            proc = psutil.Process(item.proc.pid)
            result["cpu"] = f"{proc.cpu_percent(interval=0.1):.1f}%"
            result["ram"] = f"{proc.memory_info().rss / 1024 / 1024:.1f} MB"
        except Exception:
            pass
    return result


# ═════════════════════════════════════════════════════════════════════════════
# HOST STATUS / LIVE GRAPH HELPERS (ADDED FOR REAL-TIME METRICS)
# ═════════════════════════════════════════════════════════════════════════════

def make_bar(percent: float, length: int = 10) -> str:
    percent = max(0.0, min(100.0, percent))
    filled = int(length * percent // 100)
    return '█' * filled + '░' * (length - filled)

def get_live_host_status_text() -> str:
    # CPU Usage percentage
    cpu_percent = 0.0
    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=None)
    except Exception:
        pass
    cpu_bar = make_bar(cpu_percent)

    # Memory (RAM) Usage
    mem_percent = 0.0
    mem_used = 0.0
    mem_total = 0.0
    try:
        import psutil
        mem = psutil.virtual_memory()
        mem_percent = mem.percent
        mem_used = round(mem.used / (1024 ** 2), 1)
        mem_total = round(mem.total / (1024 ** 2), 1)
    except Exception:
        pass
    mem_bar = make_bar(mem_percent)

    # Disk Storage Usage
    disk_percent = 0.0
    disk_used = 0.0
    disk_total = 0.0
    try:
        disk = shutil.disk_usage('/')
        disk_percent = (disk.used / disk.total) * 100
        disk_used = round(disk.used / (1024 ** 3), 2)
        disk_total = round(disk.total / (1024 ** 3), 2)
    except Exception:
        pass
    disk_bar = make_bar(disk_percent)

    # Total and running projects count
    all_items = [i for items in running_scripts.values() for i in items]
    active_count_total = sum(i.running for i in all_items)

    text = f"""
〔 🖥️ <b>HOST STATUS (LIVE)</b> 〕 ┄┄┄┄┄┄

💻 <b>CPU Load:</b> {cpu_percent}%
<code>[{cpu_bar}]</code>

🧠 <b>Memory Usage:</b> {mem_used} MB / {mem_total} MB ({mem_percent}%)
<code>[{mem_bar}]</code>

💾 <b>Disk Storage:</b> {disk_used} GB / {disk_total} GB ({disk_percent:.1f}%)
<code>[{disk_bar}]</code>

🐍 <b>Python:</b> {platform.python_version()}
🐧 <b>OS:</b> {platform.system()} ({platform.release()})
📂 <b>Total Projects:</b> {len(all_items)} (Active: {active_count_total})
⏱ <b>Uptime:</b> {uptime()}

⚡ <b>Powered by XP OBAID</b> ⚡
"""
    return text.strip()


async def live_host_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    text = get_live_host_status_text()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh Live Metrics", callback_data="host:refresh_live")]
    ])
    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


# ═════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def esc(value: Any) -> str:
    return html.escape(str(value))


def premium_box(title: str, lines: list[str]) -> str:
    """Render the requested premium Telegram frame."""
    body = "\n".join(f"┃ {line}" if line else "┃" for line in lines)
    footer = globals().get("brand_footer", "")
    footer_line = f"\n┃ {esc(footer)}" if footer else ""
    return (
        f"<b>╭━━〔 {esc(title)} 〕━━┈⊷</b>\n"
        f"{body}{footer_line}\n"
        f"<b>╰━━━━━━━━━━━━━━━┈⊷</b>"
    )


def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def is_approved(user_id: int) -> bool:
    return is_owner(user_id) or user_id in approved_users


def is_premium(user_id: int) -> bool:
    expire_plans()
    return is_owner(user_id) or (user_id in premium_users and expiry_active(user_id))


def plan_name(user_id: int) -> str:
    if is_owner(user_id):
        return "👑 Owner"
    if is_premium(user_id):
        plan = user_plans.get(str(user_id), "premium").title()
        return f"💎 {plan}"
    if is_approved(user_id):
        return "✅ Approved"
    return "🔒 Guest"


def get_credits(user_id: int) -> int:
    return int(user_credits.get(str(user_id), DEFAULT_CREDITS))


def set_credits(user_id: int, value: int) -> None:
    user_credits[str(user_id)] = max(0, int(value))
    save_data()


def get_stat(user_id: int) -> dict[str, Any]:
    key = str(user_id)
    if key not in user_stats:
        user_stats[key] = {
            "uploads_total": 0,
            "uploads_today": 0,
            "last_upload_date": "",
            "last_active": "",
            "username": "",
            "first_name": "",
        }
    return user_stats[key]


def touch_user(user: Any) -> None:
    stat = get_stat(user.id)
    stat["last_active"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stat["username"] = user.username or ""
    stat["first_name"] = user.first_name or ""
    save_data()


def reset_daily(user_id: int) -> None:
    stat = get_stat(user_id)
    today = date.today().isoformat()
    if stat.get("last_upload_date") != today:
        stat["last_upload_date"] = today
        stat["uploads_today"] = 0
        save_data()


def daily_limit(user_id: int) -> int:
    if is_owner(user_id):
        return 999_999
    if str(user_id) in custom_daily_limits:
        return custom_daily_limits[str(user_id)]
    return plan_limits(user_id)[0]


def running_limit(user_id: int) -> int:
    if is_owner(user_id):
        return 999_999
    if str(user_id) in custom_running_limits:
        return custom_running_limits[str(user_id)]
    return plan_limits(user_id)[1]


def user_folder(user_id: int) -> Path:
    folder = DOWNLOADS_DIR / str(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def clean_filename(name: str) -> str:
    name = Path(name).name
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120] or "upload.bin"


def clean_project_name(name: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f<>]", "", name).strip()
    return cleaned[:40]


def uptime(started_at: float = START_TIME) -> str:
    seconds = max(0, int(time.time() - started_at))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def scripts_for(user_id: int) -> list[ScriptProcess]:
    return running_scripts.setdefault(user_id, [])


def active_count(user_id: int) -> int:
    return sum(item.running for item in scripts_for(user_id))


def find_project(
    user_id: int,
    target: str,
) -> tuple[int, ScriptProcess] | None:
    target_folded = target.casefold()
    for index, item in enumerate(scripts_for(user_id)):
        if (
            item.display_name.casefold() == target_folded
            or Path(item.entry_file).name.casefold() == target_folded
        ):
            return index, item
    return None


def safe_remove_folder(folder_value: str) -> None:
    folder = Path(folder_value)
    try:
        folder.resolve().relative_to(DOWNLOADS_DIR.resolve())
    except (ValueError, OSError):
        raise ValueError("Unsafe project path")
    shutil.rmtree(folder, ignore_errors=True)


def safe_extract_zip(zip_path: Path, destination: Path) -> None:
    max_uncompressed = MAX_ZIP_EXPANDED_MB * 1024 * 1024
    total = 0

    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            total += info.file_size
            if total > max_uncompressed:
                raise ValueError(
                    f"ZIP expands beyond {MAX_ZIP_EXPANDED_MB} MB"
                )

            target = (destination / info.filename).resolve()
            try:
                target.relative_to(destination.resolve())
            except ValueError:
                raise ValueError("Unsafe ZIP path detected")

            file_type = (info.external_attr >> 16) & 0o170000
            if file_type == 0o120000:
                raise ValueError("ZIP symlinks are not allowed")

        archive.extractall(destination)


def detect_entry(folder: Path) -> Path | None:
    """Pick the file to run: Python (.py) or Node.js (.js/.mjs/.cjs)."""
    ranked: list[tuple[int, int, int, str, Path]] = []
    for f in iter_project_files(folder, suffixes=PY_EXTS):
        if f.name in PY_PRIORITY:
            ranked.append((_depth(f, folder), PY_PRIORITY.index(f.name) + 1, 0, str(f), f))
    pkg_hit = package_json_entry(folder)
    if pkg_hit:
        ranked.append((_depth(pkg_hit[1], folder), 50 if find_requirements(folder) else 0, 1, str(pkg_hit[0]), pkg_hit[0]))
    for f in iter_project_files(folder, suffixes=NODE_EXTS):
        if f.name in JS_PRIORITY:
            ranked.append((_depth(f, folder), JS_PRIORITY.index(f.name) + 1, 1, str(f), f))
    if ranked:
        return min(ranked, key=lambda r: r[:4])[4]
    for suffixes in (PY_EXTS, NODE_EXTS):
        files = sorted(iter_project_files(folder, suffixes=suffixes),
                       key=lambda x: (_depth(x, folder), str(x)))
        if files:
            return files[0]
    return None


def run_command(entry: Path) -> list[str] | None:
    ext = entry.suffix.lower()
    if ext in NODE_EXTS:
        node = node_path()
        if not node:
            raise ValueError(
                "Node.js is not installed on this host. Owner: send /nodeinstall "
                "(portable install, no root needed)."
            )
        return [node, str(entry)]
    if ext != ".py":
        return None
    private_py = None
    for parent in (entry.parent, *entry.parents):
        candidate = parent / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if candidate.exists():
            private_py = candidate
            break
    py = str(private_py) if private_py else sys.executable
    return [py, "-u", str(entry)]


def spawn_script(
    item: ScriptProcess | None,
    entry: Path,
    folder: Path,
    log_path: Path,
) -> ScriptProcess:
    cmd = run_command(entry)
    if not cmd:
        raise ValueError("Unsupported project entry")

    log_handle = open(
        log_path,
        "a",
        encoding="utf-8",
        errors="replace",
        buffering=1,
    )
    log_handle.write(
        f"\n===== Launch {datetime.now().isoformat(timespec='seconds')} =====\n"
    )

    is_node = entry.suffix.lower() in NODE_EXTS
    env = node_env() if is_node else os.environ.copy()
    env.update({"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
    env.update(project_envs.get(project_key(folder), {}))

    preexec_fn = None
    if os.name != "nt" and ENFORCE_RESOURCE_LIMITS:
        def apply_limits() -> None:
            try:
                import resource
                settings = project_settings.get(project_key(folder), {})
                ram_mb = int(settings.get("ram_mb", DEFAULT_PROJECT_RAM_MB))
                max_bytes = max(128, ram_mb) * 1024 * 1024
                if entry.suffix.lower() == ".py" and ENFORCE_ADDRESS_SPACE_LIMIT:
                    resource.setrlimit(resource.RLIMIT_AS, (max_bytes, max_bytes))
                if PROJECT_PROCESS_LIMIT > 0:
                    resource.setrlimit(
                        resource.RLIMIT_NPROC,
                        (PROJECT_PROCESS_LIMIT, PROJECT_PROCESS_LIMIT),
                    )
                if PROJECT_OPEN_FILES_LIMIT > 0:
                    resource.setrlimit(
                        resource.RLIMIT_NOFILE,
                        (PROJECT_OPEN_FILES_LIMIT, PROJECT_OPEN_FILES_LIMIT),
                    )
            except Exception:
                pass
        preexec_fn = apply_limits

    proc = subprocess.Popen(
        cmd,
        cwd=str(node_project_root(entry, folder) if is_node else folder),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env=env,
        start_new_session=(os.name != "nt"),
        close_fds=(os.name != "nt"),
        preexec_fn=preexec_fn,
    )

    if item is None:
        item = ScriptProcess(
            display_name=entry.name,
            entry_file=str(entry),
            folder=str(folder),
            log_path=str(log_path),
            proc=proc,
        )
    else:
        item.proc = proc
        item.started_at = time.time()
    item.desired_running = True

    save_projects()
    return item


def kill_process(item: ScriptProcess) -> bool:
    if not item.running:
        return True

    assert item.proc is not None
    proc = item.proc

    try:
        if os.name == "nt":
            proc.terminate()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)

        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                proc.kill()
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)

        save_projects()
        return True

    except Exception:
        logger.exception("Failed stopping PID %s", proc.pid)
        return False


async def edit_message(
    query: Any,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            disable_web_page_preview=True,
        )
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


# ═════════════════════════════════════════════════════════════════════════════
# PREMIUM UI
# ═════════════════════════════════════════════════════════════════════════════

def main_menu(user_id: int) -> ReplyKeyboardMarkup:
    rows = [
        [
            KeyboardButton("🚀 ʜᴏsᴛ ᴘʀᴏᴊᴇᴄᴛ"),
            KeyboardButton("📂 ᴍʏ ᴘʀᴏᴊᴇᴄᴛs"),
        ],
        [
            KeyboardButton("🧾 ʟɪᴠᴇ ʟᴏɢs"),
            KeyboardButton("⚙️ ᴄᴏɴᴛʀᴏʟs"),
        ],
        [
            KeyboardButton("💳 ᴡᴀʟʟᴇᴛ"),
            KeyboardButton("📊 ᴀᴄᴄᴏᴜɴᴛ"),
        ],
        [
            KeyboardButton("💎 ᴘʟᴀɴs"),
            KeyboardButton("🆘 sᴜᴘᴘᴏʀᴛ"),
        ],
    ]

    if is_owner(user_id):
        rows.append([KeyboardButton("👑 ᴀᴅᴍɪɴ ᴄᴇNTᴇʀ"), KeyboardButton("🖥 ʟɪᴠᴇ sᴛᴀᴛs")])
    else:
        rows.append([KeyboardButton("🖥 ʟɪᴠᴇ sᴛᴀᴛs")])

    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
    )


def home_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📢 Channel",
                    url="https://t.me/example_channel",
                ),
                InlineKeyboardButton(
                    "👥 Community",
                    url="https://t.me/example_group",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🆘 Contact Owner",
                    url="https://t.me/example_owner",
                )
            ],
        ]
    )


def join_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📢 Join Channel",
                    url="https://t.me/example_channel",
                )
            ],
            [
                InlineKeyboardButton(
                    "👥 Join Group",
                    url="https://t.me/example_group",
                )
            ],
            [
                InlineKeyboardButton(
                    "✅ Verify Membership",
                    callback_data="join:check",
                )
            ],
        ]
    )


def project_list_buttons(user_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for index, item in enumerate(scripts_for(user_id)):
        icon = "🟢" if item.running else "🔴"
        kind = "🟩" if Path(item.entry_file).suffix.lower() in NODE_EXTS else "🐍"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{icon} {kind} {item.display_name[:26]}",
                    callback_data=f"project:view:{index}",
                )
            ]
        )

    if scripts_for(user_id):
        rows.append(
            [
                InlineKeyboardButton("▶️ Start All", callback_data="myproj:startall"),
                InlineKeyboardButton("🛑 Stop All", callback_data="myproj:stopall"),
                InlineKeyboardButton("🔁 Restart All", callback_data="myproj:restartall"),
            ]
        )
    rows.append([InlineKeyboardButton("🔄 Refresh", callback_data="project:list")])
    return InlineKeyboardMarkup(rows)


def project_control_buttons(
    index: int,
    running: bool,
) -> InlineKeyboardMarkup:
    primary = (
        InlineKeyboardButton("🛑 Stop", callback_data=f"project:stop:{index}")
        if running
        else InlineKeyboardButton("▶️ Start", callback_data=f"project:start:{index}")
    )

    def b(label: str, action: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(label, callback_data=f"project:{action}:{index}")

    return InlineKeyboardMarkup(
        [
            [primary, b("🔁 Restart", "restart")],
            [b("🧾 Logs", "logs"), b("📄 Log File", "logfile")],
            [b("🔄 Update Code", "update"), b("📦 Reinstall deps", "deps")],
            [b("🩺 Diagnose", "diag"), b("📊 Stats", "stats")],
            [b("💾 Backup", "backup"), b("🔐 Env", "env")],
            [b("♻️ Auto-restart on/off", "autorestart")],
            [b("✏️ Rename", "rename"), b("🗑 Delete", "delete")],
            [InlineKeyboardButton("⬅️ Projects", callback_data="project:list")],
        ]
    )


def admin_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📊 Overview",
                    callback_data="admin:overview",
                ),
                InlineKeyboardButton(
                    "👥 Users",
                    callback_data="admin:users",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🚀 Processes",
                    callback_data="admin:processes",
                ),
                InlineKeyboardButton(
                    "💎 Premium",
                    callback_data="admin:premium",
                ),
            ],
            [
                InlineKeyboardButton(
                    "💳 Credits",
                    callback_data="admin:credits",
                ),
                InlineKeyboardButton(
                    "🚫 Banned",
                    callback_data="admin:banned",
                ),
            ],
            [
                InlineKeyboardButton(
                    "▶️ Start Everything",
                    callback_data="admin:startall",
                ),
                InlineKeyboardButton(
                    "🧨 Stop Everything",
                    callback_data="admin:stopall",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔐 Force Join",
                    callback_data="admin:forcejoin",
                ),
                InlineKeyboardButton(
                    "🛠 Maintenance",
                    callback_data="admin:maintenance",
                ),
            ],
            [
                InlineKeyboardButton("💓 Keep Alive", callback_data="admin:keepalive"),
                InlineKeyboardButton("🖥 Host Status", callback_data="admin:hoststatus"),
            ],
            [
                InlineKeyboardButton("🛡 Security", callback_data="admin:security"),
                InlineKeyboardButton("💾 Backup", callback_data="admin:backupinfo"),
            ],
            [
                InlineKeyboardButton(
                    "🧹 Cleanup",
                    callback_data="admin:cleanup",
                ),
                InlineKeyboardButton(
                    "📖 Commands",
                    callback_data="admin:commands",
                ),
            ],
            [InlineKeyboardButton("🟩 Node.js", callback_data="admin:node")],
            [InlineKeyboardButton("❌ Close", callback_data="admin:close")],
        ]
    )


def home_text(user_id: int) -> str:
    reset_daily(user_id)
    stat = get_stat(user_id)
    return premium_box(
        f"⚡ {BRAND_NAME.upper()} ⚡",
        [
            "<i>ᴘʀᴇᴍɪᴜᴍ ᴛᴇʟᴇɢʀᴀᴍ ʜᴏsᴛɪɴɢ</i>",
            "",
            f"👤 <b>ᴘʟᴀɴ</b>  •  {esc(plan_name(user_id))}",
            f"🆔 <b>ᴜsᴇʀ ɪᴅ</b>  •  <code>{user_id}</code>",
            f"🟢 <b>ʀᴜɴɴɪɴɢ</b>  •  <code>{active_count(user_id)}/{running_limit(user_id)}</code>",
            f"📤 <b>ᴜᴘʟᴏᴀᴅs</b>  •  <code>{stat['uploads_today']}/{daily_limit(user_id)}</code>",
            f"💳 <b>ᴄʀᴇᴅɪᴛs</b>  •  <code>{get_credits(user_id)}</code>",
            f"⏱ <b>ᴜᴘᴛɪᴍᴇ</b>  •  <code>{uptime()}</code>",
            "",
            "📦 Send <code>.py</code> / <code>.js</code> or a <code>.zip</code> (Python or Node.js) to deploy.",
        ],
    )


def projects_text(user_id: int) -> str:
    items = scripts_for(user_id)

    if not items:
        return (
            "<b>📂 ᴍʏ ᴘʀᴏᴊᴇᴄᴛs</b>\n\n"
            "No hosted projects found.\n"
            "Send a <code>.py</code> / <code>.js</code> file "
            "or a <code>.zip</code> (Python or Node.js)."
        )

    lines = ["<b>📂 ᴍʏ ᴘʀᴏᴊᴇᴄᴛs</b>", ""]

    for index, item in enumerate(items, start=1):
        status = (
            "🟢 Online"
            if item.running
            else f"🔴 Offline ({esc(item.exit_code)})"
        )

        lines.append(
            f"<b>{index}. {esc(item.display_name)}</b>\n"
            f"   {status}\n"
            f"   PID: <code>{esc(item.pid)}</code>"
        )

    return "\n\n".join(lines)


def admin_overview() -> str:
    all_items = [
        item
        for items in running_scripts.values()
        for item in items
    ]
    active = sum(item.running for item in all_items)

    return (
        f"<b>╭── 👑 {esc(BRAND_NAME)} Admin ──╮</b>\n"
        f"<b>╰────────────────────────╯</b>\n\n"
        f"👥 Approved: <code>{len(approved_users)}</code>\n"
        f"💎 Premium: <code>{len(premium_users)}</code>\n"
        f"🚫 Banned: <code>{len(banned_users)}</code>\n"
        f"💳 Credit wallets: <code>{len(user_credits)}</code>\n"
        f"🧩 Registered projects: <code>{len(all_items)}</code>\n"
        f"🟢 Active processes: <code>{active}</code>\n"
        f"🔐 Force Join: "
        f"<code>{'ON' if FORCE_JOIN_ENABLED else 'OFF'}</code>\n"
        f"🛠 Maintenance: "
        f"<code>{'ON' if maintenance_mode else 'OFF'}</code>\n"
        f"🐍 Runtime: <code>Python {platform.python_version()}</code>\n"
        f"💓 Keep Alive: <code>{'ON' if keepalive_enabled else 'OFF'}</code> / <code>{keepalive_interval}s</code>\n"
        f"🌐 Health Port: <code>{HEALTH_PORT}</code>\n"
        f"⏱ Uptime: <code>{uptime()}</code>"
    )


def admin_commands_text() -> str:
    return (
        "<b>📖 Owner Commands</b>\n\n"
        "<code>/admin</code> — Admin panel\n"
        "<code>/approve USER_ID</code> — Approve user\n"
        "<code>/revoke USER_ID</code> — Remove access\n"
        "<code>/premium USER_ID</code> — Give premium\n"
        "<code>/unpremium USER_ID</code> — Remove premium\n"
        "<code>/ban USER_ID</code> — Ban and stop projects\n"
        "<code>/unban USER_ID</code> — Unban user\n"
        "<code>/userinfo USER_ID</code> — User information\n"
        "<code>/addcredits USER_ID AMOUNT</code>\n"
        "<code>/setcredits USER_ID AMOUNT</code>\n"
        "<code>/takecredits USER_ID AMOUNT</code>\n"
        "<code>/credits USER_ID</code>\n"
        "<code>/setdaily USER_ID LIMIT</code>\n"
        "<code>/setrunning USER_ID LIMIT</code>\n"
        "<code>/broadcast MESSAGE</code>\n"
        "<code>/maintenance on|off</code>\n"
        "<code>/startall</code> — Start all stopped projects\n"
        "<code>/stopalladmin</code> — Stop all projects\n"
        "<code>/cleanup</code> — Remove missing/stopped registry\n"
        "<code>/backup</code> — Download bot data backup\n"
        "<code>/install PACKAGE</code> — Safe owner package installer\n"
        "<code>/installed</code> — List Python packages\n"
        "<code>/nodestatus</code> — Node.js status\n"
        "<code>/nodeinstall</code> — Install portable Node.js\n"
        "<code>/keepalive [on|off]</code> — Keep-alive status/toggle\n"
        "<code>/setkeepalive URL [30-45]</code> — Set ping URL/interval\n"
        "<code>/hoststats</code> — Server health & resources\n"
        "<code>/security</code> — Security/runtime status\n"
        "<code>/finduser QUERY</code> — Find stored user\n"
        "<code>/allprojects</code> — All hosted projects\n"
        "<code>/restartall</code> — Restart all registered projects\n\n"
        "<b>User Commands</b>\n\n"
        "<code>/start</code>\n"
        "<code>/projects</code>\n"
        "<code>/logs [PROJECT]</code>\n"
        "<code>/restart PROJECT</code>\n"
        "<code>/stop PROJECT</code>\n"
        "<code>/delete PROJECT</code>\n"
        "<code>/rename OLD NEW</code>\n"
        "<code>/credits</code>\n"
        "<code>/skip</code>"
    )


# ═════════════════════════════════════════════════════════════════════════════
# ACCESS CONTROL
# ═════════════════════════════════════════════════════════════════════════════

async def check_join(
    user_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    if not FORCE_JOIN_ENABLED or is_owner(user_id):
        return True

    return True


async def guard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return False

    touch_user(user)

    if user.id in banned_users:
        await message.reply_text("🚫 Your access has been suspended.")
        return False

    if maintenance_mode and not is_owner(user.id):
        await message.reply_text(
            "🛠 Service maintenance is active. Try again later."
        )
        return False

    if not is_approved(user.id):
        await message.reply_text(
            "<b>🔐 Access Required</b>\n\n"
            "Send the access password or use "
            "<code>/request reason</code>.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_buttons(),
        )
        return False

    if not await check_join(user.id, context):
        await message.reply_text(
            "<b>🔒 Membership Required</b>\n\n"
            "Join both communities, then verify.",
            parse_mode=ParseMode.HTML,
            reply_markup=join_buttons(),
        )
        return False

    return True


def owner_only(update: Update) -> bool:
    return bool(
        update.effective_user
        and is_owner(update.effective_user.id)
    )


def admin_or_owner(update: Update) -> bool:
    if not update.effective_user:
        return False
    uid = update.effective_user.id
    return is_owner(uid) or str(uid) in admin_roles


def admin_role(user_id: int) -> str:
    return "owner" if is_owner(user_id) else admin_roles.get(str(user_id), "none")


# ═════════════════════════════════════════════════════════════════════════════
# BASIC COMMANDS
# ═════════════════════════════════════════════════════════════════════════════

async def start_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user = update.effective_user

    if not user:
        return

    touch_user(user)

    if user.id in banned_users:
        await update.effective_message.reply_text(
            "🚫 Your access has been suspended."
        )
        return

    if not is_approved(user.id):
        await update.effective_message.reply_text(
            f"<b>Welcome to {esc(BRAND_NAME)}</b>\n\n"
            "Premium access is required.\n"
            "Send the access password or use "
            "<code>/request reason</code>.",
            parse_mode=ParseMode.HTML,
            reply_markup=home_buttons(),
        )
        return

    if not await check_join(user.id, context):
        await update.effective_message.reply_text(
            "<b>🔒 Complete membership verification</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=join_buttons(),
        )
        return

    await update.effective_message.reply_text(
        home_text(user.id),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(user.id),
        disable_web_page_preview=True,
    )


async def help_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await guard(update, context):
        return

    text = (
        "<b>ℹ️ ElevateX Host Help</b>\n\n"
        "<code>/projects</code> — Open projects\n"
        "<code>/logs [name]</code> — Latest logs\n"
        "<code>/restart NAME</code> — Restart project\n"
        "<code>/stop NAME</code> — Stop project\n"
        "<code>/delete NAME</code> — Delete stopped project\n"
        "<code>/rename OLD NEW</code> — Rename project\n"
        "<code>/credits</code> — Wallet\n"
        "<code>/skip</code> — Skip project name prompt\n"
        "<code>/npminstall NAME PACKAGE…</code> — Add npm packages to a Node project\n"
        "<code>/cancel</code> — Cancel a pending update\n\n"
        "You can also use the premium menu buttons."
    )

    if is_owner(update.effective_user.id):
        text += "\n\n" + admin_commands_text()

    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def request_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    user = update.effective_user

    if not user or user.id in banned_users:
        return

    reason = " ".join(context.args).strip() or "No reason provided"

    buttons = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Approve",
                    callback_data=f"request:approve:{user.id}",
                ),
                InlineKeyboardButton(
                    "❌ Reject",
                    callback_data=f"request:reject:{user.id}",
                ),
            ]
        ]
    )

    await context.bot.send_message(
        OWNER_ID,
        f"<b>📩 New Access Request</b>\n\n"
        f"👤 {esc(user.full_name)}\n"
        f"🔗 @{esc(user.username or 'not_set')}\n"
        f"🆔 <code>{user.id}</code>\n"
        f"📝 {esc(reason)}",
        parse_mode=ParseMode.HTML,
        reply_markup=buttons,
    )

    await update.effective_message.reply_text(
        "✅ Request sent to the owner."
    )


async def projects_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await guard(update, context):
        return

    uid = update.effective_user.id

    await update.effective_message.reply_text(
        projects_text(uid),
        parse_mode=ParseMode.HTML,
        reply_markup=project_list_buttons(uid),
    )


async def logs_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await guard(update, context):
        return

    uid = update.effective_user.id
    items = scripts_for(uid)

    if not items:
        await update.effective_message.reply_text(
            "🧾 No logs are available."
        )
        return

    item = items[-1]

    if context.args:
        found = find_project(uid, " ".join(context.args))
        if not found:
            await update.effective_message.reply_text(
                "❌ Project not found."
            )
            return
        _, item = found

    path = Path(item.log_path)
    content = (
        path.read_text("utf-8", errors="replace")[-MAX_LOG_CHARS:]
        if path.exists()
        else "No output yet."
    )

    await update.effective_message.reply_text(
        f"<b>🧾 {esc(item.display_name)}</b>\n\n"
        f"<pre>{esc(content)}</pre>",
        parse_mode=ParseMode.HTML,
    )


async def credits_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    caller = update.effective_user.id
    uid = caller

    if context.args:
        if not is_owner(caller):
            await update.effective_message.reply_text(
                "❌ Owner only."
            )
            return

        try:
            uid = int(context.args[0])
        except ValueError:
            await update.effective_message.reply_text(
                "❌ Invalid user ID."
            )
            return

    await update.effective_message.reply_text(
        "<b>💳 Credit Wallet</b>\n\n"
        f"User ID: <code>{uid}</code>\n"
        f"Plan: {esc(plan_name(uid))}\n"
        f"Credits: <code>{get_credits(uid)}</code>\n"
        f"Upload cost: <code>{CREDIT_PER_UPLOAD}</code>",
        parse_mode=ParseMode.HTML,
    )


async def skip_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    uid = update.effective_user.id

    if uid not in pending_project_names:
        await update.effective_message.reply_text(
            "ℹ️ No project name is pending."
        )
        return

    pending_project_names.pop(uid, None)
    await update.effective_message.reply_text(
        "✅ Original project name kept."
    )


async def rename_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await guard(update, context):
        return

    if len(context.args) < 2:
        await update.effective_message.reply_text(
            "Usage: /rename OLD_NAME NEW_NAME"
        )
        return

    uid = update.effective_user.id
    old_name = context.args[0]
    new_name = clean_project_name(" ".join(context.args[1:]))

    if not new_name:
        await update.effective_message.reply_text(
            "❌ Invalid new project name."
        )
        return

    found = find_project(uid, old_name)

    if not found:
        await update.effective_message.reply_text(
            "❌ Project not found."
        )
        return

    _, item = found
    item.display_name = new_name
    save_projects()

    await update.effective_message.reply_text(
        f"✅ Project renamed to <b>{esc(new_name)}</b>.",
        parse_mode=ParseMode.HTML,
    )


async def stop_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await guard(update, context):
        return

    if not context.args:
        await projects_cmd(update, context)
        return

    uid = update.effective_user.id
    found = find_project(uid, " ".join(context.args))

    if not found:
        await update.effective_message.reply_text(
            "❌ Project not found."
        )
        return

    _, item = found
    item.desired_running = False
    project_setting(item)["autostart"] = False
    ok = kill_process(item)
    save_projects(); save_v7_data()

    await update.effective_message.reply_text(
        (
            f"🛑 Stopped <b>{esc(item.display_name)}</b>."
            if ok
            else "❌ Could not stop project."
        ),
        parse_mode=ParseMode.HTML,
    )


async def restart_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await guard(update, context):
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /restart PROJECT_NAME"
        )
        return

    uid = update.effective_user.id
    found = find_project(uid, " ".join(context.args))

    if not found:
        await update.effective_message.reply_text(
            "❌ Project not found."
        )
        return

    _, item = found

    async with lock_for(uid):
        if item.running:
            kill_process(item)

        item.restarts += 1

        try:
            spawn_script(
                item,
                Path(item.entry_file),
                Path(item.folder),
                Path(item.log_path),
            )
            await asyncio.sleep(0.5)

            await update.effective_message.reply_text(
                (
                    f"✅ Restarted <b>{esc(item.display_name)}</b>.\n"
                    f"PID: <code>{item.pid}</code>"
                    if item.running
                    else "❌ Project exited after restart."
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            await update.effective_message.reply_text(
                f"❌ Restart failed: <code>{esc(exc)}</code>",
                parse_mode=ParseMode.HTML,
            )


async def delete_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await guard(update, context):
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /delete PROJECT_NAME"
        )
        return

    uid = update.effective_user.id
    found = find_project(uid, " ".join(context.args))

    if not found:
        await update.effective_message.reply_text(
            "❌ Project not found."
        )
        return

    index, item = found

    if item.running:
        await update.effective_message.reply_text(
            "⚠️ Stop the project before deleting it."
        )
        return

    key = project_key(item)
    safe_remove_folder(item.folder)
    scripts_for(uid).pop(index)
    project_settings.pop(key, None)
    project_envs.pop(key, None)
    save_projects(); save_v7_data()

    await update.effective_message.reply_text(
        f"🗑 Deleted <b>{esc(item.display_name)}</b>.",
        parse_mode=ParseMode.HTML,
    )


# ═════════════════════════════════════════════════════════════════════════════
# OWNER COMMANDS
# ═════════════════════════════════════════════════════════════════════════════

async def admin_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not admin_or_owner(update):
        await update.effective_message.reply_text("❌ Admin only.")
        return

    await update.effective_message.reply_text(
        admin_overview(),
        parse_mode=ParseMode.HTML,
        reply_markup=admin_buttons(),
    )


async def approve_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not owner_only(update):
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /approve USER_ID"
        )
        return

    try:
        uid = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text(
            "❌ Invalid user ID."
        )
        return

    approved_users.add(uid)
    banned_users.discard(uid)
    user_credits.setdefault(str(uid), DEFAULT_CREDITS)
    save_data()

    await update.effective_message.reply_text(
        f"✅ Approved <code>{uid}</code>.",
        parse_mode=ParseMode.HTML,
    )

    try:
        await context.bot.send_message(
            uid,
            f"✅ Access approved for {BRAND_NAME}. Send /start.",
        )
    except TelegramError:
        pass


async def revoke_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not owner_only(update):
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /revoke USER_ID"
        )
        return

    try:
        uid = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text(
            "❌ Invalid user ID."
        )
        return

    approved_users.discard(uid)
    premium_users.discard(uid)
    save_data()

    await update.effective_message.reply_text(
        f"✅ Access revoked from <code>{uid}</code>.",
        parse_mode=ParseMode.HTML,
    )


async def premium_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not owner_only(update):
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /premium USER_ID"
        )
        return

    try:
        uid = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text(
            "❌ Invalid user ID."
        )
        return

    approved_users.add(uid)
    premium_users.add(uid)
    banned_users.discard(uid)

    set_credits(
        uid,
        get_credits(uid) + PREMIUM_BONUS_CREDITS,
    )
    save_data()

    await update.effective_message.reply_text(
        f"<b>💎 Premium Activated</b>\n\n"
        f"User: <code>{uid}</code>\n"
        f"Bonus credits: <code>{PREMIUM_BONUS_CREDITS}</code>\n"
        f"Daily uploads: <code>{daily_limit(uid)}</code>\n"
        f"Running limit: <code>{running_limit(uid)}</code>",
        parse_mode=ParseMode.HTML,
    )

    try:
        await context.bot.send_message(
            uid,
            f"💎 Premium activated on {BRAND_NAME}.\n"
            f"Credits: {get_credits(uid)}\n"
            f"Daily uploads: {daily_limit(uid)}\n"
            f"Running limit: {running_limit(uid)}",
        )
    except TelegramError:
        pass


async def unpremium_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not owner_only(update):
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /unpremium USER_ID"
        )
        return

    try:
        uid = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text(
            "❌ Invalid user ID."
        )
        return

    premium_users.discard(uid)
    save_data()

    await update.effective_message.reply_text(
        f"✅ Premium removed from <code>{uid}</code>.",
        parse_mode=ParseMode.HTML,
    )


async def ban_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not owner_only(update):
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /ban USER_ID"
        )
        return

    try:
        uid = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text(
            "❌ Invalid user ID."
        )
        return

    banned_users.add(uid)
    approved_users.discard(uid)
    premium_users.discard(uid)

    stopped = 0
    for item in scripts_for(uid):
        if item.running and kill_process(item):
            stopped += 1

    save_data()

    await update.effective_message.reply_text(
        f"🚫 Banned <code>{uid}</code>.\n"
        f"Stopped projects: <code>{stopped}</code>",
        parse_mode=ParseMode.HTML,
    )


async def unban_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not owner_only(update):
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /unban USER_ID"
        )
        return

    try:
        uid = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text(
            "❌ Invalid user ID."
        )
        return

    banned_users.discard(uid)
    save_data()

    await update.effective_message.reply_text(
        f"✅ Unbanned <code>{uid}</code>.",
        parse_mode=ParseMode.HTML,
    )


async def addcredits_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not owner_only(update):
        return

    if len(context.args) != 2:
        await update.effective_message.reply_text(
            "Usage: /addcredits USER_ID AMOUNT"
        )
        return

    try:
        uid = int(context.args[0])
        amount = int(context.args[1])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text(
            "❌ Invalid user ID or amount."
        )
        return

    set_credits(uid, get_credits(uid) + amount)

    await update.effective_message.reply_text(
        f"✅ Added <code>{amount}</code> credits to "
        f"<code>{uid}</code>.\n"
        f"Total: <code>{get_credits(uid)}</code>",
        parse_mode=ParseMode.HTML,
    )


async def setcredits_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not owner_only(update):
        return

    if len(context.args) != 2:
        await update.effective_message.reply_text(
            "Usage: /setcredits USER_ID AMOUNT"
        )
        return

    try:
        uid = int(context.args[0])
        amount = int(context.args[1])
        if amount < 0:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text(
            "❌ Invalid user ID or amount."
        )
        return

    set_credits(uid, amount)

    await update.effective_message.reply_text(
        f"✅ Credits for <code>{uid}</code> set to "
        f"<code>{amount}</code>.",
        parse_mode=ParseMode.HTML,
    )


async def takecredits_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not owner_only(update):
        return

    if len(context.args) != 2:
        await update.effective_message.reply_text(
            "Usage: /takecredits USER_ID AMOUNT"
        )
        return

    try:
        uid = int(context.args[0])
        amount = int(context.args[1])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text(
            "❌ Invalid user ID or amount."
        )
        return

    set_credits(uid, get_credits(uid) - amount)

    await update.effective_message.reply_text(
        f"✅ Removed <code>{amount}</code> credits from "
        f"<code>{uid}</code>.\n"
        f"Remaining: <code>{get_credits(uid)}</code>",
        parse_mode=ParseMode.HTML,
    )


async def setdaily_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not owner_only(update):
        return

    if len(context.args) != 2:
        await update.effective_message.reply_text(
            "Usage: /setdaily USER_ID LIMIT"
        )
        return

    try:
        uid = int(context.args[0])
        limit = int(context.args[1])
        if limit < 0:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text(
            "❌ Invalid input."
        )
        return

    custom_daily_limits[str(uid)] = limit
    save_data()

    await update.effective_message.reply_text(
        f"✅ Daily upload limit for <code>{uid}</code> "
        f"set to <code>{limit}</code>.",
        parse_mode=ParseMode.HTML,
    )


async def setrunning_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not owner_only(update):
        return

    if len(context.args) != 2:
        await update.effective_message.reply_text(
            "Usage: /setrunning USER_ID LIMIT"
        )
        return

    try:
        uid = int(context.args[0])
        limit = int(context.args[1])
        if limit < 1:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text(
            "❌ Invalid input."
        )
        return

    custom_running_limits[str(uid)] = limit
    save_data()

    await update.effective_message.reply_text(
        f"✅ Running limit for <code>{uid}</code> "
        f"set to <code>{limit}</code>.",
        parse_mode=ParseMode.HTML,
    )


async def userinfo_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not owner_only(update):
        return

    if not context.args:
        await update.effective_message.reply_text(
            "Usage: /userinfo USER_ID"
        )
        return

    try:
        uid = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text(
            "❌ Invalid user ID."
        )
        return

    stat = get_stat(uid)

    await update.effective_message.reply_text(
        "<b>👤 User Information</b>\n\n"
        f"ID: <code>{uid}</code>\n"
        f"Username: @{esc(stat.get('username') or 'not_set')}\n"
        f"Name: {esc(stat.get('first_name') or 'Unknown')}\n"
        f"Plan: {esc(plan_name(uid))}\n"
        f"Approved: <code>{'YES' if is_approved(uid) else 'NO'}</code>\n"
        f"Premium: <code>{'YES' if is_premium(uid) else 'NO'}</code>\n"
        f"Banned: <code>{'YES' if uid in banned_users else 'NO'}</code>\n"
        f"Credits: <code>{get_credits(uid)}</code>\n"
        f"Running: <code>{active_count(uid)}/{running_limit(uid)}</code>\n"
        f"Uploads today: "
        f"<code>{stat.get('uploads_today', 0)}/{daily_limit(uid)}</code>\n"
        f"Total uploads: <code>{stat.get('uploads_total', 0)}</code>\n"
        f"Last active: <code>{esc(stat.get('last_active') or 'Unknown')}</code>",
        parse_mode=ParseMode.HTML,
    )


async def broadcast_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not owner_only(update):
        return

    body = " ".join(context.args).strip()

    if not body:
        await update.effective_message.reply_text(
            "Usage: /broadcast MESSAGE"
        )
        return

    targets = approved_users | premium_users | {OWNER_ID}
    sent = 0
    failed = 0

    status = await update.effective_message.reply_text(
        "📣 Sending broadcast…"
    )

    for uid in targets:
        try:
            await context.bot.send_message(
                uid,
                f"<b>📣 {esc(BRAND_NAME)}</b>\n\n{esc(body)}",
                parse_mode=ParseMode.HTML,
            )
            sent += 1
            await asyncio.sleep(0.05)
        except (Forbidden, TelegramError):
            failed += 1

    await status.edit_text(
        f"✅ Sent: {sent}\n❌ Failed: {failed}"
    )


async def maintenance_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    global maintenance_mode

    if not owner_only(update):
        return

    if (
        not context.args
        or context.args[0].lower() not in {"on", "off"}
    ):
        await update.effective_message.reply_text(
            "Usage: /maintenance on|off"
        )
        return

    maintenance_mode = context.args[0].lower() == "on"
    save_data()

    await update.effective_message.reply_text(
        f"🛠 Maintenance "
        f"{'ON' if maintenance_mode else 'OFF'}"
    )


async def startall_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not owner_only(update):
        return

    started = 0
    failed = 0

    for uid, items in running_scripts.items():
        async with lock_for(uid):
            for item in items:
                if item.running:
                    continue

                try:
                    spawn_script(
                        item,
                        Path(item.entry_file),
                        Path(item.folder),
                        Path(item.log_path),
                    )
                    await asyncio.sleep(0.15)

                    if item.running:
                        started += 1
                    else:
                        failed += 1

                except Exception:
                    logger.exception(
                        "Failed starting %s",
                        item.display_name,
                    )
                    failed += 1

    await update.effective_message.reply_text(
        f"▶️ Start All Complete\n\n"
        f"✅ Started: {started}\n"
        f"❌ Failed: {failed}"
    )


async def stopalladmin_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not owner_only(update):
        return

    stopped = 0

    for items in running_scripts.values():
        for item in items:
            if item.running and kill_process(item):
                stopped += 1

    await update.effective_message.reply_text(
        f"🧨 Stopped <code>{stopped}</code> projects.",
        parse_mode=ParseMode.HTML,
    )


async def cleanup_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not owner_only(update):
        return

    removed = 0

    for uid, items in list(running_scripts.items()):
        kept: list[ScriptProcess] = []

        for item in items:
            folder = Path(item.folder)
            entry = Path(item.entry_file)

            if folder.exists() and entry.exists():
                kept.append(item)
            else:
                removed += 1

        running_scripts[uid] = kept

    save_projects()

    await update.effective_message.reply_text(
        f"🧹 Cleanup complete.\n"
        f"Removed missing project records: <code>{removed}</code>",
        parse_mode=ParseMode.HTML,
    )


async def install_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Install Python packages without invoking a shell."""
    if not owner_only(update):
        await update.effective_message.reply_text("❌ Owner only.")
        return

    raw = " ".join(context.args).strip()
    if not raw:
        await update.effective_message.reply_text(
            premium_box(
                "📦 ᴘᴀᴄᴋᴀɢᴇ ɪɴsᴛᴀʟʟᴇʀ",
                [
                    "<b>Python:</b> <code>/install beautifulsoup4</code>",
                    "<b>Python:</b> <code>/install pip3 install requests</code>",
                    "",
                    "🔐 Owner-only • no shell execution",
                ],
            ),
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        args = shlex.split(raw)
    except ValueError as exc:
        await update.effective_message.reply_text(f"❌ Invalid syntax: {exc}")
        return

    if args[:2] in (["pip", "install"], ["pip3", "install"]):
        packages = args[2:]
    elif len(args) >= 4 and args[0] in {"python", "python3"} and args[1:4] == ["-m", "pip", "install"]:
        packages = args[4:]
    elif args and args[0].lower() in {"npm", "node", "yarn", "pnpm"}:
        await update.effective_message.reply_text("ℹ️ Node packages are installed per project: /npminstall PROJECT PACKAGE")
        return
    else:
        packages = args

    package_pattern = re.compile(r"^[A-Za-z0-9@._/+:-]+(?:[<>=!~]{1,2}[A-Za-z0-9.*+_-]+)?$")
    if not packages or len(packages) > 15 or any(not package_pattern.fullmatch(x) for x in packages):
        await update.effective_message.reply_text(
            "❌ Only valid package names/version specs are accepted. Shell operators and arbitrary flags are blocked."
        )
        return

    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *packages]

    status = await update.effective_message.reply_text(
        premium_box("⏳ ɪɴsᴛᴀʟʟɪɴɢ", [f"📦 <code>{esc(' '.join(packages))}</code>", "Please check the result below."]),
        parse_mode=ParseMode.HTML,
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(BASE_DIR), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=INSTALL_TIMEOUT_SECONDS)
        output = stdout.decode("utf-8", errors="replace")[-MAX_INSTALL_OUTPUT_CHARS:]
        title = "✅ ɪɴsᴛᴀʟʟᴇᴅ" if proc.returncode == 0 else "❌ ɪɴsᴛᴀʟʟ ғᴀɪʟᴇᴅ"
        await status.edit_text(
            premium_box(title, [f"📦 <code>{esc(' '.join(packages))}</code>", "", f"<pre>{esc(output or 'No output')}</pre>"]),
            parse_mode=ParseMode.HTML,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        await status.edit_text(premium_box("⏱ ᴛɪᴍᴇᴏᴜᴛ", [f"Installation exceeded {INSTALL_TIMEOUT_SECONDS} seconds."]), parse_mode=ParseMode.HTML)
    except FileNotFoundError:
        await status.edit_text("❌ Package manager is not installed on this panel.")
    except Exception as exc:
        logger.exception("Package installation failed")
        await status.edit_text(f"❌ Installation error: <code>{esc(exc)}</code>", parse_mode=ParseMode.HTML)


async def installed_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not owner_only(update):
        await update.effective_message.reply_text("❌ Owner only.")
        return
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pip", "list", "--format=columns",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode("utf-8", errors="replace")[-MAX_INSTALL_OUTPUT_CHARS:]
    await update.effective_message.reply_text(
        premium_box("📚 ɪɴsᴛᴀʟʟᴇᴅ ᴘᴀᴄᴋᴀɢᴇs", [f"<pre>{esc(output)}</pre>"]),
        parse_mode=ParseMode.HTML,
    )


async def backup_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not owner_only(update):
        return

    save_data()
    save_projects()

    files_sent = 0

    for path in (DATA_FILE, PROJECTS_FILE):
        if path.exists():
            await update.effective_message.reply_document(
                document=InputFile(str(path)),
                caption=f"📦 {BRAND_NAME} backup: {path.name}",
            )
            files_sent += 1

    if not files_sent:
        await update.effective_message.reply_text(
            "❌ No backup files available."
        )


# ═════════════════════════════════════════════════════════════════════════════
# FILE HOSTING
# ═════════════════════════════════════════════════════════════════════════════

async def handle_document(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not await guard(update, context):
        return

    user_id = update.effective_user.id
    document = update.effective_message.document

    if not document:
        return

    waiting = pending_updates.get(user_id)
    if waiting:
        pending_updates.pop(user_id, None)
        if time.time() - waiting[1] < 300 and waiting[0] in scripts_for(user_id):
            await handle_project_update(update, context, waiting[0])
            return

    async with lock_for(user_id):
        reset_daily(user_id)
        stat = get_stat(user_id)

        if stat["uploads_today"] >= daily_limit(user_id):
            await update.effective_message.reply_text(
                "⚠️ Your daily upload limit has been reached."
            )
            return

        if (
            not is_premium(user_id)
            and get_credits(user_id) < CREDIT_PER_UPLOAD
        ):
            await update.effective_message.reply_text(
                "💳 Not enough credits."
            )
            return

        if active_count(user_id) >= running_limit(user_id):
            await update.effective_message.reply_text(
                f"⚠️ Running limit reached: "
                f"{running_limit(user_id)}."
            )
            return

        used_mb = user_storage_mb(user_id)
        quota_mb = storage_limit_mb(user_id)
        incoming_mb = (document.file_size or 0) / (1024 * 1024)
        if not is_owner(user_id) and used_mb + incoming_mb > quota_mb:
            await update.effective_message.reply_text(
                f"💾 Storage quota exceeded. Used: {used_mb:.1f} MB / {quota_mb} MB."
            )
            return

        filename = clean_filename(
            document.file_name or "project"
        )
        suffix = Path(filename).suffix.lower()

        if suffix not in SUPPORTED_EXTS | {".zip"}:
            await update.effective_message.reply_text(
                "❌ Send a .py, .js, .mjs or .cjs file, or a .zip with a Python or Node.js project."
            )
            return

        size = document.file_size or 0

        if size > MAX_FILE_MB * 1024 * 1024:
            await update.effective_message.reply_text(
                f"❌ Maximum file size is {MAX_FILE_MB} MB."
            )
            return

        progress = await update.effective_message.reply_text(
            f"<b>📥 Upload Received</b>\n\n"
            f"📄 <code>{esc(filename)}</code>\n"
            f"📦 Size: <code>{size / (1024 * 1024):.2f} MB</code>\n\n"
            "Preparing premium hosting environment…",
            parse_mode=ParseMode.HTML,
        )

        stamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S_%f"
        )
        folder = (
            user_folder(user_id)
            / f"{stamp}_{Path(filename).stem}"
        )
        folder.mkdir(parents=True)
        uploaded = folder / filename

        try:
            tg_file = await context.bot.get_file(
                document.file_id
            )
            await tg_file.download_to_drive(str(uploaded))

            await progress.edit_text(
                "📦 Inspecting project structure…"
            )

            if suffix == ".zip":
                safe_extract_zip(uploaded, folder)
                uploaded.unlink(missing_ok=True)
                entry = detect_entry(folder)
            else:
                entry = uploaded

            if not entry:
                raise ValueError(
                    "No runnable entry found. ZIP needs main.py/bot.py/app.py or package.json/index.js/bot.js."
                )

            log_path = folder / "runtime.log"

            risk, findings = scan_project(folder) if SECURITY_SCAN_ENABLED else ("DISABLED", [])
            if risk == "HIGH" and not is_owner(user_id):
                raise ValueError("High-risk code detected: " + "; ".join(findings[:3]))

            dependency_note = await asyncio.to_thread(install_project_dependencies, folder, entry, log_path)

            item = spawn_script(
                None,
                entry,
                folder,
                log_path,
            )
            scripts_for(user_id).append(item)
            save_projects()

            await asyncio.sleep(LAUNCH_CHECK_SECONDS)

            if not item.running:
                error = (
                    log_path.read_text(
                        "utf-8",
                        errors="replace",
                    )[-MAX_LOG_CHARS:]
                    if log_path.exists()
                    else "No error output."
                )

                scripts_for(user_id).remove(item)
                save_projects()
                safe_remove_folder(item.folder)

                await progress.edit_text(
                    f"<b>❌ Launch Failed</b>\n\n"
                    f"<pre>{esc(error)}</pre>",
                    parse_mode=ParseMode.HTML,
                )
                return

            if not is_premium(user_id):
                set_credits(
                    user_id,
                    get_credits(user_id)
                    - CREDIT_PER_UPLOAD,
                )

            stat["uploads_today"] += 1
            stat["uploads_total"] += 1
            stat["last_upload_date"] = (
                date.today().isoformat()
            )
            save_data()

            pending_project_names[user_id] = item

            await progress.edit_text(
                f"<b>╭── ✅ Hosting Started ──╮</b>\n"
                f"<b>╰────────────────────╯</b>\n\n"
                f"🧩 <b>Entry:</b> "
                f"<code>{esc(entry.name)}</code>\n"
                f"⚙️ <b>Runtime:</b> {runtime_label(entry)}\n"
                f"🆔 <b>PID:</b> "
                f"<code>{item.pid}</code>\n"
                f"🟢 <b>Status:</b> Online\n"
                f"🛡 <b>Scan:</b> <code>{esc(risk)}</code>\n"
                f"📦 <b>Dependencies:</b> {esc(dependency_note)}\n"
                f"💳 <b>Credits:</b> "
                f"<code>{get_credits(user_id)}</code>\n\n"
                "<b>Now send a custom project name.</b>\n"
                "Example: <code>My WhatsApp Bot</code>\n\n"
                "Or send <code>/skip</code> to keep the file name.",
                parse_mode=ParseMode.HTML,
                reply_markup=project_control_buttons(
                    len(scripts_for(user_id)) - 1,
                    True,
                ),
            )

        except Exception as exc:
            logger.exception("Upload failed")
            shutil.rmtree(folder, ignore_errors=True)

            await progress.edit_text(
                f"<b>❌ Upload Failed</b>\n\n"
                f"<code>{esc(exc)}</code>",
                parse_mode=ParseMode.HTML,
            )


# ═════════════════════════════════════════════════════════════════════════════
# TEXT HANDLER
# ═════════════════════════════════════════════════════════════════════════════

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    text = (
        update.effective_message.text or ""
    ).strip()
    user = update.effective_user

    if not user:
        return

    touch_user(user)

    if user.id in pending_updates and text.startswith(("🚀", "📂", "🧾", "⚙️", "💳", "📊", "💎", "🆘", "👑", "🖥")):
        pending_updates.pop(user.id, None)

    waiting_env = pending_env.get(user.id)
    if waiting_env:
        pending_env.pop(user.id, None)
        if time.time() - waiting_env[1] < 300 and waiting_env[0] in scripts_for(user.id) and not text.startswith(("🚀", "📂", "🧾", "⚙️", "💳", "📊", "💎", "🆘", "👑", "🖥")):
            saved: list[str] = []
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if key.startswith("export "):
                    key = key[7:].strip()
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key):
                    project_envs.setdefault(project_key(waiting_env[0]), {})[key] = value.strip().strip("'\"")
                    saved.append(key)
            try:
                await update.effective_message.delete()
            except TelegramError:
                pass
            if saved:
                save_v7_data()
                await update.effective_message.chat.send_message(
                    "✅ Saved: " + ", ".join(f"<code>{esc(k)}</code>" for k in saved)
                    + "\n🔒 Your message was deleted for safety. Restart the project to apply.",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await update.effective_message.chat.send_message(
                    "❌ No valid KEY=VALUE lines found. Tap 🔐 Env again and retry."
                )
            return

    if user.id in pending_project_names:
        item = pending_project_names.pop(user.id)
        project_name = clean_project_name(text)

        if not project_name:
            await update.effective_message.reply_text(
                "❌ Invalid name. Send a valid project name."
            )
            pending_project_names[user.id] = item
            return

        item.display_name = project_name
        save_projects()

        await update.effective_message.reply_text(
            f"<b>✅ Project Name Saved</b>\n\n"
            f"Project: <b>{esc(project_name)}</b>\n"
            f"Status: {'🟢 Online' if item.running else '🔴 Offline'}",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(user.id),
        )
        return

    if not is_approved(user.id):
        if ACCESS_PASSWORD and text == ACCESS_PASSWORD:
            approved_users.add(user.id)
            banned_users.discard(user.id)
            user_credits.setdefault(
                str(user.id),
                DEFAULT_CREDITS,
            )
            save_data()

            await update.effective_message.reply_text(
                "✅ Access activated. Send /start."
            )
        else:
            await update.effective_message.reply_text(
                "🔐 Invalid password. Use /request for access."
            )
        return

    if text == "🚀 ʜᴏsᴛ ᴘʀᴏᴊᴇᴄᴛ":
        await update.effective_message.reply_text(
            "<b>🚀 Host New Project</b>\n\n"
            "Send one of these formats:\n"
            "• <code>.py</code> — Python script\n"
            "• <code>.js</code> / <code>.mjs</code> — Node.js script\n"
            "• <code>.zip</code> — full project\n\n"
            "Python ZIP: <code>main.py</code>, <code>bot.py</code>, "
            "<code>app.py</code> or <code>server.py</code> "
            "(+ <code>requirements.txt</code>).\n"
            "Node ZIP: <code>package.json</code> or <code>index.js</code>, "
            "<code>bot.js</code>, <code>app.js</code> "
            "(npm packages install automatically).",
            parse_mode=ParseMode.HTML,
        )

    elif text in {"📂 ᴍʏ ᴘʀᴏᴊᴇᴄᴛs", "⚙️ ᴄᴏɴᴛʀᴏʟs"}:
        await projects_cmd(update, context)

    elif text == "🧾 ʟɪᴠᴇ ʟᴏɢs":
        await logs_cmd(update, context)

    elif text == "💳 ᴡᴀʟʟᴇᴛ":
        await credits_cmd(update, context)

    elif text == "📊 ᴀᴄᴄᴏᴜɴᴛ":
        await update.effective_message.reply_text(
            home_text(user.id),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    elif text == "💎 ᴘʟᴀɴs":
        await update.effective_message.reply_text(
            f"<b>💎 {esc(BRAND_NAME)} Plans</b>\n\n"
            f"<b>✅ Approved</b>\n"
            f"• Daily uploads: <code>{DAILY_UPLOAD_LIMIT}</code>\n"
            f"• Running projects: <code>{MAX_RUNNING_PER_USER}</code>\n"
            f"• Upload cost: <code>{CREDIT_PER_UPLOAD}</code> credit\n\n"
            f"<b>💎 Premium</b>\n"
            f"• Daily uploads: "
            f"<code>{PREMIUM_DAILY_UPLOAD_LIMIT}</code>\n"
            f"• Running projects: "
            f"<code>{PREMIUM_MAX_RUNNING_PER_USER}</code>\n"
            f"• Uploads do not consume credits\n"
            f"• Premium bonus: "
            f"<code>{PREMIUM_BONUS_CREDITS}</code> credits",
            parse_mode=ParseMode.HTML,
        )

    elif text == "🆘 sᴜᴘᴘᴏʀᴛ":
        await update.effective_message.reply_text(
            f"<b>🆘 sᴜᴘᴘᴏʀᴛ</b>\n\n"
            f"Owner: @{esc(OWNER_USERNAME)}\n"
            f"Channel: {esc(MAIN_CHANNEL_LINK)}\n"
            f"Group: {esc(SUPPORT_GROUP_LINK)}\n"
            f"Direct: {esc(SUPPORT_LINK)}",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    elif text == "👑 ᴀᴅᴍɪɴ ᴄᴇɴᴛᴇʀ":
        await admin_cmd(update, context)

    elif text == "🖥 ʟɪᴠᴇ sᴛᴀᴛs":
        await live_host_status_cmd(update, context)

    else:
        await update.effective_message.reply_text(
            "Use the premium menu or upload a project file."
        )


# ═════════════════════════════════════════════════════════════════════════════
# CALLBACK HANDLER
# ═════════════════════════════════════════════════════════════════════════════

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    await query.answer()

    uid = query.from_user.id
    data = query.data or ""

    if data == "host:refresh_live":
        new_text = get_live_host_status_text()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh Live Metrics", callback_data="host:refresh_live")]
        ])
        try:
            await query.edit_message_text(text=new_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        except Exception:
            pass
        return

    if data == "join:check":
        if await check_join(uid, context):
            await edit_message(
                query,
                "✅ Membership verified. Send /start.",
            )
        else:
            await edit_message(
                query,
                "❌ Membership could not be verified.",
                join_buttons(),
            )
        return

    if data.startswith("request:"):
        if not is_owner(uid):
            await query.answer(
                "Owner only",
                show_alert=True,
            )
            return

        _, action, raw_id = data.split(":")
        target = int(raw_id)

        if action == "approve":
            approved_users.add(target)
            banned_users.discard(target)
            user_credits.setdefault(
                str(target),
                DEFAULT_CREDITS,
            )
            save_data()

            try:
                await context.bot.send_message(
                    target,
                    f"✅ Access approved for {BRAND_NAME}. "
                    "Send /start.",
                )
            except TelegramError:
                pass

            await edit_message(
                query,
                f"✅ Approved <code>{target}</code>.",
            )

        else:
            try:
                await context.bot.send_message(
                    target,
                    "❌ Your access request was rejected.",
                )
            except TelegramError:
                pass

            await edit_message(
                query,
                f"❌ Rejected <code>{target}</code>.",
            )

        return

    if data.startswith("admin:"):
        if not (is_owner(uid) or str(uid) in admin_roles):
            await query.answer("Admin only", show_alert=True); return

        action = data.split(":", 1)[1]
        if not is_owner(uid) and action not in {"close","overview","users","premium","credits","banned","processes","analytics","watchdog","panelreminder","codes","hoststatus","security","backupinfo"}:
            await query.answer("Owner required for this action", show_alert=True); return

        if action == "close":
            await edit_message(
                query,
                "✅ Admin Center closed.",
            )

        elif action == "overview":
            await edit_message(
                query,
                admin_overview(),
                admin_buttons(),
            )

        elif action == "users":
            rows = []

            for user_id in sorted(approved_users):
                stat = get_stat(user_id)
                rows.append(
                    f"• <code>{user_id}</code> "
                    f"@{esc(stat.get('username') or 'not_set')}"
                )

            await edit_message(
                query,
                "<b>👥 Approved Users</b>\n\n"
                + ("\n".join(rows[:80]) or "None"),
                admin_buttons(),
            )

        elif action == "premium":
            rows = [
                f"• <code>{x}</code>"
                for x in sorted(premium_users)
            ]

            await edit_message(
                query,
                "<b>💎 Premium Users</b>\n\n"
                + ("\n".join(rows) or "None"),
                admin_buttons(),
            )

        elif action == "credits":
            rows = [
                f"• <code>{uid}</code>: "
                f"<code>{amount}</code>"
                for uid, amount in sorted(
                    user_credits.items()
                )
            ]

            await edit_message(
                query,
                "<b>💳 Credit Wallets</b>\n\n"
                + ("\n".join(rows[:100]) or "None"),
                admin_buttons(),
            )

        elif action == "banned":
            rows = [
                f"• <code>{x}</code>"
                for x in sorted(banned_users)
            ]

            await edit_message(
                query,
                "<b>🚫 Banned Users</b>\n\n"
                + ("\n".join(rows) or "None"),
                admin_buttons(),
            )

        elif action == "processes":
            rows = []

            for user_id, items in running_scripts.items():
                for item in items:
                    rows.append(
                        f"• <code>{user_id}</code> — "
                        f"{esc(item.display_name)} "
                        f"{'🟢' if item.running else '🔴'}"
                    )

            await edit_message(
                query,
                "<b>🚀 Hosted Projects</b>\n\n"
                + ("\n".join(rows[:100]) or "None"),
                admin_buttons(),
            )

        elif action == "startall":
            started = 0
            failed = 0

            for user_id, items in running_scripts.items():
                async with lock_for(user_id):
                    for item in items:
                        if item.running:
                            continue

                        try:
                            spawn_script(
                                item,
                                Path(item.entry_file),
                                Path(item.folder),
                                Path(item.log_path),
                            )
                            await asyncio.sleep(0.1)

                            if item.running:
                                started += 1
                            else:
                                failed += 1

                        except Exception:
                            logger.exception(
                                "Start-all failure"
                            )
                            failed += 1

            await edit_message(
                query,
                f"▶️ Start Everything Complete\n\n"
                f"✅ Started: <code>{started}</code>\n"
                f"❌ Failed: <code>{failed}</code>",
                admin_buttons(),
            )

        elif action == "stopall":
            stopped = 0

            for items in running_scripts.values():
                for item in items:
                    if item.running and kill_process(item):
                        stopped += 1

            await edit_message(
                query,
                f"🧨 Stopped <code>{stopped}</code> projects.",
                admin_buttons(),
            )

        elif action == "forcejoin":
            await edit_message(
                query,
                "<b>🔐 Force Join Status</b>\n\n"
                f"Status: "
                f"<code>{'ON' if FORCE_JOIN_ENABLED else 'OFF'}</code>\n"
                f"Channel: <code>{esc(MAIN_CHANNEL_USERNAME)}</code>\n"
                f"Group: <code>{esc(SUPPORT_GROUP_USERNAME)}</code>\n\n"
                "To change it, edit "
                "<code>FORCE_JOIN_ENABLED</code> in main.py.\n"
                "The bot must be admin in both chats.",
                admin_buttons(),
            )

        elif action == "maintenance":
            global maintenance_mode
            maintenance_mode = not maintenance_mode
            save_data()

            await edit_message(
                query,
                admin_overview(),
                admin_buttons(),
            )

        elif action == "keepalive":
            await edit_message(query, keepalive_text(), admin_buttons())

        elif action == "hoststatus":
            await edit_message(query, host_stats_text(), admin_buttons())

        elif action == "security":
            await edit_message(query, security_text(), admin_buttons())

        elif action == "backupinfo":
            backups = sorted(BACKUPS_DIR.glob("elevatex_backup_*.zip"), key=lambda x: x.stat().st_mtime, reverse=True)
            lines = [f"Automatic interval: <code>{BACKUP_INTERVAL_HOURS}h</code>", f"Stored backups: <code>{len(backups)}</code>", "Use <code>/backup</code> to download current data."]
            if backups: lines.append(f"Latest: <code>{esc(backups[0].name)}</code>")
            await edit_message(query, premium_box("💾 ʙᴀᴄᴋᴜᴘs", lines), admin_buttons())

        elif action == "analytics":
            total_projects=sum(len(x) for x in running_scripts.values()); running=sum(i.running for x in running_scripts.values() for i in x)
            await edit_message(query,premium_box("📈 ᴀɴᴀʟʏᴛɪᴄs",[f"Users: <code>{len(user_stats)}</code>",f"Projects: <code>{total_projects}</code>",f"Running: <code>{running}</code>",f"Codes: <code>{len(redeem_codes)}</code>"]),admin_buttons())

        elif action == "watchdog":
            await edit_message(query,premium_box("🛡 ᴡᴀᴛᴄʜᴅᴏɢ",[f"Status: <code>{'ON' if watchdog_enabled else 'OFF'}</code>",f"Interval: <code>{watchdog_interval}s</code>",f"Restarts: <code>{watchdog_restarts}</code>"]),admin_buttons())

        elif action == "panelreminder":
            await edit_message(query,premium_box("⏰ ᴘᴀɴᴇʟ ʀᴇᴍɪɴᴅᴇʀ",[f"Status: <code>{'ON' if panel_reminder_enabled else 'OFF'}</code>",f"Cycle: <code>{PANEL_REMINDER_HOURS}h</code>","Use <code>/panelvisited</code> after visiting."]),admin_buttons())

        elif action == "panelvisited":
            if not is_owner(uid):
                await query.answer("Owner only",show_alert=True); return
            global panel_last_confirmed_at, panel_last_reminder_at
            panel_last_confirmed_at=time.time(); panel_last_reminder_at=0.0; save_v7_data()
            await edit_message(query,premium_box("✅ ᴘᴀɴᴇʟ ᴠɪsɪᴛ",["Visit confirmed.","Next reminder: <code>3 days</code>"]),admin_buttons())

        elif action == "codes":
            rows=[f"• <code>{esc(c)}</code> — {'OFF' if r.get('disabled') else 'ON'}" for c,r in list(redeem_codes.items())[:25]]
            await edit_message(query,premium_box("🎟 ᴄᴏᴅᴇs",rows or ["No redeem codes."]),admin_buttons())

        elif action == "cleanup":
            removed = 0

            for user_id, items in list(
                running_scripts.items()
            ):
                kept = []

                for item in items:
                    if (
                        Path(item.folder).exists()
                        and Path(item.entry_file).exists()
                    ):
                        kept.append(item)
                    else:
                        removed += 1

                running_scripts[user_id] = kept

            save_projects()

            await edit_message(
                query,
                f"🧹 Removed <code>{removed}</code> "
                "missing project records.",
                admin_buttons(),
            )

        elif action == "node":
            await edit_message(query, node_status_text(), node_buttons())

        elif action == "nodeinstall":
            await edit_message(query, "⏳ Downloading Node.js… this can take a minute.")
            try:
                ver = await asyncio.to_thread(install_node_runtime)
                audit(uid, "node_install", ver)
                await edit_message(query, node_status_text(), node_buttons())
            except Exception as exc:
                await edit_message(
                    query,
                    f"❌ Node install failed: <code>{esc(exc)}</code>",
                    node_buttons(),
                )

        elif action == "commands":
            await edit_message(
                query,
                admin_commands_text(),
                admin_buttons(),
            )

        return

    if not is_approved(uid) or uid in banned_users:
        await query.answer(
            "Access restricted",
            show_alert=True,
        )
        return

    if data == "project:list":
        await edit_message(
            query,
            projects_text(uid),
            project_list_buttons(uid),
        )
        return

    if data.startswith("myproj:"):
        bulk = data.split(":", 1)[1]
        done = skipped = 0
        async with lock_for(uid):
            for it in scripts_for(uid):
                try:
                    if bulk == "stopall":
                        it.desired_running = False
                        project_setting(it)["autostart"] = False
                        if it.running and kill_process(it):
                            done += 1
                    elif bulk in {"startall", "restartall"}:
                        if it.running:
                            if bulk == "startall":
                                continue
                            kill_process(it)
                        elif active_count(uid) >= running_limit(uid):
                            skipped += 1
                            continue
                        it.restarts += 1
                        spawn_script(it, Path(it.entry_file), Path(it.folder), Path(it.log_path))
                        done += 1
                except Exception:
                    logger.exception("Bulk action failed")
                    skipped += 1
        save_projects(); save_v7_data()
        await query.answer(
            f"✅ {done} done" + (f" • ⚠️ {skipped} skipped" if skipped else ""),
            show_alert=True,
        )
        await edit_message(query, projects_text(uid), project_list_buttons(uid))
        return

    parts = data.split(":")

    if len(parts) != 3 or parts[0] != "project":
        return

    action = parts[1]

    try:
        index = int(parts[2])
        item = scripts_for(uid)[index]
    except (ValueError, IndexError):
        await query.answer(
            "Project not found",
            show_alert=True,
        )
        return

    async with lock_for(uid):
        if action == "view":
            status = (
                "🟢 Online"
                if item.running
                else f"🔴 Offline ({esc(item.exit_code)})"
            )

            text = (
                f"<b>🧩 {esc(item.display_name)}</b>\n\n"
                f"Status: {status}\n"
                f"Entry: "
                f"<code>{esc(Path(item.entry_file).name)}</code>\n"
                f"Runtime: {runtime_label(Path(item.entry_file))}\n"
                f"Auto-restart: <code>{'ON' if item.auto_restart else 'OFF'}</code>\n"
                f"PID: <code>{esc(item.pid)}</code>\n"
                f"Uptime: "
                f"<code>{uptime(item.started_at) if item.running else '—'}</code>\n"
                f"Restarts: <code>{item.restarts}</code>"
            )

            await edit_message(
                query,
                text,
                project_control_buttons(
                    index,
                    item.running,
                ),
            )

        elif action == "stop":
            item.desired_running = False
            project_setting(item)["autostart"] = False
            ok = kill_process(item)
            save_projects(); save_v7_data()

            await edit_message(
                query,
                (
                    f"🛑 Stopped <b>{esc(item.display_name)}</b>."
                    if ok
                    else "❌ Could not stop project."
                ),
                project_control_buttons(index, False),
            )

        elif action in {"start", "restart"}:
            if item.running:
                kill_process(item)

            item.restarts += 1

            try:
                spawn_script(
                    item,
                    Path(item.entry_file),
                    Path(item.folder),
                    Path(item.log_path),
                )
                await asyncio.sleep(0.5)

                await edit_message(
                    query,
                    (
                        f"✅ Started "
                        f"<b>{esc(item.display_name)}</b>.\n"
                        f"PID: <code>{item.pid}</code>"
                        if item.running
                        else "❌ Project exited after launch."
                    ),
                    project_control_buttons(
                        index,
                        item.running,
                    ),
                )

            except Exception as exc:
                await edit_message(
                    query,
                    f"❌ Start failed: "
                    f"<code>{esc(exc)}</code>",
                    project_control_buttons(
                        index,
                        False,
                    ),
                )

        elif action == "logs":
            path = Path(item.log_path)
            content = (
                path.read_text(
                    "utf-8",
                    errors="replace",
                )[-MAX_LOG_CHARS:]
                if path.exists()
                else "No output."
            )

            await edit_message(
                query,
                f"<b>🧾 {esc(item.display_name)}</b>\n\n"
                f"<pre>{esc(content)}</pre>",
                project_control_buttons(
                    index,
                    item.running,
                ),
            )

        elif action == "logfile":
            path = Path(item.log_path)

            if path.exists():
                await context.bot.send_document(
                    uid,
                    InputFile(str(path)),
                    caption=f"Logs: {item.display_name}",
                )
                await query.answer("Log file sent")
            else:
                await query.answer(
                    "Log file not found",
                    show_alert=True,
                )

        elif action == "update":
            pending_updates[uid] = (item, time.time())
            await query.message.reply_text(
                f"<b>🔄 Update Code — {esc(item.display_name)}</b>\n\n"
                "Send the new <code>.py</code> / <code>.js</code> file or a <code>.zip</code> within 5 minutes.\n"
                "• Same file names are overwritten\n"
                "• Env variables, settings and installed packages are kept\n"
                "• A running project is restarted automatically\n\n"
                "Send /cancel to abort.",
                parse_mode=ParseMode.HTML,
            )

        elif action == "deps":
            if item.running:
                await query.answer("Stop the project first", show_alert=True)
                return
            await query.answer("Rebuilding dependencies…")
            try:
                note = await asyncio.to_thread(rebuild_project_env, item)
                await query.message.reply_text(
                    f"✅ Dependencies rebuilt.\n<code>{esc(note)}</code>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as exc:
                await query.message.reply_text(
                    f"❌ Rebuild failed: <code>{esc(exc)}</code>",
                    parse_mode=ParseMode.HTML,
                )

        elif action == "diag":
            log = Path(item.log_path)
            text_tail = log.read_text("utf-8", errors="replace")[-12000:] if log.exists() else ""
            await query.message.reply_text(
                premium_box(
                    "🩺 ᴅɪᴀɢɴᴏsᴛɪᴄs",
                    [f"Project: <b>{esc(item.display_name)}</b>"]
                    + [f"• {esc(x)}" for x in diagnose_log_text(text_tail)],
                ),
                parse_mode=ParseMode.HTML,
            )

        elif action == "stats":
            res = project_resources(item)
            await query.message.reply_text(
                premium_box(
                    "📊 ᴘʀᴏᴊᴇᴄᴛ sᴛᴀᴛs",
                    [
                        f"Project: <b>{esc(item.display_name)}</b>",
                        f"Runtime: {runtime_label(Path(item.entry_file))}",
                        f"Status: {'🟢 Online' if item.running else '🔴 Offline'}",
                        f"CPU: <code>{res['cpu']}</code>",
                        f"RAM: <code>{res['ram']}</code>",
                        f"Disk: <code>{res['disk']}</code>",
                        f"Uptime: <code>{uptime(item.started_at) if item.running else '—'}</code>",
                        f"Restarts: <code>{item.restarts}</code>",
                    ],
                ),
                parse_mode=ParseMode.HTML,
            )

        elif action == "backup":
            await query.answer("Preparing backup…")
            try:
                out = await asyncio.to_thread(build_project_backup, uid, item)
                await context.bot.send_document(
                    uid, InputFile(str(out)), caption=f"💾 Backup: {item.display_name}"
                )
            except Exception as exc:
                await query.message.reply_text(
                    f"❌ Backup failed: <code>{esc(exc)}</code>", parse_mode=ParseMode.HTML
                )

        elif action == "env":
            envs = project_envs.get(project_key(item), {})
            lines = [f"<code>{esc(k)}</code> = ••••••••" for k in envs] or ["No variables configured"]
            await edit_message(
                query,
                premium_box("🔐 ᴇɴᴠɪʀᴏɴᴍᴇɴᴛ", [f"Project: <b>{esc(item.display_name)}</b>", ""] + lines),
                InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("➕ Add / Update", callback_data=f"project:envadd:{index}")],
                        [InlineKeyboardButton("🗑 Clear all", callback_data=f"project:envclear:{index}")],
                        [InlineKeyboardButton("⬅️ Back", callback_data=f"project:view:{index}")],
                    ]
                ),
            )

        elif action == "envadd":
            pending_env[uid] = (item, time.time())
            await query.message.reply_text(
                "<b>🔐 Add variables</b>\n\n"
                "Send one or more lines like:\n"
                "<code>BOT_TOKEN=123456:ABC</code>\n"
                "<code>API_KEY=xyz</code>\n\n"
                "Your message is deleted right after it is saved.",
                parse_mode=ParseMode.HTML,
            )

        elif action == "envclear":
            project_envs.pop(project_key(item), None)
            save_v7_data()
            await query.answer("All variables removed", show_alert=True)

        elif action == "autorestart":
            item.auto_restart = not item.auto_restart
            item.restarts = 0
            save_projects()
            await query.answer(
                f"♻️ Auto-restart: {'ON' if item.auto_restart else 'OFF'}", show_alert=True
            )
            await edit_message(
                query,
                f"<b>🧩 {esc(item.display_name)}</b>\n\n"
                f"Auto-restart: <code>{'ON' if item.auto_restart else 'OFF'}</code>",
                project_control_buttons(index, item.running),
            )

        elif action == "rename":
            pending_project_names[uid] = item

            await query.message.reply_text(
                "✏️ Send the new project name now.\n"
                "Maximum 40 characters."
            )

        elif action == "delete":
            if item.running:
                await query.answer(
                    "Stop the project first",
                    show_alert=True,
                )
                return

            safe_remove_folder(item.folder)
            scripts_for(uid).pop(index)
            save_projects()

            await edit_message(
                query,
                projects_text(uid),
                project_list_buttons(uid),
            )


async def setplan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update): return
    if len(context.args) < 3:
        await update.effective_message.reply_text("Usage: /setplan USER_ID free|basic|premium|business|lifetime 30d|lifetime")
        return
    try: uid = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("Invalid user ID"); return
    plan, duration = context.args[1].lower(), context.args[2].lower()
    if plan not in {"free","basic","premium","business","lifetime"}:
        await update.effective_message.reply_text("Invalid plan"); return
    if plan == "free":
        premium_users.discard(uid); premium_expiry.pop(str(uid), None)
    else:
        premium_users.add(uid)
        if duration == "lifetime" or plan == "lifetime": premium_expiry[str(uid)] = "lifetime"
        else:
            delta = parse_duration(duration)
            if not delta: await update.effective_message.reply_text("Duration example: 30d"); return
            premium_expiry[str(uid)] = (datetime.now()+delta).isoformat(timespec="seconds")
    user_plans[str(uid)] = plan
    save_data(); save_v7_data(); audit(update.effective_user.id, "setplan", str(uid), f"{plan} {duration}")
    await update.effective_message.reply_text(premium_box("✅ ᴘʟᴀɴ ᴜᴘᴅᴀᴛᴇᴅ", [f"User: <code>{uid}</code>", f"Plan: <b>{esc(plan.title())}</b>", f"Duration: <code>{esc(duration)}</code>"]), parse_mode=ParseMode.HTML)


async def createcode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update): return
    if len(context.args) < 4:
        await update.effective_message.reply_text("Usage: /createcode CODE plan|credits VALUE MAX_USES [expiry:30d]"); return
    code=context.args[0].upper(); kind=context.args[1].lower(); value=context.args[2]
    try: max_uses=int(context.args[3])
    except ValueError: await update.effective_message.reply_text("MAX_USES must be number"); return
    expiry=""
    if len(context.args)>4:
        d=parse_duration(context.args[4]); expiry=(datetime.now()+d).isoformat(timespec="seconds") if d else ""
    redeem_codes[code]={"kind":kind,"value":value,"max_uses":max_uses,"used_by":[],"expiry":expiry,"created_by":update.effective_user.id}
    save_v7_data(); audit(update.effective_user.id,"createcode",code,f"{kind}:{value}")
    await update.effective_message.reply_text(f"✅ Redeem code created: <code>{esc(code)}</code>",parse_mode=ParseMode.HTML)


async def redeem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args: await update.effective_message.reply_text("Usage: /redeem CODE"); return
    uid=update.effective_user.id; code=context.args[0].upper(); row=redeem_codes.get(code)
    if row and row.get("disabled"):
        await update.effective_message.reply_text("❌ This redeem code is disabled."); return
    if not row: await update.effective_message.reply_text("❌ Invalid code"); return
    if uid in row.get("used_by",[]): await update.effective_message.reply_text("❌ You already used this code"); return
    if len(row.get("used_by",[])) >= int(row.get("max_uses",0)): await update.effective_message.reply_text("❌ Code usage limit reached"); return
    if row.get("expiry") and datetime.fromisoformat(row["expiry"]) <= datetime.now(): await update.effective_message.reply_text("❌ Code expired"); return
    if row.get("kind") == "credits": set_credits(uid,get_credits(uid)+int(row["value"]))
    elif row.get("kind") == "plan":
        plan=row["value"].lower(); premium_users.add(uid); user_plans[str(uid)]=plan; premium_expiry[str(uid)]=(datetime.now()+timedelta(days=30)).isoformat(timespec="seconds"); save_data()
    else: await update.effective_message.reply_text("❌ Invalid code configuration"); return
    row.setdefault("used_by",[]).append(uid); save_v7_data(); audit(uid,"redeem",code,str(row.get("value")))
    await update.effective_message.reply_text("✅ Code redeemed successfully")


async def setenv_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context): return
    if len(context.args) < 3: await update.effective_message.reply_text("Usage: /setenv PROJECT KEY VALUE"); return
    found=find_project(update.effective_user.id,context.args[0])
    if not found: await update.effective_message.reply_text("Project not found"); return
    _,item=found; key=context.args[1]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}",key): await update.effective_message.reply_text("Invalid variable name"); return
    value=" ".join(context.args[2:]); project_envs.setdefault(project_key(item),{})[key]=value; save_v7_data()
    await update.effective_message.reply_text(f"✅ <code>{esc(key)}</code> saved and masked. Restart project to apply.",parse_mode=ParseMode.HTML)


async def env_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context): return
    if not context.args: await update.effective_message.reply_text("Usage: /env PROJECT"); return
    found=find_project(update.effective_user.id,context.args[0])
    if not found: await update.effective_message.reply_text("Project not found"); return
    _,item=found; envs=project_envs.get(project_key(item),{})
    lines=[f"<code>{esc(k)}</code> = ••••••••" for k in envs] or ["No variables configured"]
    await update.effective_message.reply_text(premium_box("🔐 ᴇɴᴠɪʀᴏɴᴍᴇɴᴛ",lines),parse_mode=ParseMode.HTML)


async def delenv_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context): return
    if len(context.args)<2: await update.effective_message.reply_text("Usage: /delenv PROJECT KEY"); return
    found=find_project(update.effective_user.id,context.args[0])
    if not found: await update.effective_message.reply_text("Project not found"); return
    _,item=found; project_envs.get(project_key(item),{}).pop(context.args[1],None); save_v7_data(); await update.effective_message.reply_text("✅ Variable removed")


async def autorestart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context): return
    if len(context.args)<2: await update.effective_message.reply_text("Usage: /autorestart PROJECT on|off"); return
    found=find_project(update.effective_user.id,context.args[0])
    if not found: await update.effective_message.reply_text("Project not found"); return
    _,item=found; item.auto_restart=context.args[1].lower() in {"on","yes","1"}; item.restarts=0; save_projects(); await update.effective_message.reply_text(f"♻️ Auto restart: {'ON' if item.auto_restart else 'OFF'}")


async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context): return
    if not context.args: await update.effective_message.reply_text("Usage: /health PROJECT"); return
    found=find_project(update.effective_user.id,context.args[0])
    if not found: await update.effective_message.reply_text("Project not found"); return
    _,item=found; r=project_resources(item); ram_limit=project_settings.get(project_key(item),{}).get("ram_mb",plan_limits(update.effective_user.id)[2])
    lines=[f"Project: <b>{esc(item.display_name)}</b>",f"Status: {'🟢 Online' if item.running else '🔴 Offline'}",f"PID: <code>{item.pid}</code>",f"CPU: <code>{r['cpu']}</code>",f"RAM: <code>{r['ram']} / {ram_limit} MB</code>",f"Disk: <code>{r['disk']}</code>",f"Uptime: <code>{uptime(item.started_at) if item.running else '—'}</code>",f"Restarts: <code>{item.restarts}</code>"]
    await update.effective_message.reply_text(premium_box("📊 ᴘʀᴏᴊᴇᴄᴛ ʜᴇᴀʟᴛʜ",lines),parse_mode=ParseMode.HTML)


async def auditlog_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update): return
    rows=audit_log[-30:]; text="\n".join(f"{x['time']} | {x['actor']} | {x['action']} | {x['target']} | {x['detail']}" for x in rows) or "No audit entries"
    await update.effective_message.reply_text(f"<pre>{esc(text[-3800:])}</pre>",parse_mode=ParseMode.HTML)


async def plans_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid=update.effective_user.id; exp=premium_expiry.get(str(uid),"—")
    lines=[f"Current: <b>{esc(plan_name(uid))}</b>",f"Expiry: <code>{esc(exp)}</code>","Free: 1 daily / 1-2 running / 128 MB","Basic: 5 daily / 3 running / 256 MB","Premium: 25 daily / 10 running / 512 MB","Business: 100 daily / 30 running / 1024 MB"]
    await update.effective_message.reply_text(premium_box("💎 ᴘʟᴀɴs",lines),parse_mode=ParseMode.HTML)



class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] not in {"/", "/health"}:
            self.send_response(404); self.end_headers(); return
        body = json.dumps({
            "service": BRAND_NAME,
            "status": "online",
            "runtime": "python-only",
            "uptime": uptime(),
            "projects": sum(len(v) for v in running_scripts.values()),
            "active": sum(i.running for v in running_scripts.values() for i in v),
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def start_health_server() -> None:
    global health_server_started
    try:
        server = ThreadingHTTPServer(("0.0.0.0", HEALTH_PORT), _HealthHandler)
        health_server_started = True
        threading.Thread(target=server.serve_forever, daemon=True, name="elevatex-health").start()
        logger.info("Health server listening on 0.0.0.0:%s", HEALTH_PORT)
    except OSError as exc:
        health_server_started = False
        logger.warning("Health server could not start on port %s: %s", HEALTH_PORT, exc)


def _ping_keepalive(url: str) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ElevateX-Host-KeepAlive/8.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            return 200 <= response.status < 400, f"HTTP {response.status}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


async def keepalive_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    global keepalive_last_status, keepalive_last_at, keepalive_failures, keepalive_last_epoch
    if not keepalive_enabled or not keepalive_url:
        return
    now = time.time()
    if keepalive_last_epoch and now - keepalive_last_epoch < keepalive_interval:
        return
    keepalive_last_epoch = now
    ok, detail = await asyncio.to_thread(_ping_keepalive, keepalive_url)
    keepalive_last_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    keepalive_last_status = detail
    if ok:
        keepalive_failures = 0
    else:
        keepalive_failures += 1
        logger.warning("Keep-alive ping failed (%s): %s", keepalive_failures, detail)
        if keepalive_failures in {3, 10}:
            try:
                await context.bot.send_message(OWNER_ID, premium_box("⚠️ ᴋᴇᴇᴘ-ᴀʟɪᴠᴇ ᴡᴀʀɴɪɴɢ", [f"Failures: <code>{keepalive_failures}</code>", f"Status: <code>{esc(detail)}</code>", f"URL: <code>{esc(keepalive_url)}</code>"]), parse_mode=ParseMode.HTML)
            except TelegramError:
                pass


def keepalive_text() -> str:
    return premium_box("💓 ᴋᴇᴇᴘ ᴀʟɪᴠᴇ", [
        f"Status: <code>{'ON' if keepalive_enabled else 'OFF'}</code>",
        f"Interval: <code>{keepalive_interval}s</code>",
        f"URL: <code>{esc(keepalive_url or 'Not configured')}</code>",
        f"Last Ping: <code>{esc(keepalive_last_at)}</code>",
        f"Last Result: <code>{esc(keepalive_last_status)}</code>",
        f"Failures: <code>{keepalive_failures}</code>",
        f"Health Server: <code>{'ONLINE' if health_server_started else 'UNAVAILABLE'}</code> : <code>{HEALTH_PORT}</code>",
        "Use <code>/setkeepalive https://your-domain/health 40</code>",
    ])


async def keepalive_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global keepalive_enabled
    if not owner_only(update): return
    if context.args:
        mode = context.args[0].lower()
        if mode in {"on", "off"}:
            keepalive_enabled = mode == "on"; save_v7_data(); audit(update.effective_user.id, "keepalive", detail=mode)
    await update.effective_message.reply_text(keepalive_text(), parse_mode=ParseMode.HTML)


async def setkeepalive_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global keepalive_url, keepalive_interval, keepalive_enabled
    if not owner_only(update): return
    if not context.args:
        await update.effective_message.reply_text("Usage: /setkeepalive URL [30-45] | /setkeepalive off"); return
    if context.args[0].lower() == "off":
        keepalive_enabled = False; save_v7_data(); await update.effective_message.reply_text("💤 Keep-alive disabled."); return
    url = context.args[0].strip()
    if not url.startswith(("http://", "https://")):
        await update.effective_message.reply_text("❌ URL must start with http:// or https://"); return
    interval = keepalive_interval
    if len(context.args) > 1:
        try: interval = max(30, min(45, int(context.args[1])))
        except ValueError: await update.effective_message.reply_text("❌ Interval must be 30-45 seconds."); return
    keepalive_url = url; keepalive_interval = interval; keepalive_enabled = True; save_v7_data()
    audit(update.effective_user.id, "set_keepalive", detail=f"{url} @ {interval}s")
    await update.effective_message.reply_text(keepalive_text(), parse_mode=ParseMode.HTML)


def host_stats_text() -> str:
    all_items=[i for items in running_scripts.values() for i in items]
    active=sum(i.running for i in all_items)
    disk="N/A"; ram="N/A"; cpu="N/A"
    try:
        total, used, free=shutil.disk_usage(BASE_DIR); disk=f"{used/1024**3:.2f}/{total/1024**3:.2f} GB"
    except OSError: pass
    try:
        import psutil
        ram=f"{psutil.virtual_memory().percent:.1f}%"; cpu=f"{psutil.cpu_percent(interval=0.1):.1f}%"
    except Exception: pass
    return premium_box("🖥 ʜᴏsᴛ sᴛᴀᴛᴜs", [
        f"Python: <code>{platform.python_version()}</code>", f"OS: <code>{esc(platform.system())} {esc(platform.release())}</code>",
        f"CPU: <code>{cpu}</code>", f"RAM: <code>{ram}</code>", f"Disk: <code>{disk}</code>",
        f"Projects: <code>{len(all_items)}</code>", f"Running: <code>{active}</code>", f"Users: <code>{len(user_stats)}</code>",
        f"Keep Alive: <code>{'ON' if keepalive_enabled else 'OFF'} / {keepalive_interval}s</code>", f"Uptime: <code>{uptime()}</code>",
    ])


async def hoststats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update): return
    await update.effective_message.reply_text(host_stats_text(), parse_mode=ParseMode.HTML)


def security_text() -> str:
    return premium_box("🛡 sᴇᴄᴜʀɪᴛʏ & ʀᴜɴᴛɪᴍᴇ", [
        "Runtime: <code>PYTHON ONLY</code>", f"Security Scan: <code>{'ON' if SECURITY_SCAN_ENABLED else 'OFF'}</code>",
        f"Auto Dependencies: <code>{'ON' if AUTO_INSTALL_DEPENDENCIES else 'OFF'}</code>", f"Docker Mode: <code>{'ON' if DOCKER_MODE else 'OFF'}</code>",
        f"Resource Limits: <code>{'ON' if ENFORCE_RESOURCE_LIMITS else 'OFF'}</code>", f"Process Limit: <code>{PROJECT_PROCESS_LIMIT or 'disabled'}</code>",
        f"Open Files: <code>{PROJECT_OPEN_FILES_LIMIT}</code>", f"Max Upload: <code>{MAX_FILE_MB} MB</code>", f"Max ZIP Expanded: <code>{MAX_ZIP_EXPANDED_MB} MB</code>",
    ])


async def security_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update): return
    await update.effective_message.reply_text(security_text(), parse_mode=ParseMode.HTML)


async def finduser_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update): return
    if not context.args: await update.effective_message.reply_text("Usage: /finduser USER_ID|username|name"); return
    q=" ".join(context.args).lstrip("@").casefold(); rows=[]
    for uid, st in user_stats.items():
        hay=f"{uid} {st.get('username','')} {st.get('first_name','')}".casefold()
        if q in hay:
            rows.append(f"• <code>{uid}</code> @{esc(st.get('username') or 'not_set')} — {esc(st.get('first_name') or 'Unknown')} — {esc(plan_name(int(uid)))}")
    await update.effective_message.reply_text(premium_box("🔎 ᴜsᴇʀ sᴇᴀʀᴄʜ", rows[:30] or ["No matching user found."]), parse_mode=ParseMode.HTML)


async def allprojects_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update): return
    rows=[]
    for uid, items in sorted(running_scripts.items()):
        for i in items:
            rows.append(f"• <code>{uid}</code> | <b>{esc(i.display_name)}</b> | {'🟢' if i.running else '🔴'} | <code>{Path(i.entry_file).name}</code>")
    await update.effective_message.reply_text(premium_box("📂 ᴀʟʟ ᴘʀᴏᴊᴇᴄᴛs", rows[:70] or ["No projects registered."]), parse_mode=ParseMode.HTML)


async def restartall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update): return
    restarted=failed=0
    for items in running_scripts.values():
        for item in items:
            try:
                if item.running: kill_process(item)
                spawn_script(item, Path(item.entry_file), Path(item.folder), Path(item.log_path)); restarted += 1
            except Exception:
                failed += 1; logger.exception("Restart-all failure")
    save_projects(); audit(update.effective_user.id, "restart_all", detail=f"ok={restarted}, failed={failed}")
    await update.effective_message.reply_text(premium_box("♻️ ʀᴇsᴛᴀʀᴛ ᴀʟʟ", [f"Restarted: <code>{restarted}</code>", f"Failed: <code>{failed}</code>"]), parse_mode=ParseMode.HTML)



async def watchdog_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global watchdog_enabled
    if not owner_only(update): return
    if context.args:
        v=context.args[0].lower()
        if v in ("on","off"):
            watchdog_enabled = v == "on"; save_v7_data(); audit(update.effective_user.id,"watchdog",detail=v)
    await update.effective_message.reply_text(premium_box("🛡 ᴡᴀᴛᴄʜᴅᴏɢ", [
        f"Status: <code>{'ON' if watchdog_enabled else 'OFF'}</code>",
        f"Interval: <code>{watchdog_interval}s</code>", f"Crash window: <code>{CRASH_WINDOW_SECONDS}s</code>",
        f"Crash limit: <code>{CRASH_LIMIT}</code>", f"Auto restarts: <code>{watchdog_restarts}</code>"
    ]), parse_mode=ParseMode.HTML)

async def setwatchdog_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global watchdog_interval
    if not owner_only(update): return
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Usage: /setwatchdog SECONDS (minimum 20)"); return
    watchdog_interval=max(20,int(context.args[0])); save_v7_data(); audit(update.effective_user.id,"set_watchdog",detail=str(watchdog_interval))
    await update.effective_message.reply_text(f"✅ Watchdog interval set to {watchdog_interval}s")

async def watchdogstatus_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await watchdog_cmd(update, context)

async def schedulerestart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context): return
    if len(context.args) < 2:
        await update.effective_message.reply_text("Usage: /schedulerestart PROJECT 6h|30m|1d"); return
    found=find_project(update.effective_user.id, " ".join(context.args[:-1]))
    dur=parse_duration(context.args[-1])
    if not found or not dur:
        await update.effective_message.reply_text("❌ Project/duration invalid. Example: /schedulerestart MyBot 6h"); return
    _,item=found; sec=max(300,int(dur.total_seconds())); st=project_setting(item); st["restart_schedule_seconds"]=sec; st["next_restart_at"]=time.time()+sec
    save_v7_data(); audit(update.effective_user.id,"schedule_restart",item.display_name,str(sec))
    await update.effective_message.reply_text(f"✅ {item.display_name} scheduled every {sec}s.")

async def scheduleremove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context): return
    if not context.args: await update.effective_message.reply_text("Usage: /scheduleremove PROJECT"); return
    found=find_project(update.effective_user.id," ".join(context.args))
    if not found: await update.effective_message.reply_text("❌ Project not found."); return
    _,item=found; st=project_setting(item); st.pop("restart_schedule_seconds",None); st.pop("next_restart_at",None); save_v7_data()
    await update.effective_message.reply_text("✅ Scheduled restart removed.")

async def autostart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context): return
    if len(context.args)<2 or context.args[-1].lower() not in ("on","off"):
        await update.effective_message.reply_text("Usage: /autostart PROJECT on|off"); return
    found=find_project(update.effective_user.id," ".join(context.args[:-1]))
    if not found: await update.effective_message.reply_text("❌ Project not found."); return
    _,item=found; project_setting(item)["autostart"]=context.args[-1].lower()=="on"; save_v7_data()
    await update.effective_message.reply_text(f"✅ Auto-start {'enabled' if project_setting(item)['autostart'] else 'disabled'} for {item.display_name}.")

async def projectbackup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context): return
    if not context.args: await update.effective_message.reply_text("Usage: /projectbackup PROJECT"); return
    found=find_project(update.effective_user.id," ".join(context.args))
    if not found: await update.effective_message.reply_text("❌ Project not found."); return
    _,item=found; folder=Path(item.folder); stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
    out=PROJECT_BACKUPS_DIR/f"{update.effective_user.id}_{clean_project_name(item.display_name)}_{stamp}.zip"
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
        for f in folder.rglob("*"):
            if not f.is_file() or ".venv" in f.parts or "node_modules" in f.parts or f.name=="runtime.log": continue
            z.write(f, f.relative_to(folder))
    await update.effective_message.reply_document(InputFile(str(out)), caption=f"💾 Project backup: {item.display_name}")

async def backups_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update): return
    rows=sorted(BACKUPS_DIR.glob("elevatex_backup_*.zip"),key=lambda x:x.stat().st_mtime,reverse=True)[:10]
    await update.effective_message.reply_text(premium_box("💾 ʙᴀᴄᴋᴜᴘs", [f"• <code>{esc(x.name)}</code>" for x in rows] or ["No backups yet."]),parse_mode=ParseMode.HTML)

async def restorebackup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update): return
    if len(context.args) != 2 or context.args[1] != "CONFIRM":
        await update.effective_message.reply_text("Usage: /restorebackup FILENAME.zip CONFIRM\nUse /backups to list available backups."); return
    name=Path(context.args[0]).name; src=BACKUPS_DIR/name
    if not src.exists() or not name.startswith("elevatex_backup_"):
        await update.effective_message.reply_text("❌ Backup not found."); return
    allowed={DATA_FILE.name,PROJECTS_FILE.name,V7_DATA_FILE.name,V9_DB_FILE.name}
    with zipfile.ZipFile(src) as z:
        for member in z.infolist():
            if Path(member.filename).name in allowed and "/" not in member.filename.strip("/"):
                z.extract(member, BASE_DIR)
    audit(update.effective_user.id,"restore_backup",name)
    await update.effective_message.reply_text("✅ Backup files restored. Restart ElevateX Host to reload the restored state.")

async def repairenv_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context): return
    if not context.args: await update.effective_message.reply_text("Usage: /repairenv PROJECT"); return
    found = find_project(update.effective_user.id, " ".join(context.args))
    if not found: await update.effective_message.reply_text("❌ Project not found."); return
    _, item = found
    if item.running: await update.effective_message.reply_text("⚠️ Stop the project first."); return
    msg = await update.effective_message.reply_text("🔧 Rebuilding private environment…")
    try:
        note = await asyncio.to_thread(rebuild_project_env, item)
        await msg.edit_text(f"✅ Environment repaired. {note}")
    except Exception as exc:
        await msg.edit_text(f"❌ Repair failed: {exc}")


async def logsize_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context): return
    if not context.args: await update.effective_message.reply_text("Usage: /logsize PROJECT"); return
    found=find_project(update.effective_user.id," ".join(context.args));
    if not found: await update.effective_message.reply_text("❌ Project not found."); return
    _,item=found; p=Path(item.log_path); size=(p.stat().st_size/(1024*1024)) if p.exists() else 0
    await update.effective_message.reply_text(f"🧾 {item.display_name} log size: {size:.2f} MB")

async def clearlogs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context): return
    if not context.args: await update.effective_message.reply_text("Usage: /clearlogs PROJECT"); return
    found=find_project(update.effective_user.id," ".join(context.args));
    if not found: await update.effective_message.reply_text("❌ Project not found."); return
    _,item=found; Path(item.log_path).write_text("",encoding="utf-8"); await update.effective_message.reply_text("✅ Runtime log cleared.")

async def diagnose_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context): return
    if not context.args: await update.effective_message.reply_text("Usage: /diagnose PROJECT"); return
    found=find_project(update.effective_user.id," ".join(context.args));
    if not found: await update.effective_message.reply_text("❌ Project not found."); return
    _,item=found; p=Path(item.log_path); text=p.read_text("utf-8",errors="replace")[-12000:] if p.exists() else ""
    await update.effective_message.reply_text(premium_box("🩺 ᴅɪᴀɢɴᴏsᴛɪᴄs", [f"Project: <b>{esc(item.display_name)}</b>"]+[f"• {esc(x)}" for x in diagnose_log_text(text)]),parse_mode=ParseMode.HTML)

async def storage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid=update.effective_user.id; used=user_storage_mb(uid); limit=storage_limit_mb(uid)
    await update.effective_message.reply_text(premium_box("💾 sᴛᴏʀᴀɢᴇ", [f"Used: <code>{used:.1f} MB</code>",f"Quota: <code>{limit} MB</code>",f"Available: <code>{max(0,limit-used):.1f} MB</code>"]),parse_mode=ParseMode.HTML)

async def setstorage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update): return
    if len(context.args)!=2 or not context.args[0].isdigit() or not context.args[1].isdigit():
        await update.effective_message.reply_text("Usage: /setstorage USER_ID MB"); return
    user_storage_limits[str(int(context.args[0]))]=max(50,int(context.args[1])); save_v7_data(); audit(update.effective_user.id,"set_storage",context.args[0],context.args[1])
    await update.effective_message.reply_text("✅ Storage quota updated.")

async def analytics_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not admin_or_owner(update): return
    total_projects=sum(len(x) for x in running_scripts.values()); running=sum(i.running for x in running_scripts.values() for i in x)
    total_storage=sum(user_storage_mb(uid) for uid in running_scripts)
    await update.effective_message.reply_text(premium_box("📈 ᴀɴᴀʟʏᴛɪᴄs", [
        f"Known users: <code>{len(user_stats)}</code>",f"Approved: <code>{len(approved_users)}</code>",f"Premium: <code>{len(premium_users)}</code>",
        f"Projects: <code>{total_projects}</code>",f"Running: <code>{running}</code>",f"Storage: <code>{total_storage:.1f} MB</code>",
        f"Redeem codes: <code>{len(redeem_codes)}</code>",f"Audit events: <code>{len(audit_log)}</code>"
    ]),parse_mode=ParseMode.HTML)

async def addadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update): return
    if len(context.args)!=2 or not context.args[0].isdigit() or context.args[1].lower() not in ("support","moderator","superadmin"):
        await update.effective_message.reply_text("Usage: /addadmin USER_ID support|moderator|superadmin"); return
    admin_roles[str(int(context.args[0]))]=context.args[1].lower(); save_v7_data(); audit(update.effective_user.id,"add_admin",context.args[0],context.args[1])
    await update.effective_message.reply_text("✅ Admin role added. Delegated roles can access read-only V9 admin views; owner-only destructive commands remain protected.")

async def deladmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update): return
    if not context.args or not context.args[0].isdigit(): await update.effective_message.reply_text("Usage: /deladmin USER_ID"); return
    admin_roles.pop(str(int(context.args[0])),None); save_v7_data(); await update.effective_message.reply_text("✅ Admin role removed.")

async def admins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not admin_or_owner(update): return
    rows=[f"• <code>{uid}</code> — <b>{esc(role)}</b>" for uid,role in admin_roles.items()]
    await update.effective_message.reply_text(premium_box("👑 ᴀᴅᴍɪɴ ʀᴏʟᴇs", rows or ["No delegated admins."]),parse_mode=ParseMode.HTML)

async def codes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update): return
    rows=[]
    for code,row in list(redeem_codes.items())[:50]: rows.append(f"• <code>{esc(code)}</code> — {esc(str(row.get('kind')))}:{esc(str(row.get('value')))} — {'OFF' if row.get('disabled') else 'ON'} — {len(row.get('used_by',[]))}/{row.get('max_uses','∞')}")
    await update.effective_message.reply_text(premium_box("🎟 ʀᴇᴅᴇᴇᴍ ᴄᴏᴅᴇs",rows or ["No codes."]),parse_mode=ParseMode.HTML)

async def disablecode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update): return
    if not context.args: await update.effective_message.reply_text("Usage: /disablecode CODE"); return
    code=context.args[0].upper(); row=redeem_codes.get(code)
    if not row: await update.effective_message.reply_text("❌ Code not found."); return
    row["disabled"]=not bool(row.get("disabled")); save_v7_data(); await update.effective_message.reply_text(f"✅ {code}: {'disabled' if row['disabled'] else 'enabled'}")

async def deletecode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update): return
    if not context.args: await update.effective_message.reply_text("Usage: /deletecode CODE"); return
    code=context.args[0].upper(); existed=redeem_codes.pop(code,None); save_v7_data(); await update.effective_message.reply_text("✅ Code deleted." if existed else "❌ Code not found.")

async def codeinfo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update): return
    if not context.args: await update.effective_message.reply_text("Usage: /codeinfo CODE"); return
    code=context.args[0].upper(); row=redeem_codes.get(code)
    if not row: await update.effective_message.reply_text("❌ Code not found."); return
    await update.effective_message.reply_text(premium_box("🎟 ᴄᴏᴅᴇ ɪɴғᴏ",[f"Code: <code>{esc(code)}</code>",f"Kind: <code>{esc(str(row.get('kind')))}</code>",f"Value: <code>{esc(str(row.get('value')))}</code>",f"Used: <code>{len(row.get('used_by',[]))}</code>",f"Max: <code>{row.get('max_uses','∞')}</code>",f"Status: <code>{'Disabled' if row.get('disabled') else 'Active'}</code>"]),parse_mode=ParseMode.HTML)

async def forcejoin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global FORCE_JOIN_ENABLED
    if not owner_only(update): return
    if context.args and context.args[0].lower() in ("on","off"):
        FORCE_JOIN_ENABLED=context.args[0].lower()=="on"; project_settings.setdefault("__global__",{})["force_join_enabled"]=FORCE_JOIN_ENABLED; save_v7_data()
    await update.effective_message.reply_text(f"🔐 Force Join: {'ON' if FORCE_JOIN_ENABLED else 'OFF'}")

async def setbrand_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global BRAND_NAME
    if not owner_only(update): return
    if not context.args: await update.effective_message.reply_text("Usage: /setbrand NAME"); return
    BRAND_NAME=" ".join(context.args)[:50]; project_settings.setdefault("__global__",{})["brand_name"]=BRAND_NAME; save_v7_data(); await update.effective_message.reply_text("✅ Brand name updated.")

async def setfooter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global brand_footer
    if not owner_only(update): return
    if not context.args: await update.effective_message.reply_text("Usage: /setfooter TEXT"); return
    brand_footer=" ".join(context.args)[:120]; save_v7_data(); await update.effective_message.reply_text("✅ Footer updated.")

async def panelreminder_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global panel_reminder_enabled
    if not owner_only(update): return
    if context.args and context.args[0].lower() in ("on","off"):
        panel_reminder_enabled=context.args[0].lower()=="on"; save_v7_data()
    next_due=panel_last_confirmed_at + PANEL_REMINDER_HOURS*3600
    await update.effective_message.reply_text(premium_box("⏰ ᴘᴀɴᴇʟ ʀᴇᴍɪɴᴅᴇʀ",[f"Status: <code>{'ON' if panel_reminder_enabled else 'OFF'}</code>",f"Cycle: <code>{PANEL_REMINDER_HOURS}h</code>",f"Last confirmed: <code>{datetime.fromtimestamp(panel_last_confirmed_at).strftime('%Y-%m-%d %H:%M')}</code>",f"Next due: <code>{datetime.fromtimestamp(next_due).strftime('%Y-%m-%d %H:%M')}</code>","After visiting your panel, use <code>/panelvisited</code>."]),parse_mode=ParseMode.HTML)

async def panelvisited_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global panel_last_confirmed_at, panel_last_reminder_at
    if not owner_only(update): return
    panel_last_confirmed_at=time.time(); panel_last_reminder_at=0.0; save_v7_data(); audit(update.effective_user.id,"panel_visited")
    await update.effective_message.reply_text("✅ Panel visit marked. Next reminder is due in 3 days.")

async def piplist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context): return
    if not context.args: await update.effective_message.reply_text("Usage: /piplist PROJECT"); return
    found = find_project(update.effective_user.id, " ".join(context.args))
    if not found: await update.effective_message.reply_text("❌ Project not found."); return
    _, item = found
    entry = Path(item.entry_file)
    if entry.suffix.lower() in NODE_EXTS:
        npm = npm_command()
        if not npm: await update.effective_message.reply_text("❌ npm not found. Owner: /nodeinstall"); return
        root = node_project_root(entry, Path(item.folder))
        r = await asyncio.to_thread(subprocess.run, npm + ["ls", "--depth=0"], cwd=root, env=node_env(), capture_output=True, text=True, timeout=60)
        text = ((r.stdout or r.stderr) or "No packages installed.")[-3500:]
        await update.effective_message.reply_text(f"<pre>{esc(text)}</pre>", parse_mode=ParseMode.HTML)
        return
    py = Path(item.folder) / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists(): await update.effective_message.reply_text("❌ Private environment not found."); return
    r = await asyncio.to_thread(subprocess.run, [str(py), "-m", "pip", "list", "--format=freeze"], capture_output=True, text=True, timeout=60)
    text = (r.stdout or r.stderr)[-3500:]
    await update.effective_message.reply_text(f"<pre>{esc(text)}</pre>", parse_mode=ParseMode.HTML)


async def requirements_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context): return
    if not context.args: await update.effective_message.reply_text("Usage: /requirements PROJECT"); return
    found = find_project(update.effective_user.id, " ".join(context.args))
    if not found: await update.effective_message.reply_text("❌ Project not found."); return
    _, item = found
    entry = Path(item.entry_file)
    if entry.suffix.lower() in NODE_EXTS:
        manifest = node_project_root(entry, Path(item.folder)) / "package.json"
        missing = "No package.json found."
    else:
        manifest = find_requirements(Path(item.folder)) or (Path(item.folder) / "requirements.txt")
        missing = "No requirements.txt found."
    if not manifest.exists(): await update.effective_message.reply_text(missing); return
    await update.effective_message.reply_text(f"<pre>{esc(manifest.read_text('utf-8', errors='replace')[:3500])}</pre>", parse_mode=ParseMode.HTML)


async def checkcompat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context): return
    if not context.args: await update.effective_message.reply_text("Usage: /checkcompat PROJECT"); return
    found = find_project(update.effective_user.id, " ".join(context.args))
    if not found: await update.effective_message.reply_text("❌ Project not found."); return
    _, item = found
    entry = Path(item.entry_file)
    if entry.suffix.lower() in NODE_EXTS:
        ver = node_version()
        notes = [f"Host Node.js: <code>{esc(ver) or 'not installed'}</code>"]
        pkg = node_project_root(entry, Path(item.folder)) / "package.json"
        if pkg.exists():
            notes.append("package.json: <code>Detected</code>")
            try:
                spec = str((json.loads(pkg.read_text("utf-8", errors="replace")).get("engines") or {}).get("node", ""))
            except (OSError, ValueError, AttributeError):
                spec = ""
            if spec:
                notes.append(f"engines.node: <code>{esc(spec)}</code>")
                match = re.search(r"(\d+)", spec)
                host = re.match(r"v?(\d+)", ver)
                if match and host and ">=" in spec and int(match.group(1)) > int(host.group(1)):
                    notes.append("⚠️ Host Node.js is older than this project requires.")
        else:
            notes.append("package.json: <code>Not found</code>")
        await update.effective_message.reply_text(premium_box("🧪 ᴄᴏᴍᴘᴀᴛɪʙɪʟɪᴛʏ", notes), parse_mode=ParseMode.HTML)
        return
    req = find_requirements(Path(item.folder))
    notes = [f"Host Python: <code>{sys.version.split()[0]}</code>"]
    if req:
        txt = req.read_text("utf-8", errors="replace"); notes.append("requirements.txt: <code>Detected</code>")
        if sys.version_info >= (3, 13) and re.search(r"python-telegram-bot\s*==\s*20\.", txt, re.I): notes.append("⚠️ PTB 20.x is not recommended on Python 3.13; compatibility rewrite will be used.")
    else: notes.append("requirements.txt: <code>Not found</code>")
    await update.effective_message.reply_text(premium_box("🧪 ᴄᴏᴍᴘᴀᴛɪʙɪʟɪᴛʏ", notes), parse_mode=ParseMode.HTML)


def rebuild_project_env(item: ScriptProcess) -> str:
    """Delete and recreate the project's private environment (.venv or node_modules)."""
    folder = Path(item.folder)
    entry = Path(item.entry_file)
    if entry.suffix.lower() in NODE_EXTS:
        root = node_project_root(entry, folder)
        if not (root / "package.json").exists():
            raise RuntimeError("package.json not found.")
        shutil.rmtree(root / "node_modules", ignore_errors=True)
    else:
        if not find_requirements(folder):
            raise RuntimeError("requirements.txt not found.")
        shutil.rmtree(folder / ".venv", ignore_errors=True)
    return install_project_dependencies(folder, entry, Path(item.log_path))


def build_project_backup(user_id: int, item: ScriptProcess) -> Path:
    folder = Path(item.folder)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = PROJECT_BACKUPS_DIR / f"{user_id}_{clean_project_name(item.display_name)}_{stamp}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in folder.rglob("*"):
            if not f.is_file() or ".venv" in f.parts or "node_modules" in f.parts or f.name == "runtime.log":
                continue
            z.write(f, f.relative_to(folder))
    return out


def node_status_text() -> str:
    ver = node_version()
    lines = [
        f"Node.js: <code>{esc(ver) if ver else 'not installed'}</code>",
        f"npm: <code>{'ready' if npm_command() else 'missing'}</code>",
        f"Path: <code>{esc(node_path() or '—')}</code>",
    ]
    if not ver:
        lines += ["", "Tap Install to download a portable Node.js", "(no root access needed)."]
    return premium_box("🟩 ɴᴏᴅᴇ.ᴊs", lines)


def node_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⬇️ Install / Update Node.js", callback_data="admin:nodeinstall")],
            [InlineKeyboardButton("🔄 Refresh", callback_data="admin:node")],
            [InlineKeyboardButton("⬅️ Admin", callback_data="admin:overview")],
        ]
    )


async def handle_project_update(update: Update, context: ContextTypes.DEFAULT_TYPE, item: ScriptProcess) -> None:
    """Overlay a new file/zip onto an existing project, keeping env, settings and packages."""
    msg = update.effective_message
    uid = update.effective_user.id
    document = msg.document
    filename = clean_filename(document.file_name or "update")
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTS | {".zip"}:
        await msg.reply_text("❌ Send a .py/.js/.mjs/.cjs file or a .zip. Update cancelled.")
        return
    if (document.file_size or 0) > MAX_FILE_MB * 1024 * 1024:
        await msg.reply_text(f"❌ Maximum file size is {MAX_FILE_MB} MB.")
        return
    folder = Path(item.folder)
    if not folder.exists():
        await msg.reply_text("❌ Project folder is missing.")
        return
    status = await msg.reply_text("📥 Updating project files…")
    tmp = folder.parent / f".update_{secrets.token_hex(4)}"
    tmp.mkdir(parents=True)
    try:
        async with lock_for(uid):
            upload = tmp / filename
            tg_file = await context.bot.get_file(document.file_id)
            await tg_file.download_to_drive(str(upload))
            src = tmp / "x"
            src.mkdir()
            if suffix == ".zip":
                safe_extract_zip(upload, src)
            else:
                shutil.copy2(upload, src / filename)

            entry = Path(item.entry_file)
            try:
                entry_rel = entry.resolve().relative_to(folder.resolve())
            except ValueError:
                entry_rel = Path(entry.name)
            dest_base = folder
            if not (src / entry_rel).exists():
                kids = list(src.iterdir())
                if len(kids) == 1 and kids[0].is_dir() and (kids[0] / entry_rel).exists():
                    src = kids[0]
                elif len(entry_rel.parts) > 1 and (src / Path(*entry_rel.parts[1:])).exists():
                    dest_base = folder / entry_rel.parts[0]

            risk, findings = scan_project(src) if SECURITY_SCAN_ENABLED else ("DISABLED", [])
            if risk == "HIGH" and not is_owner(uid):
                raise ValueError("High-risk code detected: " + "; ".join(findings[:3]))

            keep = {".venv", "node_modules", "runtime.log", ".elevatex-requirements.txt"}
            was_running = item.running
            if was_running:
                kill_process(item)
            copied = 0
            deps_changed = False
            for f in src.rglob("*"):
                rel = f.relative_to(src)
                if not f.is_file() or rel.parts[0] in keep:
                    continue
                dest = dest_base / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                is_manifest = rel.name in {"requirements.txt", "package.json"}
                before = hashlib.sha256(dest.read_bytes()).hexdigest() if is_manifest and dest.exists() else ""
                shutil.copy2(f, dest)
                copied += 1
                if is_manifest and hashlib.sha256(dest.read_bytes()).hexdigest() != before:
                    deps_changed = True

            note = ""
            if deps_changed and AUTO_INSTALL_DEPENDENCIES:
                try:
                    note = await asyncio.to_thread(rebuild_project_env, item)
                except Exception as exc:
                    note = f"dependency step failed: {exc}"
            restarted = ""
            if was_running:
                try:
                    spawn_script(item, Path(item.entry_file), Path(item.folder), Path(item.log_path))
                    await asyncio.sleep(1.0)
                    restarted = "🟢 Restarted" if item.running else "🔴 Crashed after restart — check 🧾 Logs"
                except Exception as exc:
                    restarted = f"❌ Restart failed: {exc}"
            extra = ""
            if suffix != ".zip" and filename != entry.name:
                extra = f"\nℹ️ Added as an extra file (entry stays <code>{esc(entry.name)}</code>). Use the same file name to replace it."
            audit(uid, "project_update", item.display_name, f"{copied} files")
        await status.edit_text(
            f"<b>✅ Project Updated</b>\n\n"
            f"📁 Files written: <code>{copied}</code>\n"
            f"🛡 Scan: <code>{esc(risk)}</code>\n"
            + (f"📦 {esc(note)}\n" if note else "")
            + (f"{restarted}\n" if restarted else "")
            + extra,
            parse_mode=ParseMode.HTML,
            reply_markup=project_control_buttons(scripts_for(uid).index(item), item.running),
        )
    except Exception as exc:
        logger.exception("Project update failed")
        await status.edit_text(f"<b>❌ Update Failed</b>\n\n<code>{esc(exc)}</code>", parse_mode=ParseMode.HTML)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context): return
    uid = update.effective_user.id
    had = pending_updates.pop(uid, None) is not None
    had = (pending_env.pop(uid, None) is not None) or had
    await update.effective_message.reply_text("✅ Cancelled." if had else "Nothing to cancel.")


async def nodestatus_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update):
        await update.effective_message.reply_text("❌ Owner only.")
        return
    await update.effective_message.reply_text(node_status_text(), parse_mode=ParseMode.HTML, reply_markup=node_buttons())


async def nodeinstall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not owner_only(update):
        await update.effective_message.reply_text("❌ Owner only.")
        return
    msg = await update.effective_message.reply_text("⏳ Downloading Node.js… this can take a minute.")
    try:
        ver = await asyncio.to_thread(install_node_runtime)
        audit(update.effective_user.id, "node_install", ver)
        await msg.edit_text(node_status_text(), parse_mode=ParseMode.HTML, reply_markup=node_buttons())
    except Exception as exc:
        await msg.edit_text(f"❌ Node install failed: <code>{esc(exc)}</code>", parse_mode=ParseMode.HTML)


async def npminstall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context): return
    if len(context.args) < 2:
        await update.effective_message.reply_text("Usage: /npminstall PROJECT PACKAGE [PACKAGE…]\nExample: /npminstall index.js axios express")
        return
    found = find_project(update.effective_user.id, context.args[0])
    if not found: await update.effective_message.reply_text("❌ Project not found."); return
    _, item = found
    entry = Path(item.entry_file)
    if entry.suffix.lower() not in NODE_EXTS:
        await update.effective_message.reply_text("❌ This is not a Node.js project.")
        return
    packages = context.args[1:]
    if len(packages) > 10 or any(not NPM_SPEC_RE.fullmatch(x) for x in packages):
        await update.effective_message.reply_text("❌ Only plain package names/versions are accepted (max 10).")
        return
    npm = npm_command()
    if not npm:
        await update.effective_message.reply_text("❌ npm not found. Owner: send /nodeinstall")
        return
    root = node_project_root(entry, Path(item.folder))
    msg = await update.effective_message.reply_text(f"📦 Installing <code>{esc(' '.join(packages))}</code>…", parse_mode=ParseMode.HTML)
    try:
        r = await asyncio.to_thread(
            subprocess.run,
            npm + ["install", "--no-audit", "--no-fund", "--no-progress", *packages],
            cwd=root, env=node_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=DEPENDENCY_TIMEOUT_SECONDS,
        )
        out = r.stdout.decode("utf-8", errors="replace")[-MAX_INSTALL_OUTPUT_CHARS:]
        title = "✅ ɪɴsᴛᴀʟʟᴇᴅ — restart the project" if r.returncode == 0 else "❌ ɪɴsᴛᴀʟʟ ғᴀɪʟᴇᴅ"
        await msg.edit_text(premium_box(title, [f"<pre>{esc(out or 'No output')}</pre>"]), parse_mode=ParseMode.HTML)
    except subprocess.TimeoutExpired:
        await msg.edit_text("⏱ npm install timed out.")
    except Exception as exc:
        await msg.edit_text(f"❌ Error: <code>{esc(exc)}</code>", parse_mode=ParseMode.HTML)


async def scheduled_backup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    save_data(); save_projects(); save_v7_data()
    stamp=datetime.now().strftime("%Y%m%d_%H%M%S"); archive=BACKUPS_DIR/f"elevatex_backup_{stamp}.zip"
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
        for f in (DATA_FILE,PROJECTS_FILE,V7_DATA_FILE,V9_DB_FILE):
            if f.exists(): z.write(f,f.name)
    old=sorted(BACKUPS_DIR.glob("elevatex_backup_*.zip"),key=lambda x:x.stat().st_mtime,reverse=True)[7:]
    for f in old: f.unlink(missing_ok=True)
    try: await context.bot.send_document(OWNER_ID,document=InputFile(str(archive)),caption="📦 Automatic ElevateX backup")
    except TelegramError: logger.exception("Automatic backup delivery failed")


# ═════════════════════════════════════════════════════════════════════════════
# JOBS & ERRORS
# ═════════════════════════════════════════════════════════════════════════════

async def auto_restart_job(
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    for uid, items in list(running_scripts.items()):
        async with lock_for(uid):
            for item in items:
                if (
                    not item.running
                    and item.auto_restart
                    and item.restarts < MAX_RESTARTS
                ):
                    try:
                        item.restarts += 1

                        spawn_script(
                            item,
                            Path(item.entry_file),
                            Path(item.folder),
                            Path(item.log_path),
                        )

                        await context.bot.send_message(
                            uid,
                            f"♻️ Auto-restarted "
                            f"{item.display_name}.",
                        )

                    except Exception:
                        logger.exception(
                            "Auto restart failed"
                        )



async def watchdog_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    global watchdog_last_epoch, watchdog_restarts
    if not watchdog_enabled or time.time()-watchdog_last_epoch < watchdog_interval: return
    watchdog_last_epoch=time.time(); now=time.time()
    for uid,items in list(running_scripts.items()):
        async with lock_for(uid):
            for item in items:
                st=project_setting(item)
                # scheduled restarts
                sec=int(st.get("restart_schedule_seconds",0) or 0); nxt=float(st.get("next_restart_at",0) or 0)
                if sec and nxt and now>=nxt:
                    try:
                        if item.running: kill_process(item)
                        spawn_script(item,Path(item.entry_file),Path(item.folder),Path(item.log_path)); st["next_restart_at"]=now+sec; watchdog_restarts+=1
                    except Exception: logger.exception("Scheduled restart failed")
                if item.running: continue
                if not (item.auto_restart or st.get("autostart") or item.desired_running): continue
                crashes=[float(x) for x in st.get("crash_times",[]) if now-float(x)<=CRASH_WINDOW_SECONDS]
                crashes.append(now); st["crash_times"]=crashes[-20:]
                if len(crashes)>CRASH_LIMIT:
                    if not st.get("crash_alerted"):
                        st["crash_alerted"]=True
                        try: await context.bot.send_message(uid,f"🛑 {item.display_name} stopped by crash-loop protection ({len(crashes)} crashes).")
                        except TelegramError: pass
                    continue
                try:
                    spawn_script(item,Path(item.entry_file),Path(item.folder),Path(item.log_path)); watchdog_restarts+=1
                except Exception: logger.exception("Watchdog restart failed")
    save_v7_data(); save_projects()

async def startup_recovery_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    recovered=0
    for uid,items in running_scripts.items():
        async with lock_for(uid):
            for item in items:
                if item.running: continue
                if not (item.desired_running or project_setting(item).get("autostart")): continue
                try: spawn_script(item,Path(item.entry_file),Path(item.folder),Path(item.log_path)); recovered+=1
                except Exception: logger.exception("Startup recovery failed")
    if recovered:
        try: await context.bot.send_message(OWNER_ID,f"♻️ V9 startup recovery restored {recovered} project(s).")
        except TelegramError: pass

async def log_rotation_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    maxb=LOG_ROTATE_MAX_MB*1024*1024; keep=LOG_ROTATE_KEEP_MB*1024*1024
    for items in running_scripts.values():
        for item in items:
            p=Path(item.log_path)
            try:
                if p.exists() and p.stat().st_size>maxb:
                    with p.open("rb") as f: f.seek(-min(keep,p.stat().st_size),2); tail=f.read()
                    p.write_bytes(b"===== ElevateX V9 log rotated =====\n"+tail)
            except OSError: pass

async def panel_reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    global panel_last_reminder_at
    if not panel_reminder_enabled: return
    now=time.time(); due=panel_last_confirmed_at+PANEL_REMINDER_HOURS*3600
    if now<due or (panel_last_reminder_at and now-panel_last_reminder_at<12*3600): return
    panel_last_reminder_at=now; save_v7_data()
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ I Visited Panel",callback_data="admin:panelvisited")]])
    try:
        await context.bot.send_message(OWNER_ID,premium_box("⏰ ᴘᴀɴᴇʟ ʀᴇᴍɪɴᴅᴇʀ",["Your 3-day panel visit reminder is due.","Open your hosting panel manually, then tap the button below or run <code>/panelvisited</code>."]),parse_mode=ParseMode.HTML,reply_markup=kb)
    except TelegramError: logger.exception("Panel reminder failed")


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    logger.exception(
        "Unhandled update error",
        exc_info=context.error,
    )

    if (
        isinstance(update, Update)
        and update.effective_message
    ):
        try:
            await update.effective_message.reply_text(
                "⚠️ An internal error occurred. Try again."
            )
        except TelegramError:
            pass


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    if (
        not TOKEN
        or TOKEN == "PASTE_NEW_BOT_TOKEN_HERE"
    ):
        raise SystemExit(
            "BOT_TOKEN missing. Open main.py and paste your token inside the quotes of "
            "MY_BOT_TOKEN = \"\" (near the top), or create a .env file."
        )

    if OWNER_ID <= 0:
        raise SystemExit(
            "Missing or invalid OWNER_ID (set OWNER_ID in .env)."
        )

    load_data()
    load_v7_data()
    init_v9_database()
    sync_v9_database()
    global FORCE_JOIN_ENABLED, BRAND_NAME
    g=project_settings.get("__global__",{})
    FORCE_JOIN_ENABLED=bool(g.get("force_join_enabled",FORCE_JOIN_ENABLED))
    BRAND_NAME=str(g.get("brand_name",BRAND_NAME))
    expire_plans()
    start_health_server()

    app: Application = (
        ApplicationBuilder()
        .token(TOKEN)
        .connect_timeout(30)
        .read_timeout(60)
        .write_timeout(60)
        .concurrent_updates(32)
        .build()
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("request", request_cmd))
    app.add_handler(CommandHandler("projects", projects_cmd))
    app.add_handler(CommandHandler("status", projects_cmd))
    app.add_handler(CommandHandler("logs", logs_cmd))
    app.add_handler(CommandHandler("credits", credits_cmd))
    app.add_handler(CommandHandler("skip", skip_cmd))
    app.add_handler(CommandHandler("rename", rename_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("restart", restart_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CommandHandler("livestats", live_host_status_cmd))

    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("approve", approve_cmd))
    app.add_handler(CommandHandler("revoke", revoke_cmd))
    app.add_handler(CommandHandler("premium", premium_cmd))
    app.add_handler(CommandHandler("unpremium", unpremium_cmd))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("userinfo", userinfo_cmd))
    app.add_handler(CommandHandler("addcredits", addcredits_cmd))
    app.add_handler(CommandHandler("setcredits", setcredits_cmd))
    app.add_handler(CommandHandler("takecredits", takecredits_cmd))
    app.add_handler(CommandHandler("setdaily", setdaily_cmd))
    app.add_handler(CommandHandler("setrunning", setrunning_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("maintenance", maintenance_cmd))
    app.add_handler(CommandHandler("startall", startall_cmd))
    app.add_handler(CommandHandler("stopalladmin", stopalladmin_cmd))
    app.add_handler(CommandHandler("cleanup", cleanup_cmd))
    app.add_handler(CommandHandler("backup", backup_cmd))
    app.add_handler(CommandHandler("install", install_cmd))
    app.add_handler(CommandHandler("installed", installed_cmd))
    app.add_handler(CommandHandler("setplan", setplan_cmd))
    app.add_handler(CommandHandler("plans", plans_cmd))
    app.add_handler(CommandHandler("createcode", createcode_cmd))
    app.add_handler(CommandHandler("redeem", redeem_cmd))
    app.add_handler(CommandHandler("setenv", setenv_cmd))
    app.add_handler(CommandHandler("env", env_cmd))
    app.add_handler(CommandHandler("delenv", delenv_cmd))
    app.add_handler(CommandHandler("autorestart", autorestart_cmd))
    app.add_handler(CommandHandler("health", health_cmd))
    app.add_handler(CommandHandler("auditlog", auditlog_cmd))
    app.add_handler(CommandHandler("keepalive", keepalive_cmd))
    app.add_handler(CommandHandler("setkeepalive", setkeepalive_cmd))
    app.add_handler(CommandHandler("hoststats", hoststats_cmd))
    app.add_handler(CommandHandler("security", security_cmd))
    app.add_handler(CommandHandler("finduser", finduser_cmd))
    app.add_handler(CommandHandler("allprojects", allprojects_cmd))
    app.add_handler(CommandHandler("restartall", restartall_cmd))
    app.add_handler(CommandHandler("watchdog", watchdog_cmd))
    app.add_handler(CommandHandler("setwatchdog", setwatchdog_cmd))
    app.add_handler(CommandHandler("watchdogstatus", watchdogstatus_cmd))
    app.add_handler(CommandHandler("schedulerestart", schedulerestart_cmd))
    app.add_handler(CommandHandler("scheduleremove", scheduleremove_cmd))
    app.add_handler(CommandHandler("autostart", autostart_cmd))
    app.add_handler(CommandHandler("projectbackup", projectbackup_cmd))
    app.add_handler(CommandHandler("backups", backups_cmd))
    app.add_handler(CommandHandler("restorebackup", restorebackup_cmd))
    app.add_handler(CommandHandler("logsize", logsize_cmd))
    app.add_handler(CommandHandler("clearlogs", clearlogs_cmd))
    app.add_handler(CommandHandler("diagnose", diagnose_cmd))
    app.add_handler(CommandHandler("storage", storage_cmd))
    app.add_handler(CommandHandler("setstorage", setstorage_cmd))
    app.add_handler(CommandHandler("analytics", analytics_cmd))
    app.add_handler(CommandHandler("addadmin", addadmin_cmd))
    app.add_handler(CommandHandler("deladmin", deladmin_cmd))
    app.add_handler(CommandHandler("admins", admins_cmd))
    app.add_handler(CommandHandler("codes", codes_cmd))
    app.add_handler(CommandHandler("disablecode", disablecode_cmd))
    app.add_handler(CommandHandler("deletecode", deletecode_cmd))
    app.add_handler(CommandHandler("codeinfo", codeinfo_cmd))
    app.add_handler(CommandHandler("forcejoin", forcejoin_cmd))
    app.add_handler(CommandHandler("setbrand", setbrand_cmd))
    app.add_handler(CommandHandler("setfooter", setfooter_cmd))
    app.add_handler(CommandHandler("panelreminder", panelreminder_cmd))
    app.add_handler(CommandHandler("panelvisited", panelvisited_cmd))
    app.add_handler(CommandHandler("piplist", piplist_cmd))
    app.add_handler(CommandHandler("requirements", requirements_cmd))
    app.add_handler(CommandHandler("checkcompat", checkcompat_cmd))
    app.add_handler(CommandHandler("repairenv", repairenv_cmd))
    app.add_handler(CommandHandler("npminstall", npminstall_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("nodestatus", nodestatus_cmd))
    app.add_handler(CommandHandler("nodeinstall", nodeinstall_cmd))

    app.add_handler(
        CallbackQueryHandler(callback_handler)
    )
    app.add_handler(
        MessageHandler(
            filters.Document.ALL,
            handle_document,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )

    app.add_error_handler(error_handler)

    if app.job_queue:
        app.job_queue.run_once(startup_recovery_job, when=8)
        app.job_queue.run_repeating(watchdog_job,interval=10, first=20)
        app.job_queue.run_repeating(log_rotation_job, interval=300, first=180)
        app.job_queue.run_repeating(panel_reminder_job, interval=3600, first=60)
        app.job_queue.run_repeating(keepalive_job, interval=5, first=10, name="elevatex_keepalive")
        app.job_queue.run_repeating(
            scheduled_backup_job,
            interval=max(3600, BACKUP_INTERVAL_HOURS * 3600),
            first=120,
        )

    logger.info(
        "%s V9 Stability Pro started | Owner: %s",
        BRAND_NAME,
        OWNER_ID,
    )

    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()