from flask import Flask, render_template_string, request, jsonify
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
import random
import time
from concurrent.futures import ThreadPoolExecutor
import queue
import json

app = Flask(__name__)

# Global variables for configuration and status
config = {
    'smtp_host': '',
    'smtp_port': 587,
    'smtp_user': '',
    'smtp_pass': '',
    'senders': [],
    'sender_names': [],
    'subjects': [],
    'recipients': [],
    'body': '',
    'workers': 10
}

status = {
    'running': False,
    'total_sent': 0,
    'total_emails': 0,
    'errors': 0,
    'progress': 0
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
            background: #0a0a0a;
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
        input, textarea {
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
        input:focus, textarea:focus {
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
        .log {
            background: #000;
            border: 1px solid #333;
            border-radius: 6px;
            height: 200px;
            overflow-y: auto;
            padding: 15px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
            margin-top: 20px;
            color: #00ff88;
        }
        @media (max-width: 768px) {
            .form-grid {
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
            <div class="log" id="log"></div>
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
                senders: document.getElementById('senders').value.split('\\n').map(s => s.trim()).filter(Boolean),
                sender_names: document.getElementById('sender_names').value.split('\\n').map(s => s.trim()).filter(Boolean),
                subjects: document.getElementById('subjects').value.split('\\n').map(s => s.trim()).filter(Boolean),
                recipients: document.getElementById('recipients').value.split('\\n').map(s => s.trim()).filter(Boolean),
                body: document.getElementById('body').value,
                workers: parseInt(document.getElementById('workers').value)
            };
            
            const sendBtn = document.getElementById('sendBtn');
            sendBtn.disabled = true;
            sendBtn.textContent = 'Sending...';
            isRunning = true;
            
            document.getElementById('statusPanel').style.display = 'block';
            
            const response = await fetch('/send', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(formData)
            });
            
            sendBtn.disabled = false;
            sendBtn.textContent = '🚀 Send Emails';
            isRunning = false;
        });
        
        // Status polling
        setInterval(async () => {
            if (isRunning) {
                const response = await fetch('/status');
                const data = await response.json();
                
                document.getElementById('totalSent').textContent = data.total_sent;
                document.getElementById('totalEmails').textContent = data.total_emails;
                document.getElementById('errors').textContent = data.errors;
                document.getElementById('progressPct').textContent = data.progress + '%';
                document.getElementById('progressFill').style.width = data.progress + '%';
                
                document.getElementById('log').textContent = data.log.slice(-1000);
                document.getElementById('log').scrollTop = document.getElementById('log').scrollHeight;
            }
        }, 1000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/send', methods=['POST'])
def send_emails():
    global config, status, email_queue
    data = request.json
    
    # Update config
    config.update(data)
    
    # Reset status
    status = {
        'running': True,
        'total_sent': 0,
        'total_emails': len(config['recipients']) * 10,  # Estimate
        'errors': 0,
        'progress': 0,
        'log': []
    }
    
    # Populate email queue
    email_queue = queue.Queue()
    for _ in range(100):  # Generate queue items
        for recipient in config['recipients']:
            email_queue.put(recipient)
    
    # Start workers
    executor = ThreadPoolExecutor(max_workers=config['workers'])
    
    futures = []
    for i in range(config['workers']):
        future = executor.submit(worker_function, i)
        futures.append(future)
    
    # Store futures for status checking
    from flask import g
    if not hasattr(g, 'futures'):
        g.futures = []
    g.futures = futures
    
    return jsonify({'status': 'started'})

def worker_function(worker_id):
    """Worker thread function"""
    global status, email_queue
    
    try:
        server = smtplib.SMTP(config['smtp_host'], config['smtp_port'])
        server.starttls()
        server.login(config['smtp_user'], config['smtp_pass'])
        
        log_message(f"Worker {worker_id}: Connected to SMTP server")
        
        sent_count = 0
        while status['running'] and not email_queue.empty():
            try:
                recipient = email_queue.get(timeout=1)
                
                # Randomly select sender details
                sender_email = random.choice(config['senders'])
                sender_name = random.choice(config['sender_names'])
                subject = random.choice(config['subjects'])
                
                # Create email
                msg = MimeMultipart()
                msg['From'] = f"{sender_name} <{sender_email}>"
                msg['To'] = recipient
                msg['Subject'] = subject
                
                msg.attach(MimeText(config['body'], 'plain'))
                
                # Send email
                server.send_message(msg)
                
                with lock:
                    status['total_sent'] += 1
                    sent_count += 1
                    status['progress'] = min(100, (status['total_sent'] / status['total_emails']) * 100)
                
                log_message(f"Worker {worker_id}: Sent to {recipient} from {sender_name}")
                email_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                with lock:
                    status['errors'] += 1
                log_message(f"Worker {worker_id}: Error sending to {recipient}: {str(e)}")
        
        server.quit()
        log_message(f"Worker {worker_id}: Completed ({sent_count} emails sent)")
        
    except Exception as e:
        log_message(f"Worker {worker_id}: Failed to connect: {str(e)}")

def log_message(message):
    """Thread-safe logging"""
    global status
    with lock:
        status['log'].append(f"[{time.strftime('%H:%M:%S')}] {message}")
        if len(status['log']) > 1000:
            status['log'] = status['log'][-500:]

@app.route('/status')
def get_status():
    global status
    return jsonify(status)

if __name__ == '__main__':
    print("🚀 SMTP Mass Mailer starting on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
