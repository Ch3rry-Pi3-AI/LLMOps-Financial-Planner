#!/usr/bin/env python3
"""
Alex Financial Planner – Local Full-Stack Development Runner.

Starts:
- FastAPI backend (via `uv run main.py` on port 8000)
- Next.js frontend (via `npm run dev` on port 3000)

Behaviour:
1. Validates Node.js, npm, uv
2. Ensures `.env` and `frontend/.env.local` exist
3. Ensures backend/.venv is the ONLY Python environment used
4. Starts backend + waits for /health
5. Starts frontend + waits for http://localhost:3000
6. Monitors logs until Ctrl+C
"""

from __future__ import annotations

import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List

# ============================================================
# 🌍 Project Paths
# ============================================================

PROJECT_ROOT = Path(__file__).parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
BACKEND_API_DIR = BACKEND_DIR / "api"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# The ONLY environment we want to use for Python
BACKEND_VENV = BACKEND_DIR / ".venv"

processes: List[subprocess.Popen[str]] = []


# ============================================================
# 🧹 Cleanup
# ============================================================

def cleanup(signum=None, frame=None):
    print("\n🛑 Shutting down services...")
    for proc in processes:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)


# ============================================================
# 🔧 Environment Helper for Nested `uv`
# ============================================================

def uv_env() -> dict[str, str]:
    """
    Force uv to use backend/.venv instead of scripts/.venv.
    Remove VIRTUAL_ENV entirely so uv auto-detects backend project root.
    """
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)

    # Prepend backend/.venv/bin or Scripts to PATH
    if platform.system() == "Windows":
        bin_dir = BACKEND_VENV / "Scripts"
    else:
        bin_dir = BACKEND_VENV / "bin"

    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    return env


# ============================================================
# ✅ Requirements Check
# ============================================================

def check_requirements():
    checks = []

    # Node.js
    try:
        r = subprocess.run(["node", "--version"], capture_output=True, text=True)
        if r.returncode == 0:
            checks.append(f"✅ Node.js: {r.stdout.strip()}")
        else:
            checks.append("❌ Node.js not found")
    except FileNotFoundError:
        checks.append("❌ Node.js not found")

    # npm
    npm_path = shutil.which("npm")
    if npm_path:
        try:
            if platform.system() == "Windows":
                r = subprocess.run("npm --version", shell=True, capture_output=True, text=True)
            else:
                r = subprocess.run(["npm", "--version"], capture_output=True, text=True)
            if r.returncode == 0:
                checks.append(f"✅ npm: {r.stdout.strip()}")
            else:
                checks.append("✅ npm detected (version check skipped)")
        except Exception:
            checks.append("✅ npm detected (version check skipped)")
    else:
        checks.append("❌ npm not found")

    # uv
    try:
        r = subprocess.run(["uv", "--version"], capture_output=True, text=True)
        if r.returncode == 0:
            checks.append(f"✅ uv: {r.stdout.strip()}")
        else:
            checks.append("❌ uv not found")
    except FileNotFoundError:
        checks.append("❌ uv not found")

    print("\n📋 Prerequisites Check:")
    for c in checks:
        print("  " + c)

    if any("❌" in c for c in checks):
        print("\n⚠️  Missing dependencies. Fix and try again.")
        sys.exit(1)


# ============================================================
# 🌱 Env Files Check
# ============================================================

def check_env_files():
    missing = []
    if not (PROJECT_ROOT / ".env").exists():
        missing.append(".env")
    if not (FRONTEND_DIR / ".env.local").exists():
        missing.append("frontend/.env.local")

    if missing:
        print("\n❌ Missing environment files:")
        for f in missing:
            print("  - " + f)
        sys.exit(1)

    print("✅ Environment files found")


# ============================================================
# 🚀 Backend Startup
# ============================================================

def start_backend():
    print("\n🚀 Starting FastAPI backend...")

    # Sync only if backend environment is missing
    if not BACKEND_VENV.exists():
        print("  📦 Creating backend environment (uv sync backend/)...")
        subprocess.run(["uv", "sync"], cwd=BACKEND_DIR, env=uv_env(), check=True)

    try:
        import httpx  # type: ignore
    except ImportError:
        print("📦 Installing httpx...")
        subprocess.run(["uv", "add", "httpx"], cwd=BACKEND_DIR, env=uv_env(), check=True)
        import httpx

    proc = subprocess.Popen(
        ["uv", "run", "main.py"],
        cwd=BACKEND_API_DIR,
        env=uv_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    processes.append(proc)

    print("  ⏳ Waiting for backend (http://localhost:8000/health)...")

    import httpx
    for _ in range(40):
        try:
            r = httpx.get("http://localhost:8000/health", timeout=1)
            if r.status_code == 200:
                print("  ✅ Backend running at http://localhost:8000")
                return proc
        except Exception:
            pass
        time.sleep(1)

    print("❌ Backend failed to start")
    cleanup()


# ============================================================
# 🚀 Frontend Startup
# ============================================================

def start_frontend():
    print("\n🚀 Starting Next.js frontend...")

    is_win = platform.system() == "Windows"

    # Install node modules if missing
    if not (FRONTEND_DIR / "node_modules").exists():
        print("  📦 Installing frontend dependencies (npm install)...")
        if is_win:
            subprocess.run("npm install", cwd=FRONTEND_DIR, shell=True, check=True)
        else:
            subprocess.run(["npm", "install"], cwd=FRONTEND_DIR, check=True)

    # Start the dev server
    if is_win:
        proc = subprocess.Popen(
            "npm run dev",
            cwd=FRONTEND_DIR,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    else:
        proc = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=FRONTEND_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

    processes.append(proc)

    print("  ⏳ Waiting for frontend (http://localhost:3000)...")

    try:
        import httpx
    except ImportError:
        print("📦 Installing httpx...")
        subprocess.run(["uv", "add", "httpx"], cwd=BACKEND_DIR, env=uv_env(), check=True)
        import httpx

    # Poll the server — NO select(), NO WinError 10038
    for _ in range(60):
        if proc.poll() is not None:
            print("❌ Frontend process exited early")
            cleanup()

        try:
            r = httpx.get("http://localhost:3000", timeout=1)
            if r.status_code < 500:
                print("  ✅ Frontend running at http://localhost:3000")
                return proc
        except Exception:
            pass

        time.sleep(1)

    print("❌ Frontend failed to start")
    cleanup()


# ============================================================
# 📡 Log Monitoring
# ============================================================

def monitor_processes():
    print("\n================ LOGS ================\n")
    while True:
        for proc in list(processes):
            if proc.poll() is not None:
                print("\n⚠️  A process stopped unexpectedly!")
                cleanup()

            if proc.stdout:
                line = proc.stdout.readline()
                if line:
                    print("[LOG]", line.rstrip())
        time.sleep(0.1)


# ============================================================
# 🎯 Main
# ============================================================

def main():
    print("\n🔧 Alex Financial Planner – Local Development Setup")
    print("==================================================")

    check_requirements()
    check_env_files()

    start_backend()
    start_frontend()

    try:
        monitor_processes()
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
