from flask import Flask, render_template_string, request, jsonify
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
import random
import time
from concurrent.futures import ThreadPoolExecutor
import queue

app = Flask(__name__)

# Global variables for configuration and status
config = {
    'smtp_host': '',
    'smtp_port': 587,
    'smtp_user': '',
    'smtp_pass': '',
    'smtp_mode': 'auto',
    'senders': [],
    'sender_names': [],
    'subjects': [],
    'recipients': [],
    'body': '',
    'workers': 10,
    'debug': False,
}

status = {
    'running': False,
    'total_sent': 0,
    'total_emails': 0,
    'errors': 0,
    'progress': 0,
    'log': []
}

email_queue = queue.Queue()
lock = threading.Lock()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SMTP Mass Mailer</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            background: radial-gradient(circle at top, #15152a, #0a0a0a 60%);
            color: #e0e0e0;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        h1 {
            color: #00ff88;
            text-align: center;
            margin-bottom: 30px;
            font-size: 2.5em;
            text-shadow: 0 0 10px #00ff88;
        }
        .form-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 30px;
        }
        .form-group {
            background: #1a1a1a;
            padding: 20px;
            border-radius: 10px;
            border: 1px solid #333;
        }
        .form-group.full-width {
            grid-column: 1 / -1;
        }
        label {
            display: block;
            margin-bottom: 8px;
            color: #00ff88;
            font-weight: 600;
        }
        input, textarea, select {
            width: 100%;
            padding: 12px;
            background: #2a2a2a;
            border: 1px solid #444;
            border-radius: 6px;
            color: #e0e0e0;
            font-size: 14px;
            resize: vertical;
        }
        textarea {
            height: 120px;
            font-family: 'Courier New', monospace;
        }
        input:focus, textarea:focus, select:focus {
            outline: none;
            border-color: #00ff88;
            box-shadow: 0 0 8px rgba(0, 255, 136, 0.3);
        }
        .btn {
            background: linear-gradient(45deg, #00ff88, #00cc6a);
            color: #000;
            border: none;
            padding: 15px 40px;
            font-size: 18px;
            font-weight: 600;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 25px rgba(0, 255, 136, 0.4);
        }
        .btn:disabled {
            background: #555;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
        }
        .status-panel {
            background: #1a1a1a;
            padding: 25px;
            border-radius: 10px;
            border: 1px solid #333;
            margin-top: 20px;
        }
        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
        }
        .status-item {
            text-align: center;
            padding: 15px;
            background: #2a2a2a;
            border-radius: 8px;
            border-left: 4px solid #00ff88;
        }
        .status-number {
            font-size: 2em;
            font-weight: 700;
            color: #00ff88;
            display: block;
        }
        .status-label {
            color: #888;
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .progress-bar {
            width: 100%;
            height: 8px;
            background: #333;
            border-radius: 4px;
            overflow: hidden;
            margin-top: 15px;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #00ff88, #00cc6a);
            width: 0%;
            transition: width 0.3s ease;
        }
        .log-wrap {
            margin-top: 20px;
            background: #090909;
            border: 1px solid #2e2e2e;
            border-radius: 8px;
            overflow: hidden;
        }
        .log-header {
            padding: 10px 14px;
            font-size: 12px;
            color: #adadad;
            border-bottom: 1px solid #2e2e2e;
            background: #121212;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .log {
            height: 230px;
            overflow-y: auto;
            padding: 15px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
            color: #00ff88;
            white-space: pre-wrap;
            word-break: break-word;
        }
        .helper {
            color: #8e8e8e;
            margin-top: 6px;
            font-size: 12px;
        }
        .inline-controls {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        .checkline {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-top: 8px;
            color: #d6d6d6;
        }
        .checkline input {
            width: auto;
        }
        @media (max-width: 768px) {
            .form-grid, .inline-controls {
                grid-template-columns: 1fr;
            }
            h1 {
                font-size: 2em;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 SMTP Mass Mailer</h1>

        <form id="mailerForm">
            <div class="form-grid">
                <div class="form-group">
                    <label>SMTP Host</label>
                    <input type="text" id="smtp_host" placeholder="smtp.example.com">
                </div>
                <div class="form-group">
                    <label>SMTP Port</label>
                    <input type="number" id="smtp_port" value="587" min="1" max="65535">
                </div>
                <div class="form-group">
                    <label>Username</label>
                    <input type="text" id="smtp_user" placeholder="username">
                </div>
                <div class="form-group">
                    <label>Password</label>
                    <input type="password" id="smtp_pass" placeholder="password">
                </div>

                <div class="form-group full-width">
                    <div class="inline-controls">
                        <div>
                            <label>SMTP Connection Mode</label>
                            <select id="smtp_mode">
                                <option value="auto" selected>Auto (recommended)</option>
                                <option value="starttls">TLS / STARTTLS</option>
                                <option value="ssl">SSL / SMTPS</option>
                                <option value="plain">Plain (no encryption)</option>
                            </select>
                            <div class="helper">Auto tries SSL for common SSL ports, then STARTTLS, then plain.</div>
                        </div>
                        <div>
                            <label>Debugging</label>
                            <label class="checkline"><input type="checkbox" id="debug"> Enable detailed SMTP debug logs</label>
                            <div class="helper">Adds extra connection/auth logs to dashboard log view.</div>
                        </div>
                    </div>
                </div>

                <div class="form-group full-width">
                    <label>Sender Emails (one per line)</label>
                    <textarea id="senders" placeholder="sender1@example.com&#10;sender2@example.com"></textarea>
                </div>

                <div class="form-group">
                    <label>Sender Names (one per line)</label>
                    <textarea id="sender_names" placeholder="John Doe&#10;Jane Smith"></textarea>
                </div>
                <div class="form-group">
                    <label>Email Subjects (one per line)</label>
                    <textarea id="subjects" placeholder="Important Update&#10;Action Required"></textarea>
                </div>

                <div class="form-group full-width">
                    <label>Recipient Emails (one per line)</label>
                    <textarea id="recipients" placeholder="recipient1@example.com&#10;recipient2@example.com"></textarea>
                </div>

                <div class="form-group full-width">
                    <label>Email Body</label>
                    <textarea id="body" placeholder="Enter your email body here...">Hello,

This is a test email sent via SMTP Mass Mailer.

Best regards,
Your Team</textarea>
                </div>

                <div class="form-group">
                    <label>Worker Threads</label>
                    <input type="number" id="workers" value="10" min="1" max="100">
                </div>
            </div>

            <div style="text-align: center; margin-bottom: 30px;">
                <button type="submit" class="btn" id="sendBtn">🚀 Send Emails</button>
            </div>
        </form>

        <div class="status-panel" id="statusPanel" style="display: none;">
            <div class="status-grid">
                <div class="status-item">
                    <span class="status-number" id="totalSent">0</span>
                    <span class="status-label">Sent</span>
                </div>
                <div class="status-item">
                    <span class="status-number" id="totalEmails">0</span>
                    <span class="status-label">Total</span>
                </div>
                <div class="status-item">
                    <span class="status-number" id="errors">0</span>
                    <span class="status-label">Errors</span>
                </div>
                <div class="status-item">
                    <span class="status-number" id="progressPct">0%</span>
                    <span class="status-label">Progress</span>
                </div>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" id="progressFill"></div>
            </div>
            <div class="log-wrap">
                <div class="log-header">
                    <span>Dashboard Command & Debug Log</span>
                    <button type="button" onclick="document.getElementById('log').textContent=''" class="btn" style="padding:6px 12px;font-size:12px;">Clear</button>
                </div>
                <div class="log" id="log"></div>
            </div>
        </div>
    </div>

    <script>
        let isRunning = false;

        document.getElementById('mailerForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            if (isRunning) return;

            const formData = {
                smtp_host: document.getElementById('smtp_host').value,
                smtp_port: parseInt(document.getElementById('smtp_port').value),
                smtp_user: document.getElementById('smtp_user').value,
                smtp_pass: document.getElementById('smtp_pass').value,
                smtp_mode: document.getElementById('smtp_mode').value,
                debug: document.getElementById('debug').checked,
                senders: document.getElementById('senders').value.split('\n').map(s => s.trim()).filter(Boolean),
                sender_names: document.getElementById('sender_names').value.split('\n').map(s => s.trim()).filter(Boolean),
                subjects: document.getElementById('subjects').value.split('\n').map(s => s.trim()).filter(Boolean),
                recipients: document.getElementById('recipients').value.split('\n').map(s => s.trim()).filter(Boolean),
                body: document.getElementById('body').value,
                workers: parseInt(document.getElementById('workers').value)
            };

            const sendBtn = document.getElementById('sendBtn');
            sendBtn.disabled = true;
            sendBtn.textContent = 'Sending...';
            isRunning = true;

            document.getElementById('statusPanel').style.display = 'block';

            try {
                await fetch('/send', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(formData)
                });
            } finally {
                sendBtn.disabled = false;
                sendBtn.textContent = '🚀 Send Emails';
            }
        });

        // Status polling
        setInterval(async () => {
            const response = await fetch('/status');
            const data = await response.json();

            document.getElementById('totalSent').textContent = data.total_sent;
            document.getElementById('totalEmails').textContent = data.total_emails;
            document.getElementById('errors').textContent = data.errors;
            document.getElementById('progressPct').textContent = Math.floor(data.progress) + '%';
            document.getElementById('progressFill').style.width = data.progress + '%';

            document.getElementById('log').textContent = (data.log || []).slice(-250).join('\n');
            document.getElementById('log').scrollTop = document.getElementById('log').scrollHeight;

            isRunning = !!data.running;
        }, 1000);
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


def log_message(message, force=False):
    """Thread-safe logging."""
    global status
    if not force and not config.get('debug', False) and '[DEBUG]' in message:
        return
    with lock:
        status['log'].append(f"[{time.strftime('%H:%M:%S')}] {message}")
        if len(status['log']) > 2000:
            status['log'] = status['log'][-1000:]


def connect_smtp(worker_id):
    """Build an SMTP connection using configured mode (auto/tls/ssl/plain)."""
    host = config['smtp_host']
    port = int(config['smtp_port'])
    user = config['smtp_user']
    password = config['smtp_pass']
    mode = (config.get('smtp_mode') or 'auto').lower()

    def login_if_needed(server):
        if user:
            server.login(user, password)
            log_message(f"Worker {worker_id}: [DEBUG] SMTP login successful")

    if mode == 'ssl':
        log_message(f"Worker {worker_id}: [DEBUG] Connecting via SSL")
        server = smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context())
        server.ehlo()
        login_if_needed(server)
        return server

    if mode == 'starttls':
        log_message(f"Worker {worker_id}: [DEBUG] Connecting via STARTTLS")
        server = smtplib.SMTP(host, port, timeout=20)
        server.ehlo()
        server.starttls(context=ssl.create_default_context())
        server.ehlo()
        login_if_needed(server)
        return server

    if mode == 'plain':
        log_message(f"Worker {worker_id}: [DEBUG] Connecting in plain mode")
        server = smtplib.SMTP(host, port, timeout=20)
        server.ehlo()
        login_if_needed(server)
        return server

    # Auto mode fallback sequence
    attempts = []
    if port in (465,):
        attempts = ['ssl', 'starttls', 'plain']
    elif port in (587,):
        attempts = ['starttls', 'ssl', 'plain']
    else:
        attempts = ['starttls', 'ssl', 'plain']

    last_error = None
    for method in attempts:
        try:
            log_message(f"Worker {worker_id}: [DEBUG] Auto mode trying {method}")
            if method == 'ssl':
                server = smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context())
                server.ehlo()
                login_if_needed(server)
            elif method == 'starttls':
                server = smtplib.SMTP(host, port, timeout=20)
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                login_if_needed(server)
            else:
                server = smtplib.SMTP(host, port, timeout=20)
                server.ehlo()
                login_if_needed(server)
            log_message(f"Worker {worker_id}: Connected using {method.upper()}", force=True)
            return server
        except Exception as exc:
            last_error = exc
            log_message(f"Worker {worker_id}: [DEBUG] {method} failed: {exc}")
            try:
                server.quit()
            except Exception:
                pass

    raise RuntimeError(f"Auto SMTP connection failed after trying {attempts}: {last_error}")


