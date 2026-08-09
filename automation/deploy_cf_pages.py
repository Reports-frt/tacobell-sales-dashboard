# -*- coding: utf-8 -*-
"""
Deploy the dashboard to Cloudflare Pages (parallel hosting next to GitHub Pages).

Called at the end of the daily pipelines (sales + food) so the Cloudflare copy
stays as fresh as the GitHub one. Idempotent: stages the current serve-files to
a temp dir, applies the agent-chat overlay (the repo files stay untouched β€”
GitHub Pages keeps serving WITHOUT the chat until the cutover), and deploys.

Auth: wrangler's machine-wide OAuth (no PAT, no secrets in this repo).
Logs: _work/cf_deploy.log
"""
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(r"C:\Users\IT\Documents\GitHub\tacobell-sales-dashboard")
PROJECT = "tacobell-dashboard"
WRANGLER = Path(r"C:\Projects\kfc-labour-schedule\worker\node_modules\.bin\wrangler.cmd")

SERVE_FILES = [
    "index.html", "data.json", "manifest.json", "service-worker.js",
    "favicon.png", "icon-180.png", "icon-192.png", "icon-512.png",
    "icon-maskable-512.png", "food/index.html", "food/food_data.json",
]
OVERLAY_JS = REPO / "automation" / "cf_overlay" / "agent-chat.js"

# --- chat overlay patches (must mirror what the cutover will bake in) --------
# Remember-me: ΟƒΟ„ΞΏ PWA Ο„ΞΏ sessionStorage Ξ±Ξ΄ΞµΞΉΞ±Ξ¶ΞµΞΉ ΟƒΞµ ΞΞ‘ΞΞ• Ξ±Ξ½ΞΏΞΉΞ³ΞΌΞ± Ο„ΞΏΟ… app,
# ΞΏΟ€ΞΏΟ„Ξµ Ξ¶Ξ·Ο„Ξ±Ξ³Ξµ ΞΊΟ‰Ξ΄ΞΉΞΊΞΏ ΞΊΞ±ΞΈΞµ Ο†ΞΏΟΞ±. Ξ¤ΞΏ localStorage ΞµΟ€ΞΉΞ²ΞΉΟ‰Ξ½ΞµΞΉ Ο„Ξ± ΞΊΞ»ΞµΞΉΟƒΞΉΞΌΞ±Ο„Ξ±.
GATE_GET_OLD = 'if (sessionStorage.getItem(__SESSION_KEY__) === "1") {'
GATE_GET_NEW = 'if (localStorage.getItem(__SESSION_KEY__) === "1" || sessionStorage.getItem(__SESSION_KEY__) === "1") {'
GATE_ANCHOR = 'try { sessionStorage.setItem(__SESSION_KEY__, "1"); } catch(e) {}'
GATE_HOOK = ('\n      try { localStorage.setItem(__SESSION_KEY__, "1"); } catch(e) {}'
             '\n      try { localStorage.setItem("tb_agent_pw", pw); } catch(e) {}')
SW_OLD_VERSION = "const CACHE_VERSION = 'tacobell-dashboard-v14';"
SW_NEW_VERSION = "const CACHE_VERSION = 'tacobell-dashboard-v15';  // v15: Cloudflare (persinos kairos)"
SW_SHELL_ANCHOR = "  './index.html',"

LOG_FILE = REPO / "_work" / "cf_deploy.log"
LOG_FILE.parent.mkdir(exist_ok=True)
logging.basicConfig(filename=str(LOG_FILE), level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("cf_deploy")


def insert_after(text, anchor, addition, label):
    """Insert `addition` right after `anchor`, once. Idempotent."""
    if addition in text:
        log.info(f"  {label}: already applied")
        return text
    if anchor not in text:
        log.warning(f"  {label}: anchor NOT FOUND β€” deploying unpatched")
        return text
    return text.replace(anchor, anchor + addition, 1)


def replace_once(text, old, new, label):
    """Replace `old` with `new`, once. Idempotent."""
    if new in text:
        log.info(f"  {label}: already applied")
        return text
    if old not in text:
        log.warning(f"  {label}: anchor NOT FOUND β€” deploying unpatched")
        return text
    return text.replace(old, new, 1)


def main():
    log.info(f"=== Cloudflare Pages deploy: {PROJECT} ===")
    if not WRANGLER.exists():
        log.error(f"wrangler not found: {WRANGLER}")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="cf_pages_"))
    try:
        # 1. stage serve-files (repo stays untouched)
        for rel in SERVE_FILES:
            src = REPO / rel
            if not src.exists():
                log.warning(f"  missing (skipped): {rel}")
                continue
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        shutil.copy2(OVERLAY_JS, tmp / "agent-chat.js")

        # 2. overlay: chat widget wiring
        idx = tmp / "index.html"
        s = idx.read_text(encoding="utf-8")
        s = replace_once(s, GATE_GET_OLD, GATE_GET_NEW, "gate-remember-get")
        s = insert_after(s, GATE_ANCHOR, GATE_HOOK, "gate-hook")
        s = replace_once(s, "</body>",
                         '<script src="agent-chat.js" defer></script>\n</body>', "chat-script")
        idx.write_text(s, encoding="utf-8")

        sw = tmp / "service-worker.js"
        s = sw.read_text(encoding="utf-8")
        s = replace_once(s, SW_OLD_VERSION, SW_NEW_VERSION, "sw-version")
        s = insert_after(s, SW_SHELL_ANCHOR, "\n  './agent-chat.js',", "sw-shell")
        sw.write_text(s, encoding="utf-8")

        # 3. deploy
        result = subprocess.run(
            [str(WRANGLER), "pages", "deploy", str(tmp),
             "--project-name", PROJECT, "--branch", "main", "--commit-dirty=true"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=600,
        )
        for line in (result.stdout + result.stderr).splitlines():
            if line.strip():
                log.info(f"  {line.strip()}")
        if result.returncode != 0:
            log.error(f"deploy failed (exit {result.returncode})")
            return 1
        log.info("=== deploy OK ===")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
