#!/usr/bin/env python3
"""
Run both backend (FastAPI) and frontend (React/Vite) for local development.

Usage:
  python run_all.py                      # backend + frontend
  python run_all.py --backend-only       # backend only (no Node/npm required)
  python run_all.py --reinstall-frontend # fix broken/partial node_modules
  python run_all.py --reload             # enable uvicorn --reload (off by default on Windows)

Corporate proxy (AVD / on-prem):
  set HTTP_PROXY=http://proxy.etisalat.corp.ae:8080
  set HTTPS_PROXY=http://proxy.etisalat.corp.ae:8080
  python run_all.py

  Pip (backend deps), run separately from repo root:
  .venv\\Scripts\\pip install -r backend\\requirements.txt

Node on Windows:
  Add the folder that contains node.exe to PATH (e.g. C:\\Tools\\node-v24.13.1-win-x64).
  Do NOT point PATH at a parent folder — a nested extract causes:
  ...\\node-v24.13.1-win-x64\\node-v24.13.1-win-x64\\node_modules\\npm\\...
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import urlopen

# Colors for terminal output
GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

PROCS: List[subprocess.Popen] = []
ROOT_DIR = Path(__file__).parent.resolve()

DEFAULT_CORP_PROXY = "http://proxy.etisalat.corp.ae:8080"
BACKEND_PORT = 8000
FRONTEND_PORT = 5173


def log(color: str, prefix: str, msg: str) -> None:
    print(f"{color}[{prefix}]{RESET} {msg}")


def apply_proxy_env(env: Dict[str, str]) -> Dict[str, str]:
    """
    Propagate corporate proxy settings for subprocesses (npm, etc.).

    Only applies when HTTP(S)_PROXY or VOICELAB_PROXY is already set.
    Set VOICELAB_PROXY to use the Etisalat default if needed:
      set VOICELAB_PROXY=http://proxy.etisalat.corp.ae:8080
    """
    proxy = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or os.environ.get("VOICELAB_PROXY")
        or ""
    ).strip()

    if not proxy:
        return env

    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env.setdefault(key, proxy)
    env.setdefault("npm_config_proxy", proxy)
    env.setdefault("npm_config_https_proxy", proxy)
    return env


def find_venv_python() -> Path:
    """Prefer repo .venv; fall back to the interpreter running this script."""
    candidates = [
        ROOT_DIR / ".venv" / "Scripts" / "python.exe",
        ROOT_DIR / ".venv" / "bin" / "python",
    ]
    for path in candidates:
        if path.exists():
            return path
    return Path(sys.executable)


def find_node_toolchain() -> Tuple[Optional[Path], Optional[Path], Optional[str]]:
    """
    Resolve node.exe and npm.cmd on PATH.

    Returns (node_exe, npm_cmd, error_message).
    """
    node = shutil.which("node")
    if not node:
        return None, None, (
            "node.exe not found on PATH. Install Node.js LTS and add its folder to PATH "
            "(the directory that contains node.exe, not a parent Downloads folder)."
        )

    node_path = Path(node).resolve()
    node_dir = node_path.parent

    npm_cli_js = node_dir / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if not npm_cli_js.is_file():
        return node_path, None, (
            f"npm is missing next to Node ({npm_cli_js}).\n"
            "  Use the official Windows installer (.msi) or a full node-v*-win-x64 zip, "
            "not a partial copy."
        )

    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        candidate = node_dir / "npm.cmd"
        if candidate.is_file():
            npm = str(candidate)
        else:
            return node_path, None, (
                f"npm.cmd not found beside {node_path}. Add {node_dir} to PATH."
            )

    return node_path, Path(npm).resolve(), None


def run_node_npm(
    node_exe: Path,
    npm_cmd: Path,
    args: List[str],
    cwd: Path,
    env: Dict[str, str],
) -> None:
    """
    Run npm via ``node …/npm-cli.js`` so a broken npm.cmd shim (common on AVD)
    does not double the install path.
    """
    npm_cli = node_exe.parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    if npm_cli.is_file():
        cmd = [str(node_exe), str(npm_cli)] + args
    else:
        cmd = [str(npm_cmd)] + args
    subprocess.run(cmd, cwd=str(cwd), env=env, shell=False, check=True)


def vite_dist_cli(frontend_dir: Path) -> Path:
    """File vite.js imports; missing => incomplete npm install (common on AVD)."""
    return frontend_dir / "node_modules" / "vite" / "dist" / "node" / "cli.js"


def is_frontend_deps_ready(frontend_dir: Path) -> bool:
    return vite_dist_cli(frontend_dir).is_file()


def remove_frontend_node_modules(frontend_dir: Path) -> None:
    nm = frontend_dir / "node_modules"
    if not nm.exists():
        return
    log(YELLOW, "FRONTEND", f"Removing incomplete {nm} ...")
    shutil.rmtree(nm)


def npm_install_frontend(frontend_dir: Path, env: Dict[str, str]) -> None:
    node, npm, err = find_node_toolchain()
    if err:
        log(RED, "FRONTEND", err)
        log(YELLOW, "FRONTEND", "Install deps manually, then re-run:")
        log(YELLOW, "FRONTEND", f"  cd {frontend_dir}")
        log(YELLOW, "FRONTEND", "  set HTTP_PROXY=http://proxy.etisalat.corp.ae:8080")
        log(YELLOW, "FRONTEND", "  npm install")
        log(YELLOW, "FRONTEND", "Or use backend only:  python run_all.py --backend-only")
        raise SystemExit(1)

    lock = frontend_dir / "package-lock.json"
    npm_args = ["ci"] if lock.is_file() else ["install"]
    log(
        YELLOW,
        "FRONTEND",
        f"Running npm {' '.join(npm_args)} (proxy from HTTP_PROXY / VOICELAB_PROXY)...",
    )
    run_node_npm(node, npm, npm_args, frontend_dir, env)


def ensure_frontend_deps(
    frontend_dir: Path, env: Dict[str, str], *, force_reinstall: bool = False
) -> None:
    """
    Ensure frontend/node_modules contains a complete Vite install.

    A partial copy or interrupted ``npm install`` leaves ``node_modules`` present
    but without ``vite/dist/node/cli.js`` — that causes ERR_MODULE_NOT_FOUND at dev time.
    """
    if force_reinstall:
        remove_frontend_node_modules(frontend_dir)

    if is_frontend_deps_ready(frontend_dir):
        return

    if (frontend_dir / "node_modules").exists():
        log(
            YELLOW,
            "FRONTEND",
            "node_modules exists but Vite is incomplete (missing vite/dist/node/cli.js). "
            "Reinstalling...",
        )
        remove_frontend_node_modules(frontend_dir)

    npm_install_frontend(frontend_dir, env)

    if not is_frontend_deps_ready(frontend_dir):
        log(RED, "FRONTEND", "npm install finished but Vite is still missing.")
        log(YELLOW, "FRONTEND", "Try manually:")
        log(YELLOW, "FRONTEND", f"  cd {frontend_dir}")
        log(YELLOW, "FRONTEND", "  rmdir /s /q node_modules")
        log(YELLOW, "FRONTEND", "  set HTTP_PROXY=http://proxy.etisalat.corp.ae:8080")
        log(YELLOW, "FRONTEND", "  npm install")
        log(YELLOW, "FRONTEND", "Or: python run_all.py --reinstall-frontend")
        raise SystemExit(1)


def run_vite_dev(frontend_dir: Path, env: Dict[str, str]) -> List[str]:
    """Start Vite dev server via local binary (after ensure_frontend_deps)."""
    if not is_frontend_deps_ready(frontend_dir):
        raise RuntimeError(
            "Frontend dependencies are not ready. Run: python run_all.py --reinstall-frontend"
        )

    # Docker sets VITE_HOST / HOST=0.0.0.0 so the UI is reachable outside the container.
    vite_host = (
        os.environ.get("VITE_HOST")
        or ("0.0.0.0" if os.environ.get("HOST", "").strip() == "0.0.0.0" else "127.0.0.1")
    ).strip() or "127.0.0.1"

    node, npm, err = find_node_toolchain()
    vite_js = frontend_dir / "node_modules" / "vite" / "bin" / "vite.js"
    if node and vite_js.is_file():
        return [str(node), str(vite_js), "--host", vite_host, "--port", str(FRONTEND_PORT)]
    if npm:
        return [str(npm), "run", "dev", "--", "--host", vite_host, "--port", str(FRONTEND_PORT)]
    raise RuntimeError(err or "Cannot start frontend: Node/npm not available.")


def free_port(port: int) -> None:
    """Kill any process currently listening on *port* (Windows + Unix)."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        if s.connect_ex(("127.0.0.1", port)) != 0:
            return  # port is free

    if os.name == "nt":
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if f":{port} " in line and "LISTEN" in line:
                    parts = line.split()
                    pid = int(parts[-1])
                    if pid > 0:
                        log(YELLOW, "PORT", f"Freeing port {port} (PID {pid})...")
                        subprocess.run(
                            ["taskkill", "/PID", str(pid), "/F"],
                            capture_output=True,
                        )
        except Exception as e:
            log(YELLOW, "PORT", f"Could not free port {port}: {e}")
    else:
        try:
            result = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for pid_str in result.stdout.split():
                pid = int(pid_str.strip())
                if pid > 0:
                    log(YELLOW, "PORT", f"Freeing port {port} (PID {pid})...")
                    subprocess.run(["kill", "-9", str(pid)], capture_output=True)
        except Exception as e:
            log(YELLOW, "PORT", f"Could not free port {port}: {e}")

    time.sleep(0.5)


