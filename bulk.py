from __future__ import annotations

import logging
import random
import smtplib
import ssl
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.mime.text import MIMEText
from email.utils import formataddr

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(threadName)s %(message)s",
)

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
MAX_EVENTS_PER_JOB = 300


def mark_job_done(job_id: str, sent: int = 0, failed: int = 0, errors: list[str] | None = None):
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id]["done"] = True
            JOBS[job_id]["sent"] = sent
            JOBS[job_id]["failed"] = failed
            JOBS[job_id]["errors"] = list(errors or [])


HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Modern SMTP Sender</title>
  <style>
    :root {
      --bg: #0b1220;
      --panel: #121a2b;
      --panel-2: #18233a;
      --line: #273552;
      --text: #e8eefc;
      --muted: #9fb0d3;
      --primary: #58a6ff;
      --success: #27c281;
      --danger: #ff6b6b;
      --shadow: 0 10px 30px rgba(0,0,0,.25);
    }
    * { box-sizing: border-box; }
    body { margin: 0; padding: 20px; background: var(--bg); color: var(--text); font-family: Tahoma, Arial, sans-serif; }
    .container { max-width: 1300px; margin: 0 auto; display: grid; gap: 16px; }
    .title-wrap h1 { margin: 0 0 8px; font-size: 30px; }
    .title-wrap p { margin: 0; color: var(--muted); }
    .card { background: linear-gradient(180deg, rgba(255,255,255,.02), rgba(255,255,255,.01)); border: 1px solid var(--line); border-radius: 16px; padding: 16px; box-shadow: var(--shadow); }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .full { grid-column: 1 / -1; }
    .inline-row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    label { display: block; margin-bottom: 6px; color: var(--muted); font-size: 13px; }
    input, textarea, select { width: 100%; background: #0f1728; color: var(--text); border: 1px solid var(--line); border-radius: 12px; padding: 12px 13px; font-size: 14px; outline: none; }
    input:focus, textarea:focus, select:focus { border-color: var(--primary); }
    textarea { min-height: 110px; resize: vertical; line-height: 1.4; }
    .body-area { min-height: 240px; }
    button { border: 1px solid transparent; background: var(--primary); color: #08111f; padding: 10px 14px; border-radius: 12px; cursor: pointer; font-size: 14px; transition: .2s ease; font-weight: bold; box-shadow: var(--shadow); }
    button:hover { transform: translateY(-1px); }
    button:disabled { opacity: 0.6; cursor: wait; }
    .muted { color: var(--muted); font-size: 13px; }
    .result { white-space: pre-wrap; margin-top: 8px; }
    .ok { color: var(--success); }
    .err { color: var(--danger); }
    .monitor-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 12px 0 8px; }
    .monitor-stat { padding: 10px 12px; border-radius: 12px; background: var(--panel); border: 1px solid var(--line); }
    .monitor-stat .label { color: var(--muted); font-size: 12px; margin-bottom: 6px; }
    .monitor-stat .value { font-size: 24px; font-weight: bold; }
    .progress-wrap { margin: 12px 0 2px; }
    .progress-bar { height: 12px; background: #0f1728; border-radius: 999px; border: 1px solid var(--line); overflow: hidden; }
    .progress-fill { height: 100%; width: 0%; background: linear-gradient(90deg, var(--primary), var(--success)); transition: width .3s ease; }
    .progress-text { margin-top: 6px; color: var(--muted); font-size: 12px; }
    .monitor-console { margin-top: 12px; border: 1px solid #333; background: #000; color: #fff; border-radius: 12px; min-height: 210px; max-height: 320px; overflow: auto; padding: 12px; font-family: Consolas, monospace; font-size: 12px; line-height: 1.5; white-space: pre-wrap; }
    .monitor-line { margin-bottom: 3px; }
    .monitor-error { color: #ff7f7f; }
    .monitor-ok { color: #7ff0bb; }
    @media (max-width: 980px) { .grid, .inline-row, .monitor-grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <main class="container">
    <div class="title-wrap card">
      <h1>SMTP Bulk Sender</h1>
      <p>واجهة حديثة مع مراقبة مباشرة، حفظ تلقائي للبيانات، واستبدال [URL] بشكل عشوائي.</p>
    </div>

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
      <div>
        <label>SMTP Security</label>
        <select name="smtp_mode">
          <option value="auto" selected>Auto (default)</option>
          <option value="starttls">STARTTLS</option>
          <option value="ssl">SSL/TLS (Implicit)</option>
          <option value="plain">Plain / No TLS</option>
        </select>
      </div>
      <div class="full inline-row">
        <div>
          <label>Sender Name (one per line)</label>
          <textarea name="sender_names" required></textarea>
        </div>
        <div>
          <label>Email Sender (one per line)</label>
          <textarea name="sender_emails" required></textarea>
        </div>
      </div>
      <div class="full">
        <label>Email Subjects (one per line)</label>
        <textarea name="subjects" required></textarea>
      </div>
      <div class="full">
        <label>Email Body</label>
        <textarea class="body-area" name="body" required placeholder="Use [URL] to insert random links"></textarea>
      </div>
      <div class="full">
        <label>Recipient Emails (one per line)</label>
        <textarea name="recipients" required></textarea>
      </div>
      <div class="full inline-row">
        <div>
          <label>URL (one per line)</label>
          <textarea name="urls" placeholder="https://link1.com&#10;https://link2.com"></textarea>
        </div>
        <div>
          <label>SRC</label>
          <textarea name="src" placeholder="Reserved for future use"></textarea>
        </div>
      </div>
      <div>
        <label>Worker Threads</label>
        <input name="workers" type="number" min="1" value="5" required />
      </div>
      <div class="full">
        <button id="sendBtn" type="submit">Send</button>
        <p class="muted">Live monitoring is shown below for debugging and error diagnosis.</p>
        <div id="result" class="result muted">Idle.</div>
        <div class="monitor-grid">
          <div class="monitor-stat"><div class="label">Recipients</div><div id="statRecipients" class="value">0</div></div>
          <div class="monitor-stat"><div class="label">Sent</div><div id="statSent" class="value">0</div></div>
          <div class="monitor-stat"><div class="label">Failed</div><div id="statFailed" class="value">0</div></div>
          <div class="monitor-stat"><div class="label">Success Rate</div><div id="statRate" class="value">0%</div></div>
        </div>
        <div class="progress-wrap">
          <div class="progress-bar"><div id="progressFill" class="progress-fill"></div></div>
          <div id="progressText" class="progress-text">0 / 0 processed</div>
        </div>
        <div id="monitor" class="monitor-console" aria-live="polite">[monitor] Waiting for a job...</div>
      </div>
    </form>
  </main>

  <script>
    const form = document.getElementById('mailForm');
    const sendBtn = document.getElementById('sendBtn');
    const result = document.getElementById('result');
    const monitor = document.getElementById('monitor');
    const statRecipients = document.getElementById('statRecipients');
    const statSent = document.getElementById('statSent');
    const statFailed = document.getElementById('statFailed');
    const statRate = document.getElementById('statRate');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');

    let monitorTimer = null;
    let currentJobId = null;
    let lastSeq = 0;
    const STORAGE_KEY = 'smtpBulkSenderFormV2';

    console.log('[SMTP Dashboard] Loaded dashboard and initialized form handlers');

    function appendMonitorLine(text, cssClass = '') {
      const line = document.createElement('div');
      line.className = `monitor-line ${cssClass}`.trim();
      line.textContent = text;
      monitor.appendChild(line);
      monitor.scrollTop = monitor.scrollHeight;
    }

    function resetMonitor() {
      monitor.innerHTML = '';
      appendMonitorLine('[monitor] New request started...');
      updateStats(0, 0, 0);
    }

    function updateStats(totalRecipients, sent, failed) {
      const processed = sent + failed;
      const rate = processed ? Math.round((sent / processed) * 100) : 0;
      const progress = totalRecipients ? Math.min(100, Math.round((processed / totalRecipients) * 100)) : 0;
      statRecipients.textContent = String(totalRecipients || 0);
      statSent.textContent = String(sent || 0);
      statFailed.textContent = String(failed || 0);
      statRate.textContent = `${rate}%`;
      progressFill.style.width = `${progress}%`;
      progressText.textContent = `${processed} / ${totalRecipients || 0} processed`;
    }

    function saveFormToStorage() {
      const payload = Object.fromEntries(new FormData(form).entries());
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    }

    function loadFormFromStorage() {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      try {
        const data = JSON.parse(raw);
        for (const [key, value] of Object.entries(data)) {
          const field = form.elements.namedItem(key);
          if (field) {
            field.value = value;
          }
        }
      } catch (error) {
        console.warn('[SMTP Dashboard] Failed to parse local storage data', error);
      }
    }

    async function pollMonitoring() {
      if (!currentJobId) {
        return;
      }

      try {
        const response = await fetch(`/monitor/${currentJobId}?after=${lastSeq}`);
        const data = await response.json();

        if (!response.ok || !data.ok) {
          appendMonitorLine(`[monitor] Failed to fetch monitoring: ${data.error || 'unknown error'}`, 'monitor-error');
          return;
        }

        for (const event of data.events || []) {
          lastSeq = Math.max(lastSeq, event.seq || 0);
          const line = `[${event.at}] [${event.level}] ${event.message}`;
          const cssClass = event.level === 'ERROR' ? 'monitor-error' : (event.level === 'SUCCESS' ? 'monitor-ok' : '');
          appendMonitorLine(line, cssClass);
          if (event.level === 'ERROR') {
            console.error('[SMTP Dashboard][monitor]', event.message);
          } else {
            console.log('[SMTP Dashboard][monitor]', event.message);
          }
        }

        updateStats(data.total_recipients || 0, data.sent || 0, data.failed || 0);

        if (data.done) {
          appendMonitorLine('[monitor] Job finished.', 'monitor-ok');
          result.className = data.failed > 0 ? 'result err' : 'result ok';
          result.textContent = `Completed. Sent: ${data.sent} | Failed: ${data.failed}`;
          if ((data.errors || []).length > 0) {
            appendMonitorLine('[monitor] Final error summary:', 'monitor-error');
            for (const err of data.errors) {
              appendMonitorLine(` - ${err}`, 'monitor-error');
            }
          }
          stopMonitoring();
        }
      } catch (error) {
        appendMonitorLine(`[monitor] Polling exception: ${error.message}`, 'monitor-error');
        console.error('[SMTP Dashboard] Monitoring polling failed', error);
      }
    }

    function startMonitoring(jobId) {
      stopMonitoring();
      currentJobId = jobId;
      lastSeq = 0;
      appendMonitorLine(`[monitor] Tracking job ${jobId}`);
      monitorTimer = setInterval(pollMonitoring, 700);
      pollMonitoring();
    }

    function stopMonitoring() {
      if (monitorTimer) {
        clearInterval(monitorTimer);
        monitorTimer = null;
      }
    }

    form.addEventListener('input', saveFormToStorage);
    loadFormFromStorage();

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      sendBtn.disabled = true;
      result.textContent = 'Sending...';
      result.className = 'result muted';
      resetMonitor();

      const payload = Object.fromEntries(new FormData(form).entries());
      payload.smtp_port = Number(payload.smtp_port);
      payload.workers = Number(payload.workers);
      saveFormToStorage();
      console.debug('[SMTP Dashboard] Sending payload', {
        host: payload.smtp_host,
        port: payload.smtp_port,
        workers: payload.workers,
        smtp_mode: payload.smtp_mode
      });

      try {
        const response = await fetch('/send', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)
        });

        const data = await response.json();
        console.debug('[SMTP Dashboard] API response', data);

        if (data.job_id) {
          startMonitoring(data.job_id);
        }

        if (!response.ok || !data.ok) {
          result.className = 'result err';
          result.textContent = data.error || 'Unknown error';
          appendMonitorLine(`[monitor] Request failed immediately: ${result.textContent}`, 'monitor-error');
          stopMonitoring();
        } else {
          result.className = 'result muted';
          result.textContent = 'Job accepted. Monitoring in progress...';
          appendMonitorLine('[monitor] Job accepted by API. Waiting for worker updates...');
          pollMonitoring();
        }
      } catch (error) {
        console.error('[SMTP Dashboard] Request failed', error);
        result.className = 'result err';
        result.textContent = `Request failed: ${error.message}`;
        appendMonitorLine(`[monitor] Request failed: ${error.message}`, 'monitor-error');
        stopMonitoring();
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


def log_job_event(job_id: str, level: str, message: str):
    timestamp = time.strftime("%H:%M:%S")
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job["seq"] += 1
        event = {
            "seq": job["seq"],
            "at": timestamp,
            "level": level,
            "message": message,
        }
        job["events"].append(event)
        if len(job["events"]) > MAX_EVENTS_PER_JOB:
            job["events"] = job["events"][-MAX_EVENTS_PER_JOB:]

    if level == "ERROR":
        logging.error("[%s] %s", job_id, message)
    elif level == "SUCCESS":
        logging.info("[%s] %s", job_id, message)
    else:
        logging.debug("[%s] %s", job_id, message)


def smtp_connect(host: str, port: int, username: str, password: str, mode: str = "auto"):
    context = ssl.create_default_context()

    normalized_mode = mode.lower().strip() if mode else "auto"
    logging.info("Opening SMTP connection host=%s port=%s mode=%s", host, port, normalized_mode)

    def connect_ssl():
        return smtplib.SMTP_SSL(host=host, port=port, timeout=30, context=context)

    def connect_starttls():
        server = smtplib.SMTP(host=host, port=port, timeout=30)
        server.ehlo()
        if not server.has_extn("starttls"):
            server.close()
            raise smtplib.SMTPNotSupportedError("STARTTLS extension not supported by server.")
        server.starttls(context=context)
        server.ehlo()
        return server

    def connect_plain():
        server = smtplib.SMTP(host=host, port=port, timeout=30)
        server.ehlo()
        return server

    if normalized_mode in {"ssl", "starttls", "plain"}:
        connector = {
            "ssl": connect_ssl,
            "starttls": connect_starttls,
            "plain": connect_plain,
        }[normalized_mode]
        server = connector()
        server.login(username, password)
        logging.info("SMTP login successful for user=%s using mode=%s", username, normalized_mode)
        return server

    if normalized_mode != "auto":
        raise ValueError("Invalid smtp_mode. Use auto, starttls, ssl, or plain.")

    if port == 465:
        attempts = [("ssl", connect_ssl), ("starttls", connect_starttls), ("plain", connect_plain)]
    else:
        attempts = [("starttls", connect_starttls), ("plain", connect_plain), ("ssl", connect_ssl)]

    attempt_errors = []
    for attempt_mode, connector in attempts:
        server = None
        try:
            server = connector()
            server.login(username, password)
            logging.info("SMTP login successful for user=%s using mode=%s", username, attempt_mode)
            return server
        except Exception as exc:  # noqa: BLE001
            attempt_errors.append(f"{attempt_mode}: {exc}")
            logging.warning(
                "SMTP auto mode attempt failed host=%s port=%s mode=%s error=%s",
                host,
                port,
                attempt_mode,
                exc,
            )
            if server is not None:
                try:
                    server.close()
                except Exception:  # noqa: BLE001
                    pass

    raise ConnectionError(f"Unable to establish SMTP connection in auto mode. Attempts: {' | '.join(attempt_errors)}")


def send_batch(
    job_id: str,
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
    urls: list[str],
    smtp_mode: str,
    barrier: threading.Barrier,
):
    sent = 0
    failed = 0
    errors = []

    log_job_event(job_id, "INFO", f"Worker {worker_id} ready with {len(recipients)} recipients.")
    try:
        barrier.wait(timeout=10)
        log_job_event(job_id, "INFO", f"Worker {worker_id} passed startup barrier.")
    except threading.BrokenBarrierError:
        log_job_event(job_id, "ERROR", f"Worker {worker_id}: startup synchronization failed.")
        return 0, len(recipients), [f"Worker {worker_id}: startup synchronization failed."]

    try:
        log_job_event(job_id, "INFO", f"Worker {worker_id} opening SMTP connection to {host}:{port} mode={smtp_mode}.")
        with smtp_connect(host, port, username, password, smtp_mode) as smtp:
            log_job_event(job_id, "SUCCESS", f"Worker {worker_id} SMTP connection established and logged in.")
            for recipient in recipients:
                sender_email = random.choice(sender_emails)
                sender_name = random.choice(sender_names)
                subject = random.choice(subjects)

                selected_url = random.choice(urls) if urls else ""
                rendered_body = body.replace("[URL]", selected_url) if "[URL]" in body else body

                msg = MIMEText(rendered_body, "plain", "utf-8")
                msg["Subject"] = subject
                msg["From"] = formataddr((sender_name, sender_email))
                msg["To"] = recipient

                try:
                    smtp.sendmail(sender_email, [recipient], msg.as_string())
                    sent += 1
                    log_job_event(job_id, "SUCCESS", f"Worker {worker_id} sent to {recipient} from {sender_email}.")
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    reason = f"Worker {worker_id} recipient {recipient}: {exc}"
                    errors.append(reason)
                    log_job_event(job_id, "ERROR", reason)
    except Exception as exc:  # noqa: BLE001
        failed += len(recipients)
        reason = f"Worker {worker_id} connection/auth error: {exc}"
        errors.append(reason)
        log_job_event(job_id, "ERROR", reason)

    return sent, failed, errors


@app.get("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.get("/monitor/<job_id>")
def monitor(job_id: str):
    after = int(request.args.get("after", 0))
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({"ok": False, "error": "job_id not found"}), 404

        events = [event for event in job["events"] if event["seq"] > after]
        done = job["done"]
        sent = job.get("sent", 0)
        failed = job.get("failed", 0)
        total_recipients = job.get("total_recipients", 0)
        errors = job.get("errors", [])[:20]

    return jsonify(
        {
            "ok": True,
            "job_id": job_id,
            "done": done,
            "sent": sent,
            "failed": failed,
            "total_recipients": total_recipients,
            "errors": errors,
            "events": events,
        }
    )


@app.post("/send")
def send_mail():
    job_id = uuid.uuid4().hex[:10]
    with JOBS_LOCK:
        JOBS[job_id] = {"events": [], "done": False, "seq": 0, "sent": 0, "failed": 0, "errors": [], "total_recipients": 0}

    log_job_event(job_id, "INFO", "Incoming send request received by API.")

    try:
        payload = request.get_json(force=True)
    except Exception as exc:  # noqa: BLE001
        mark_job_done(job_id, failed=0, errors=[f"Invalid JSON payload: {exc}"])
        log_job_event(job_id, "ERROR", f"Invalid JSON payload: {exc}")
        return jsonify({"ok": False, "job_id": job_id, "error": f"Invalid JSON payload: {exc}"}), 400

    try:
        thread = threading.Thread(target=process_job, args=(job_id, payload), daemon=True, name=f"job-{job_id}")
        thread.start()
        return jsonify({"ok": True, "job_id": job_id, "status": "started"}), 202
    except Exception as exc:  # noqa: BLE001
        mark_job_done(job_id, failed=0, errors=[f"Failed to start background job: {exc}"])
        log_job_event(job_id, "ERROR", f"Failed to start background job: {exc}")
        return jsonify({"ok": False, "job_id": job_id, "error": f"Failed to start background job: {exc}"}), 500


def process_job(job_id: str, payload: dict):
    total_sent = 0
    total_failed = 0
    all_errors: list[str] = []

    try:
        host = str(payload.get("smtp_host", "")).strip()
        port = int(payload.get("smtp_port", 587))
        username = str(payload.get("smtp_user", "")).strip()
        password = str(payload.get("smtp_pass", ""))
        smtp_mode = str(payload.get("smtp_mode", "auto")).strip().lower() or "auto"

        sender_emails = split_lines(str(payload.get("sender_emails", "")))
        sender_names = split_lines(str(payload.get("sender_names", "")))
        subjects = split_lines(str(payload.get("subjects", "")))
        recipients = split_lines(str(payload.get("recipients", "")))
        urls = split_lines(str(payload.get("urls", "")))
        _src = str(payload.get("src", ""))
        body = str(payload.get("body", "")).strip()
        workers = max(1, int(payload.get("workers", 1)))

        log_job_event(
            job_id,
            "INFO",
            f"Parsed payload host={host} port={port} mode={smtp_mode} workers={workers} recipients={len(recipients)}.",
        )

        if not (host and username and password and body):
            raise ValueError("SMTP host/user/password and body are required.")
        if not sender_emails:
            raise ValueError("At least one sender email is required.")
        if not sender_names:
            raise ValueError("At least one sender name is required.")
        if not subjects:
            raise ValueError("At least one subject is required.")
        if not recipients:
            raise ValueError("At least one recipient is required.")

        workers = min(workers, len(recipients))
        chunks = [[] for _ in range(workers)]
        for index, recipient in enumerate(recipients):
            chunks[index % workers].append(recipient)

        with JOBS_LOCK:
            if job_id in JOBS:
                JOBS[job_id]["total_recipients"] = len(recipients)

        log_job_event(job_id, "INFO", f"Split workload into {workers} workers.")

        barrier = threading.Barrier(workers)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    send_batch,
                    job_id,
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
                    urls,
                    smtp_mode,
                    barrier,
                )
                for worker_id, chunk in enumerate(chunks, start=1)
            ]

            for future in as_completed(futures):
                sent, failed, errors = future.result()
                total_sent += sent
                total_failed += failed
                all_errors.extend(errors)
                log_job_event(
                    job_id,
                    "INFO",
                    f"Worker completed. Aggregate sent={total_sent}, failed={total_failed}",
                )

        log_job_event(
            job_id,
            "SUCCESS",
            f"Job finished. sent={total_sent}, failed={total_failed}, errors={len(all_errors)}",
        )
    except Exception as exc:  # noqa: BLE001
        all_errors.append(str(exc))
        total_failed = max(total_failed, 1)
        log_job_event(job_id, "ERROR", f"Unexpected error: {exc}")
    finally:
        mark_job_done(job_id, sent=total_sent, failed=total_failed, errors=all_errors)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