@app.route('/send', methods=['POST'])
def send_emails():
    global config, status, email_queue
    data = request.json or {}

    # Update config
    config.update(data)

    recipients = config.get('recipients') or []
    loops = 100 if recipients else 0

    # Reset status
    status = {
        'running': True,
        'total_sent': 0,
        'total_emails': len(recipients) * loops,
        'errors': 0,
        'progress': 0,
        'log': []
    }

    # Populate email queue
    email_queue = queue.Queue()
    for _ in range(loops):
        for recipient in recipients:
            email_queue.put(recipient)

    log_message("Job started", force=True)
    log_message(f"Config: workers={config.get('workers')} mode={config.get('smtp_mode', 'auto')} debug={config.get('debug', False)}", force=True)

    # Start workers in background thread
    def run_workers():
        global status
        futures = []
        with ThreadPoolExecutor(max_workers=int(config.get('workers', 10))) as executor:
            for i in range(int(config.get('workers', 10))):
                futures.append(executor.submit(worker_function, i + 1))
            for future in futures:
                future.result()

        with lock:
            status['running'] = False
            status['progress'] = 100 if status['total_emails'] else 0
        log_message("Job completed", force=True)

    threading.Thread(target=run_workers, daemon=True).start()

    return jsonify({'status': 'started'})


