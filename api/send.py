from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from http.server import BaseHTTPRequestHandler
import json
import mimetypes
import os
import re
import smtplib
import ssl
from supabase import create_client

supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_ROLE_KEY"],
)

GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
ALLOWED_ORIGIN = os.environ["ALLOWED_ORIGIN"]

EMAIL_REGEX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SESSION_ID_REGEX = re.compile(r"^[0-9a-f]{64}$")


def strip_newlines(value):
    if not isinstance(value, str):
        return ""
    return value.replace("\r", "").replace("\n", "")


def cleanup_abandoned_sessions():
    """Opportunistically sweep and delete session files older than 1 hour."""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        items = supabase.storage.from_("uploads").list("sessions", {"limit": 50})
        to_delete = []

        for item in items:
            name = item.get("name") if isinstance(item, dict) else getattr(item, "name", None)
            if not name or name == ".emptyFolderPlaceholder":
                continue

            session_files = supabase.storage.from_("uploads").list(f"sessions/{name}", {"limit": 50})
            for sf in session_files:
                sf_name = sf.get("name") if isinstance(sf, dict) else getattr(sf, "name", None)
                if not sf_name or sf_name == ".emptyFolderPlaceholder":
                    continue

                created_at_str = sf.get("created_at") if isinstance(sf, dict) else getattr(sf, "created_at", None)
                updated_at_str = sf.get("updated_at") if isinstance(sf, dict) else getattr(sf, "updated_at", None)
                ts_str = created_at_str or updated_at_str
                if ts_str:
                    try:
                        file_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if file_dt < cutoff:
                            to_delete.append(f"sessions/{name}/{sf_name}")
                    except Exception:
                        pass

        if to_delete:
            supabase.storage.from_("uploads").remove(to_delete)
    except Exception:
        pass


# Vercel's Python runtime looks for a class named exactly "handler"
class handler(BaseHTTPRequestHandler):
    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send_json(200, {})

    def do_POST(self):
        ip = self.headers.get("x-forwarded-for", "").split(",")[0].strip() or self.client_address[0]

        # --- 1. Read and sanitize input with strict type safety ---
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send_json(400, {"error": "Invalid JSON"})

        if not isinstance(data, dict):
            return self._send_json(400, {"error": "JSON payload must be an object"})

        receiver_raw = data.get("receiver")
        if not isinstance(receiver_raw, str):
            return self._send_json(400, {"error": "Receiver must be a string"})

        subject_raw = data.get("subject", "")
        if subject_raw is not None and not isinstance(subject_raw, str):
            return self._send_json(400, {"error": "Subject must be a string"})

        body_raw = data.get("body", "")
        if body_raw is not None and not isinstance(body_raw, str):
            return self._send_json(400, {"error": "Body must be a string"})

        session_id = data.get("sessionId")
        if session_id is not None:
            if not isinstance(session_id, str) or not SESSION_ID_REGEX.match(session_id):
                return self._send_json(400, {"error": "Invalid session ID"})

        receiver = strip_newlines(receiver_raw).strip()
        if not EMAIL_REGEX.match(receiver):
            return self._send_json(400, {"error": "Invalid receiver email address"})

        subject = strip_newlines(subject_raw).strip() or "(no subject)"
        body_text = body_raw or ""

        # --- 2. Atomic rate limiting, daily cap check, and logging (STRICTLY before touching Storage) ---
        try:
            rpc_res = supabase.rpc(
                "check_and_log_send",
                {
                    "p_ip": ip,
                    "p_receiver": receiver,
                    "p_file_name": session_id,
                },
            ).execute()
            if not rpc_res.data:
                return self._send_json(429, {"error": "Rate limit or daily limit reached, try later"})
        except Exception:
            return self._send_json(500, {"error": "Failed to verify rate limits"})

        # --- 3. Opportunistic cleanup of abandoned sessions ---
        cleanup_abandoned_sessions()

        # --- 4. Fetch files from Supabase Storage under sessions/<sessionId>/ ---
        attachments = []  # list of (file_name, file_bytes) tuples
        file_paths = []
        if session_id:
            try:
                listed_files = supabase.storage.from_("uploads").list(
                    f"sessions/{session_id}",
                    {"limit": 50},
                )
                for item in listed_files:
                    fn = item.get("name") if isinstance(item, dict) else getattr(item, "name", None)
                    if not fn or fn == ".emptyFolderPlaceholder":
                        continue
                    fp = f"sessions/{session_id}/{fn}"
                    file_paths.append(fp)
                    fb = supabase.storage.from_("uploads").download(fp)
                    attachments.append((fn, fb))
            except Exception:
                return self._send_json(400, {"error": "Could not fetch uploaded session files"})

        # --- 5. Build and send the email ---
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = formataddr(("Cero Mailer", GMAIL_USER))
        msg["To"] = receiver
        msg.set_content(body_text)

        for file_name, file_bytes in attachments:
            mime_type, _ = mimetypes.guess_type(file_name)
            if mime_type is None:
                mime_type = "application/octet-stream"
            main_type, sub_type = mime_type.split("/")
            msg.add_attachment(file_bytes, maintype=main_type, subtype=sub_type, filename=file_name)

        try:
            ssl_context = ssl.create_default_context()
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls(context=ssl_context)
                server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                server.send_message(msg)
        except Exception:
            return self._send_json(500, {"error": "Failed to send email"})

        # --- 6. Clean up uploaded temporary session files ---
        if file_paths:
            try:
                supabase.storage.from_("uploads").remove(file_paths)
            except Exception:
                pass

        return self._send_json(200, {"success": True})
