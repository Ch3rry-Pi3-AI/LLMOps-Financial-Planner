#!/usr/bin/env python3
"""
Alex Financial Planner – Local Full-Stack Development Runner.

This script provides a **one-command local dev experience** by starting both the:

- FastAPI backend (via ``uv run main.py`` on port 8000)
- Next.js frontend (via ``npm run dev`` on port 3000)

It will:

1. Verify that core tools are installed:
   - Node.js
   - npm
   - uv (Python environment manager)
2. Check that required environment files exist:
   - ``.env`` at the project root
   - ``frontend/.env.local`` for frontend (e.g. Clerk keys)
3. Ensure ``httpx`` is available for health checks (installing via ``uv add`` if needed)
4. Start the backend and wait for a healthy ``/health`` response
5. Start the frontend and wait until the dev server is reachable
6. Stream logs from both processes and handle clean shutdown on Ctrl+C

Typical usage
-------------
# From the project root:
uv run scripts/run_local.py
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Sequence

# ============================================================
# 🌍 Project Paths & Globals
# ============================================================

PROJECT_ROOT = Path(__file__).parent.parent
BACKEND_API_DIR = PROJECT_ROOT / "backend" / "api"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# Track subprocesses for clean shutdown
processes: List[subprocess.Popen[str]] = []


# ============================================================
# 🧹 Process Cleanup & Signal Handling
# ============================================================

def cleanup(signum: int | None = None, frame: object | None = None) -> None:  # noqa: ARG001
    """
    Terminate all child processes and exit.

    This is invoked when:
    - The user presses Ctrl+C (SIGINT)
    - The process receives SIGTERM
    - Any managed subprocess exits unexpectedly
    """
    print("\n🛑 Shutting down services...")
    for proc in processes:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            # Fallback to hard kill if graceful terminate fails
            try:
                proc.kill()
            except Exception:
                pass

    sys.exit(0)


# Register signal handlers for graceful shutdown
signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)


# ============================================================
# ✅ Prerequisite Checks
# ============================================================

def check_requirements() -> None:
    """
    Verify that required tooling is installed (Node.js, npm, uv).

    Exits the process with a non-zero status if any critical tool is missing.
    """
    checks: list[str] = []

    # Node.js
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            checks.append(f"✅ Node.js: {result.stdout.strip()}")
        else:
            checks.append("❌ Node.js not found - please install Node.js")
    except FileNotFoundError:
        checks.append("❌ Node.js not found - please install Node.js")

    # npm
    try:
        result = subprocess.run(
            ["npm", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            checks.append(f"✅ npm: {result.stdout.strip()}")
        else:
            checks.append("❌ npm not found - please install npm")
    except FileNotFoundError:
        checks.append("❌ npm not found - please install npm")

    # uv
    try:
        result = subprocess.run(
            ["uv", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            checks.append(f"✅ uv: {result.stdout.strip()}")
        else:
            checks.append("❌ uv not found - please install uv")
    except FileNotFoundError:
        checks.append("❌ uv not found - please install uv")

    print("\n📋 Prerequisites Check:")
    for check in checks:
        print(f"  {check}")

    if any("❌" in check for check in checks):
        print("\n⚠️  Please install missing dependencies and try again.")
        sys.exit(1)


def check_env_files() -> None:
    """
    Ensure required environment files exist.

    Required:
    - ``.env`` in the project root (backend variables from Parts 1–7)
    - ``frontend/.env.local`` (e.g. Clerk keys for local auth)
    """
    root_env = PROJECT_ROOT / ".env"
    frontend_env = FRONTEND_DIR / ".env.local"

    missing: list[str] = []

    if not root_env.exists():
        missing.append(".env (root project file)")
    if not frontend_env.exists():
        missing.append("frontend/.env.local")

    if missing:
        print("\n⚠️  Missing environment files:")
        for file in missing:
            print(f"  - {file}")
        print("\nPlease create these files with the required configuration.")
        print("The root .env should have all backend variables from Parts 1–7.")
        print("The frontend/.env.local should have Clerk keys and other frontend config.")
        sys.exit(1)

    print("✅ Environment files found")


# ============================================================
# 🚀 Backend Startup (FastAPI)
# ============================================================

def start_backend() -> subprocess.Popen[str]:
    """
    Start the FastAPI backend using uv.

    Behaviour
    ---------
    - Ensures backend dependencies are installed (``uv sync`` if no ``.venv`` and no ``uv.lock``)
    - Starts the app via ``uv run main.py``
    - Polls ``http://localhost:8000/health`` until a 200 OK is returned or times out
    """
    print("\n🚀 Starting FastAPI backend...")

    if not BACKEND_API_DIR.exists():
        print(f"  ❌ Backend directory not found: {BACKEND_API_DIR}")
        sys.exit(1)

    # Install dependencies if needed
    if not (BACKEND_API_DIR / ".venv").exists() and not (BACKEND_API_DIR / "uv.lock").exists():
        print("  📦 Installing backend dependencies (uv sync)...")
        subprocess.run(["uv", "sync"], cwd=BACKEND_API_DIR, check=True)

    # Lazy import httpx here so that main() can install it first
    try:
        import httpx  # type: ignore[import]
    except ImportError:
        print("  ❌ httpx not installed; please re-run via main() so it can be added.")
        sys.exit(1)

    proc = subprocess.Popen(
        ["uv", "run", "main.py"],
        cwd=BACKEND_API_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    processes.append(proc)

    print("  ⏳ Waiting for backend to start (http://localhost:8000/health)...")
    for _ in range(30):  # up to ~30 seconds
        try:
            response = httpx.get("http://localhost:8000/health", timeout=1.0)
            if response.status_code == 200:
                print("  ✅ Backend running at http://localhost:8000")
                print("     API docs: http://localhost:8000/docs")
                return proc
        except Exception:
            time.sleep(1)

    print("  ❌ Backend failed to start within timeout window")
    cleanup()
    raise SystemExit(1)


# ============================================================
# 🚀 Frontend Startup (Next.js Dev Server)
# ============================================================

def start_frontend() -> subprocess.Popen[str]:
    """
    Start the Next.js frontend dev server.

    Behaviour
    ---------
    - Installs Node dependencies if ``node_modules`` is missing (``npm install``)
    - Starts the dev server via ``npm run dev``
    - Streams initial logs looking for readiness hints ("ready"/"compiled"/"started server")
    - Polls ``http://localhost:3000`` until reachable or timeout
    """
    print("\n🚀 Starting Next.js frontend...")

    if not FRONTEND_DIR.exists():
        print(f"  ❌ Frontend directory not found: {FRONTEND_DIR}")
        sys.exit(1)

    # Install dependencies if needed
    if not (FRONTEND_DIR / "node_modules").exists():
        print("  📦 Installing frontend dependencies (npm install)...")
        subprocess.run(["npm", "install"], cwd=FRONTEND_DIR, check=True)

    proc = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=FRONTEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # Combine stderr with stdout
        text=True,
        bufsize=1,
    )
    processes.append(proc)

    print("  ⏳ Waiting for frontend to start on http://localhost:3000...")
    import select  # type: ignore[import]

    try:
        import httpx  # type: ignore[import]
    except ImportError:
        print("  ❌ httpx not installed; please re-run via main() so it can be added.")
        sys.exit(1)

    started = False

    for i in range(30):  # ~30 seconds
        # Non-blocking read of any available process output
        if proc.stdout:
            ready, _, _ = select.select([proc.stdout], [], [], 0)
            if ready:
                line = proc.stdout.readline()
                if line:
                    print(f"    Frontend: {line.strip()}")
                    lowered = line.lower()
                    if "ready" in lowered or "compiled" in lowered or "started server" in lowered:
                        started = True

        # Also try connecting directly after a small delay or when logs suggest readiness
        if started or i > 5:
            try:
                response = httpx.get("http://localhost:3000", timeout=1.0)
                if response.status_code < 500:
                    print("  ✅ Frontend running at http://localhost:3000")
                    return proc
            except httpx.ConnectError:
                # Server not yet accepting connections
                pass
            except Exception:
                # Any other response/exception is taken as "something is listening"
                print("  ✅ Frontend running at http://localhost:3000")
                return proc

        time.sleep(1)

    print("  ❌ Frontend failed to start within timeout window")
    cleanup()
    raise SystemExit(1)


# ============================================================
# 📡 Process Monitoring & Logging
# ============================================================

def monitor_processes() -> None:
    """
    Monitor running frontend and backend processes and stream their logs.

    Exits and triggers cleanup if any process stops unexpectedly.
    """
    print("\n" + "=" * 60)
    print("🎯 Alex Financial Planner – Local Development")
    print("=" * 60)
    print("\n📍 Services:")
    print("  Frontend: http://localhost:3000")
    print("  Backend:  http://localhost:8000")
    print("  API Docs: http://localhost:8000/docs")
    print("\n📝 Logs will appear below. Press Ctrl+C to stop.\n")
    print("=" * 60 + "\n")

    while True:
        for proc in list(processes):
            # If any process exits, tear everything down
            if proc.poll() is not None:
                print("\n⚠️  A process has stopped unexpectedly!")
                cleanup()

            # Stream any available stdout line
            if proc.stdout:
                try:
                    line = proc.stdout.readline()
                    if line:
                        print(f"[LOG] {line.strip()}")
                except Exception:
                    # Ignore transient read issues; main loop will keep going
                    pass

        time.sleep(0.1)


# ============================================================
# 🚀 CLI Entry Point
# ============================================================

def ensure_httpx_installed() -> None:
    """
    Ensure ``httpx`` is available in the active uv environment.

    If import fails, installs it using ``uv add httpx``.
    """
    try:
        import httpx  # type: ignore[import, unused-import]
        return
    except ImportError:
        print("\n📦 Installing httpx for health checks...")
        subprocess.run(["uv", "add", "httpx"], check=True)


def main() -> None:
    """
    Main entry point for local development.

    Steps
    -----
    1. Check system prerequisites (Node.js, npm, uv)
    2. Verify required environment files exist
    3. Ensure ``httpx`` is installed (via uv)
    4. Start backend (FastAPI) and wait for health
    5. Start frontend (Next.js) and wait for readiness
    6. Monitor both processes and stream logs until interrupted
    """
    print("\n🔧 Alex Financial Planner – Local Development Setup")
    print("=" * 50)

    check_requirements()
    check_env_files()
    ensure_httpx_installed()

    # Start services
    start_backend()
    start_frontend()

    # Monitor
    try:
        monitor_processes()
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
