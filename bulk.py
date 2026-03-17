from __future__ import annotations

import random
import smtplib
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.mime.text import MIMEText
from email.utils import formataddr

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)


HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Dark SMTP Sender</title>
  <style>
    :root {
      --bg: #050505;
      --panel: #111111;
      --panel-2: #171717;
      --text: #f3f3f3;
      --muted: #9e9e9e;
      --accent: #36d399;
      --border: #292929;
      --error: #ff6b6b;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, Segoe UI, Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      padding: 24px;
    }

    .container {
      max-width: 1100px;
      margin: 0 auto;
      display: grid;
      gap: 16px;
    }

    h1 {
      margin: 0;
      text-align: center;
      letter-spacing: .6px;
      color: var(--accent);
    }

    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }

    .full { grid-column: 1 / -1; }

    label {
      display: block;
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 14px;
    }

    input, textarea {
      width: 100%;
      background: var(--panel-2);
      border: 1px solid var(--border);
      border-radius: 8px;
      color: var(--text);
      padding: 10px;
      font-size: 14px;
    }

    textarea { min-height: 120px; resize: vertical; }

    button {
      border: none;
      background: var(--accent);
      color: #000;
      border-radius: 8px;
      padding: 12px 18px;
      font-weight: 700;
      cursor: pointer;
    }

    .muted { color: var(--muted); font-size: 13px; }
    .result { white-space: pre-wrap; margin-top: 8px; }
    .ok { color: var(--accent); }
    .err { color: var(--error); }

    @media (max-width: 820px) {
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main class="container">
    <h1>SMTP Bulk Sender</h1>

    <form id="mailForm" class="card grid">
      <div>
        <label>SMTP IP / Host</label>
        <input name="smtp_host" required placeholder="127.0.0.1 or smtp.example.com" />
      </div>
      <div>
        <label>SMTP Port</label>
        <input name="smtp_port" type="number" min="1" max="65535" value="587" required />
      </div>
      <div>
        <label>SMTP Username</label>
        <input name="smtp_user" required />
      </div>
      <div>
        <label>SMTP Password</label>
        <input name="smtp_pass" type="password" required />
      </div>
      <div class="full">
        <label>Sender Emails (one per line)</label>
        <textarea name="sender_emails" required></textarea>
      </div>
      <div class="full">
        <label>Sender Names (one per line)</label>
        <textarea name="sender_names" required></textarea>
      </div>
      <div class="full">
        <label>Email Subjects (one per line)</label>
        <textarea name="subjects" required></textarea>
      </div>
      <div class="full">
        <label>Recipient Emails (one per line)</label>
        <textarea name="recipients" required></textarea>
      </div>
      <div class="full">
        <label>Email Body</label>
        <textarea name="body" required></textarea>
      </div>
      <div>
        <label>Worker Threads</label>
        <input name="workers" type="number" min="1" value="5" required />
      </div>
      <div class="full">
        <button id="sendBtn" type="submit">Send</button>
        <p class="muted">Each worker opens its own SMTP connection and starts at approximately the same time.</p>
        <div id="result" class="result muted">Idle.</div>
      </div>
    </form>
  </main>

  <script>
    const form = document.getElementById('mailForm');
    const sendBtn = document.getElementById('sendBtn');
    const result = document.getElementById('result');

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      sendBtn.disabled = true;
      result.textContent = 'Sending...';
      result.className = 'result muted';

      const payload = Object.fromEntries(new FormData(form).entries());
      payload.smtp_port = Number(payload.smtp_port);
      payload.workers = Number(payload.workers);

      try {
        const response = await fetch('/send', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)
        });

        const data = await response.json();
        if (!response.ok || !data.ok) {
          result.className = 'result err';
          result.textContent = data.error || 'Unknown error';
        } else {
          result.className = 'result ok';
          result.textContent = `Completed. Sent: ${data.sent} | Failed: ${data.failed}`;
        }
      } catch (error) {
        result.className = 'result err';
        result.textContent = `Request failed: ${error.message}`;
      } finally {
        sendBtn.disabled = false;
      }
    });
  </script>
