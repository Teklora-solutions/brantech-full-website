"""Codex Device Code Authentication Service.

Manages interactive device-authorization login with OpenAI / ChatGPT subscription
backend (`https://auth.openai.com/codex/device`).
Spawns background polling or manages tokens so users can connect ChatGPT Plus/Pro
without manual copy-pasting of private auth cookies.
"""
import logging
import os
import pty
import re
import select
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Optional

from django.utils import timezone
from brandtechsolution.config import config

logger = logging.getLogger(__name__)

# Active device code login sessions: session_id -> state
_ACTIVE_LOGIN_SESSIONS: Dict[str, dict] = {}
_SESSION_LOCK = threading.Lock()


class CodexDeviceAuthService:
    """Handles starting Codex device authorization and polling for status."""

    @classmethod
    def get_status(cls) -> dict:
        """Return current Codex connection status."""
        from ai_workflows.models import Provider

        provider_row = Provider.objects.filter(name="codex").first()
        is_enabled = bool(provider_row.enabled) if provider_row else False
        has_env_token = bool((getattr(config, "codex_oauth_token", "") or "").strip())

        local_auth_path = Path.home() / ".codex" / "auth.json"
        has_local_auth = False
        user_email = ""
        plan_type = ""

        if local_auth_path.exists():
            try:
                import json
                with local_auth_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    has_local_auth = bool(data.get("tokens", {}).get("access_token"))
                    # Parse JWT id_token payload if present for display
                    id_tok = data.get("tokens", {}).get("id_token")
                    if id_tok and "." in id_tok:
                        import base64
                        parts = id_tok.split(".")
                        if len(parts) >= 2:
                            padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
                            payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
                            user_email = payload.get("email", "")
                            auth_dict = payload.get("https://api.openai.com/auth", {})
                            plan_type = auth_dict.get("chatgpt_plan_type", "ChatGPT Subscription")
            except Exception as e:
                logger.debug("[codex] Failed reading local auth info: %s", e)

        connected = has_env_token or has_local_auth
        return {
            "connected": connected,
            "enabled": is_enabled,
            "has_env_token": has_env_token,
            "has_local_auth": has_local_auth,
            "account_email": user_email,
            "plan_type": plan_type,
            "status": "connected" if connected and is_enabled else ("ready" if connected else "disconnected"),
        }

    @classmethod
    def start_device_auth(cls) -> dict:
        """Start `codex login --device-auth` in a pseudo-terminal and capture device code."""
        codex_bin = "/home/bigaddict/.local/bin/codex"
        if not os.path.exists(codex_bin):
            import shutil
            codex_bin = shutil.which("codex") or "codex"

        session_id = f"codex_auth_{int(time.time())}"
        session_state = {
            "session_id": session_id,
            "status": "initializing",
            "verification_url": "https://auth.openai.com/codex/device",
            "user_code": None,
            "error": None,
            "started_at": time.time(),
            "completed": False,
        }

        with _SESSION_LOCK:
            _ACTIVE_LOGIN_SESSIONS[session_id] = session_state

        def run_auth_worker():
            try:
                master, slave = pty.openpty()
                pid = os.fork()
                if pid == 0:
                    os.close(master)
                    os.setsid()
                    os.dup2(slave, 0)
                    os.dup2(slave, 1)
                    os.dup2(slave, 2)
                    os.close(slave)
                    os.environ["TERM"] = "xterm"
                    os.execv(codex_bin, ["codex", "login", "--device-auth"])
                else:
                    os.close(slave)
                    chunks = []
                    start_t = time.time()
                    code_extracted = False

                    # Read loop
                    while time.time() - start_t < 900:  # 15 minutes max
                        r, _, _ = select.select([master], [], [], 0.5)
                        if r:
                            try:
                                data = os.read(master, 1024)
                            except OSError:
                                break
                            if not data:
                                break
                            text = data.decode("utf-8", errors="ignore")
                            chunks.append(text)
                            full_text = "".join(chunks)
                            clean_text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", full_text)

                            if not code_extracted and "Enter this one-time code" in clean_text:
                                match = re.search(r"([A-Z0-9]{4,6}-[A-Z0-9]{4,6})", clean_text)
                                if match:
                                    code = match.group(1)
                                    session_state["user_code"] = code
                                    session_state["status"] = "awaiting_approval"
                                    code_extracted = True

                            if "Successfully signed in" in clean_text or "Logged in" in clean_text or "Login successful" in clean_text:
                                session_state["status"] = "success"
                                session_state["completed"] = True
                                break

                        # Check if process exited
                        try:
                            res = os.waitpid(pid, os.WNOHANG)
                            if res and res[0] == pid:
                                break
                        except ChildProcessError:
                            break

                    try:
                        os.close(master)
                    except OSError:
                        pass

                    try:
                        import signal
                        os.kill(pid, signal.SIGTERM)
                    except Exception:
                        pass

                    # If successful or finished, activate in DB
                    from ai_workflows.models import Provider
                    provider_row, _ = Provider.objects.get_or_create(name="codex")
                    provider_row.status = Provider.ACTIVE
                    provider_row.enabled = True
                    provider_row.last_checked_at = timezone.now()
                    provider_row.save(update_fields=["status", "enabled", "last_checked_at"])

                    session_state["status"] = "success"
                    session_state["completed"] = True

            except Exception as e:
                logger.exception("[codex] Device auth worker exception: %s", e)
                session_state["status"] = "error"
                session_state["error"] = str(e)
                session_state["completed"] = True

        thread = threading.Thread(target=run_auth_worker, daemon=True)
        thread.start()

        # Wait up to 3.5s for initial code extraction before returning response
        for _ in range(7):
            if session_state.get("user_code"):
                break
            time.sleep(0.5)

        return session_state

    @classmethod
    def poll_session(cls, session_id: str) -> dict:
        """Poll the state of an in-flight device auth session."""
        with _SESSION_LOCK:
            session = _ACTIVE_LOGIN_SESSIONS.get(session_id)
            if not session:
                return {"status": "not_found", "completed": True}
            return dict(session)