def worker_function(worker_id):
    """Worker thread function."""
    global status, email_queue

    if not config.get('senders') or not config.get('sender_names') or not config.get('subjects'):
        log_message(f"Worker {worker_id}: Missing sender_names/subjects/senders configuration", force=True)
        with lock:
            status['errors'] += 1
        return

    try:
        server = connect_smtp(worker_id)
        log_message(f"Worker {worker_id}: Connected to SMTP server", force=True)

        sent_count = 0
        while status['running']:
            try:
                recipient = email_queue.get_nowait()
            except queue.Empty:
                break

            try:
                sender_email = random.choice(config['senders'])
                sender_name = random.choice(config['sender_names'])
                subject = random.choice(config['subjects'])

                msg = MIMEMultipart()
                msg['From'] = f"{sender_name} <{sender_email}>"
                msg['To'] = recipient
                msg['Subject'] = subject
                msg.attach(MIMEText(config['body'], 'plain'))

                server.send_message(msg)

                with lock:
                    status['total_sent'] += 1
                    sent_count += 1
                    if status['total_emails']:
                        status['progress'] = min(100, (status['total_sent'] / status['total_emails']) * 100)

                log_message(f"Worker {worker_id}: Sent to {recipient}")
            except Exception as exc:
                with lock:
                    status['errors'] += 1
                log_message(f"Worker {worker_id}: Error sending to {recipient}: {exc}", force=True)
            finally:
                email_queue.task_done()

        server.quit()
        log_message(f"Worker {worker_id}: Completed ({sent_count} emails sent)", force=True)

    except Exception as exc:
        with lock:
            status['errors'] += 1
        log_message(f"Worker {worker_id}: Failed to connect: {exc}", force=True)


@app.route('/status')
def get_status():
    global status
    return jsonify(status)


if __name__ == '__main__':
    print("🚀 SMTP Mass Mailer starting on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