</body>
</html>
"""


def split_lines(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def smtp_connect(host: str, port: int, username: str, password: str):
    context = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(host=host, port=port, timeout=30, context=context)
    else:
        server = smtplib.SMTP(host=host, port=port, timeout=30)
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
    server.login(username, password)
    return server


def send_batch(
    worker_id: int,
    host: str,
    port: int,
    username: str,
    password: str,
    recipients: list[str],
    sender_emails: list[str],
    sender_names: list[str],
    subjects: list[str],
    body: str,
    barrier: threading.Barrier,
):
    sent = 0
    failed = 0
    errors = []

    try:
        barrier.wait(timeout=10)
    except threading.BrokenBarrierError:
        return 0, len(recipients), [f"Worker {worker_id}: startup synchronization failed."]

    try:
        with smtp_connect(host, port, username, password) as smtp:
            for recipient in recipients:
                sender_email = random.choice(sender_emails)
                sender_name = random.choice(sender_names)
                subject = random.choice(subjects)

                msg = MIMEText(body, "plain", "utf-8")
                msg["Subject"] = subject
                msg["From"] = formataddr((sender_name, sender_email))
                msg["To"] = recipient

                try:
                    smtp.sendmail(sender_email, [recipient], msg.as_string())
                    sent += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    errors.append(f"Worker {worker_id} recipient {recipient}: {exc}")
    except Exception as exc:  # noqa: BLE001
        failed += len(recipients)
        errors.append(f"Worker {worker_id} connection/auth error: {exc}")

    return sent, failed, errors


@app.get("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.post("/send")
def send_mail():
    try:
        payload = request.get_json(force=True)

        host = str(payload.get("smtp_host", "")).strip()
        port = int(payload.get("smtp_port", 587))
        username = str(payload.get("smtp_user", "")).strip()
        password = str(payload.get("smtp_pass", ""))

        sender_emails = split_lines(str(payload.get("sender_emails", "")))
        sender_names = split_lines(str(payload.get("sender_names", "")))
        subjects = split_lines(str(payload.get("subjects", "")))
        recipients = split_lines(str(payload.get("recipients", "")))
        body = str(payload.get("body", "")).strip()
        workers = max(1, int(payload.get("workers", 1)))

        if not (host and username and password and body):
            return jsonify({"ok": False, "error": "SMTP host/user/password and body are required."}), 400
        if not sender_emails:
            return jsonify({"ok": False, "error": "At least one sender email is required."}), 400
        if not sender_names:
            return jsonify({"ok": False, "error": "At least one sender name is required."}), 400
        if not subjects:
            return jsonify({"ok": False, "error": "At least one subject is required."}), 400
        if not recipients:
            return jsonify({"ok": False, "error": "At least one recipient is required."}), 400

        workers = min(workers, len(recipients))
        chunks = [[] for _ in range(workers)]
        for index, recipient in enumerate(recipients):
            chunks[index % workers].append(recipient)

        barrier = threading.Barrier(workers)
        total_sent = 0
        total_failed = 0
        all_errors = []

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    send_batch,
                    worker_id,
                    host,
                    port,
                    username,
                    password,
                    chunk,
                    sender_emails,
                    sender_names,
                    subjects,
                    body,
                    barrier,
                )
                for worker_id, chunk in enumerate(chunks, start=1)
            ]

            for future in as_completed(futures):
                sent, failed, errors = future.result()
                total_sent += sent
                total_failed += failed
                all_errors.extend(errors)

        return jsonify(
            {
                "ok": True,
                "sent": total_sent,
                "failed": total_failed,
                "errors": all_errors[:20],
            }
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"Unexpected error: {exc}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
