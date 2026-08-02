from __future__ import annotations

import logging
import os
import socket
import sys
from pathlib import Path

INSTALL_DIR = Path(__file__).resolve().parents[1]
LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
DATA_DIR = LOCAL_APPDATA / "ReelIndex"
LOG_DIR = DATA_DIR / "logs"
STATIC_DIR = INSTALL_DIR / "app" / "web"
TOOLS_DIR = INSTALL_DIR / "tools"
PORT_FILE = DATA_DIR / "server.port"
PID_FILE = DATA_DIR / "server.pid"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("REELINDEX_DATA_DIR", str(DATA_DIR))
os.environ.setdefault("REELINDEX_STATIC_DIR", str(STATIC_DIR))
os.environ.setdefault("REELINDEX_FFPROBE_PATH", str(TOOLS_DIR / "ffprobe.exe"))
os.environ.setdefault("REELINDEX_MEDIAINFO_PATH", str(TOOLS_DIR / "mediainfo.exe"))
os.environ.setdefault("REELINDEX_WINDOWS_MODE", "true")
os.environ.setdefault("REELINDEX_CORS_ORIGINS", "http://127.0.0.1:8765,http://localhost:8765")
os.environ.setdefault("REELINDEX_LOG_LEVEL", "INFO")

sys.path.insert(0, str(INSTALL_DIR / "app"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "reelindex.log", encoding="utf-8")],
    force=True,
)
logger = logging.getLogger("reelindex.windows")


def choose_port() -> int:
    for port in range(8765, 8785):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("No free local port was available between 8765 and 8784")


def main() -> int:
    port = choose_port()
    PORT_FILE.write_text(str(port), encoding="ascii")
    PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    os.environ["REELINDEX_CORS_ORIGINS"] = f"http://127.0.0.1:{port},http://localhost:{port}"

    from app.main import app
    import uvicorn

    logger.info("Starting ReelIndex on http://127.0.0.1:%s", port)
    try:
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info", access_log=False)
        uvicorn.Server(config).run()
        return 0
    except Exception:
        logger.exception("ReelIndex server stopped unexpectedly")
        return 1
    finally:
        for path in (PID_FILE, PORT_FILE):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
