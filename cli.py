import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.request
import webbrowser

# Same values as index.html — safe to keep here, this is the public/anon key,
# not a secret. The actual Gmail credentials never leave Vercel.
SUPABASE_URL = "https://euduprorskqxcvecapfo.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_gxIe1B6z1ZGKecBOksly4w_H9nw1xFq"
VERCEL_BASE_URL = "https://cero-mailer.vercel.app"
CREATE_SESSION_URL = f"{VERCEL_BASE_URL}/api/create-session"
SEND_API_URL = f"{VERCEL_BASE_URL}/api/send"

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


def sanitize_filename(filename):
    return re.sub(r"[^a-zA-Z0-9._-]", "_", filename)


def parse_error_response(error_body, fallback_status=""):
    try:
        data = json.loads(error_body)
        if isinstance(data, dict) and "error" in data:
            return data["error"]
        return error_body
    except Exception:
        return error_body or fallback_status


def create_session():
    req = urllib.request.Request(
        CREATE_SESSION_URL,
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data["sessionId"]
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        err_msg = parse_error_response(err_body, f"HTTP {e.code}")
        raise RuntimeError(f"{e.code}: {err_msg}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}")


def upload_file(session_id, file_path):
    file_name = sanitize_filename(os.path.basename(file_path))
    remote_path = f"sessions/{session_id}/{file_name}"

    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type is None:
        mime_type = "application/octet-stream"

    with open(file_path, "rb") as f:
        file_data = f.read()

    upload_url = f"{SUPABASE_URL}/storage/v1/object/uploads/{remote_path}"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": mime_type,
    }

    req = urllib.request.Request(upload_url, data=file_data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            if response.status not in (200, 201):
                err_body = response.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"{response.status}: {err_body}")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        err_msg = parse_error_response(err_body, f"HTTP {e.code}")
        raise RuntimeError(f"{e.code}: {err_msg}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}")

    return remote_path


def send_email(session_id, receiver, subject, body):
    payload = {
        "sessionId": session_id,
        "receiver": receiver,
        "subject": subject,
        "body": body,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        SEND_API_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode("utf-8"))
            return True, result
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        err_msg = parse_error_response(err_body, f"HTTP {e.code}")
        return False, err_msg
    except urllib.error.URLError as e:
        return False, f"Network error: {e.reason}"


def open_file_picker():
    """Open native OS file-picker or fallback to manual path input if tkinter is unavailable."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()

        selected = filedialog.askopenfilenames(
            title="Select files to attach",
            parent=root,
        )
        root.destroy()
        return list(selected)
    except Exception:
        print("\nGraphical file picker is unavailable.")
        raw_paths = input("Enter file path(s) to attach (comma-separated, or leave blank): ").strip()
        if not raw_paths:
            return []
        paths = [p.strip().strip('"').strip("'") for p in raw_paths.split(",") if p.strip()]
        return paths


def main():
    print("=== Cero Mailer ===")
    print("[1] Command-line mode")
    print("[2] Open the webpage version\n")
    mode = input(">> ").strip()

    if mode == "2":
        print("Opening https://cero-mailer.vercel.app in your browser...")
        webbrowser.open("https://cero-mailer.vercel.app")
        return

    receiver = input("\nReceiver Gmail address: ").strip()
    subject = input("Subject: ").strip()
    body = input("Body: ").strip()

    print("\n  [1] Choose Files")
    print("  [Enter] Skip — send without attachments\n")
    choice = input(">> ").strip()

    if choice == "1":
        file_paths = open_file_picker()
    else:
        file_paths = []

    # Validate each selected file
    for fp in file_paths:
        if not os.path.isfile(fp):
            print(f"File not found: {fp}")
            sys.exit(1)
        if os.path.getsize(fp) > MAX_FILE_SIZE:
            print(f"File too large (max 50MB): {fp}")
            sys.exit(1)

    # 1. Request server-issued session ID
    try:
        session_id = create_session()
    except Exception as e:
        print(f"Failed to create upload session: {e}")
        sys.exit(1)

    # 2. Upload each file under sessions/<sessionId>/...
    if file_paths:
        print(f"Uploading {len(file_paths)} file(s)...")
        for fp in file_paths:
            try:
                upload_file(session_id, fp)
            except Exception as e:
                print(f"Upload failed for {os.path.basename(fp)}: {e}")
                sys.exit(1)
    else:
        print("No files selected — sending without attachments.")

    # 3. Send email with sessionId
    print("Sending email...")
    ok, result = send_email(session_id, receiver, subject, body)

    if ok:
        print("Email sent!")
    else:
        print(f"Error: {result}")


if __name__ == "__main__":
    main()