def start_backend(*, enable_reload: bool = False) -> subprocess.Popen:
    """Start FastAPI backend with uvicorn (matches README / run_dev.ps1)."""
    env = apply_proxy_env(os.environ.copy())

    venv_python = find_venv_python()
    if ".venv" not in str(venv_python):
        log(
            YELLOW,
            "BACKEND",
            "No .venv found — using current Python. Prefer: python -m venv .venv",
        )

    # Docker sets HOST=0.0.0.0 so the port is reachable outside the container.
    host = os.environ.get("HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("PORT", str(BACKEND_PORT)) or BACKEND_PORT)
    free_port(port)

    cmd = [
        str(venv_python),
        "-m",
        "uvicorn",
        "app.main:app",
        "--app-dir",
        "backend",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if enable_reload:
        cmd.append("--reload")

    log(GREEN, "BACKEND", f"Starting FastAPI on http://{host}:{port}")
    log(GREEN, "BACKEND", f"Command: {' '.join(cmd)}")

    return subprocess.Popen(
        cmd,
        cwd=str(ROOT_DIR),
        env=env,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


def wait_for_backend(timeout_sec: float = 45, poll_interval: float = 0.5) -> bool:
    # FastAPI serves /openapi.json without auth — no /health in this app.
    port = int(os.environ.get("PORT", str(BACKEND_PORT)) or BACKEND_PORT)
    url = f"http://127.0.0.1:{port}/openapi.json"
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as r:
                if r.getcode() == 200:
                    return True
        except (URLError, OSError):
            pass
        time.sleep(poll_interval)
    return False


def start_frontend(*, force_reinstall: bool = False) -> subprocess.Popen:
    """Start Vite React frontend (proxies /api → backend)."""
    frontend_dir = ROOT_DIR / "frontend"
    env = apply_proxy_env(os.environ.copy())

    free_port(FRONTEND_PORT)
    ensure_frontend_deps(frontend_dir, env, force_reinstall=force_reinstall)

    cmd = run_vite_dev(frontend_dir, env)

    log(BLUE, "FRONTEND", f"Starting Vite on http://localhost:{FRONTEND_PORT}")
    log(BLUE, "FRONTEND", f"Command: {' '.join(cmd)}")

    return subprocess.Popen(
        cmd,
        cwd=str(frontend_dir),
        env=env,
        shell=False,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


def cleanup() -> None:
    log(YELLOW, "SHUTDOWN", "Stopping all processes...")
    for proc in PROCS:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    log(GREEN, "SHUTDOWN", "All processes stopped")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run e& Lahja Studio (VoiceLab) backend and/or frontend."
    )
    p.add_argument(
        "--backend-only",
        action="store_true",
        help="Start only the FastAPI backend (skip Node/npm frontend).",
    )
    p.add_argument(
        "--reinstall-frontend",
        action="store_true",
        help="Delete frontend/node_modules and run npm install/ci before starting Vite.",
    )
    p.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn auto-reload (off by default on Windows).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    print(
        f"""
{GREEN}===============================================================
  e& Lahja Studio - Local Development Server
==============================================================={RESET}
"""
    )

    signal.signal(signal.SIGINT, lambda _s, _f: None)

    try:
        backend_proc = start_backend(enable_reload=args.reload)
        PROCS.append(backend_proc)

        log(BLUE, "BACKEND", "Waiting for backend to be ready...")
        if wait_for_backend():
            log(GREEN, "BACKEND", "Backend is ready")
        else:
            log(YELLOW, "BACKEND", "Backend not ready in time; continuing anyway")

        if args.backend_only:
            print(
                f"""
{GREEN}===============================================================
  Backend:  http://127.0.0.1:{BACKEND_PORT}
  API Docs: http://127.0.0.1:{BACKEND_PORT}/docs
  Login:    admin / changeme
  (Frontend skipped — --backend-only)
==============================================================={RESET}

Press Ctrl+C to stop...
"""
            )
        else:
            frontend_proc = start_frontend(force_reinstall=args.reinstall_frontend)
            PROCS.append(frontend_proc)
            print(
                f"""
{GREEN}===============================================================
  Backend:  http://127.0.0.1:{BACKEND_PORT}
  Frontend: http://localhost:{FRONTEND_PORT}
  API Docs: http://127.0.0.1:{BACKEND_PORT}/docs
  Login:    admin / changeme
==============================================================={RESET}

Press Ctrl+C to stop all servers...
"""
            )

        while True:
            for proc in PROCS:
                if proc.poll() is not None:
                    log(RED, "ERROR", f"Process exited with code {proc.returncode}")
                    cleanup()
                    return proc.returncode or 1
            time.sleep(1)

    except KeyboardInterrupt:
        print()
    except SystemExit as e:
        cleanup()
        return int(e.code) if isinstance(e.code, int) else 1
    except subprocess.CalledProcessError as e:
        log(RED, "ERROR", f"Command failed with exit code {e.returncode}")
        cleanup()
        return e.returncode or 1
    except RuntimeError as e:
        log(RED, "ERROR", str(e))
        cleanup()
        return 1
    finally:
        cleanup()

    return 0


if __name__ == "__main__":
    sys.exit(main())
