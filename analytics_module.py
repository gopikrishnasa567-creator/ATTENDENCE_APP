import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from flask import Blueprint, jsonify, session, render_template_string
import mysql.connector
from dotenv import load_dotenv

load_dotenv()
analytics_bp = Blueprint('analytics', __name__)

def get_db():
    return mysql.connector.connect(
        host="localhost", user="root",
        password=os.getenv("DB_PASSWORD"),
        database="attendance_system"
    )

def get_all_student_stats():
    db     = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute("SELECT roll_no, name, email FROM students")
    students = cursor.fetchall()
    stats = []
    for roll_no, name, email in students:
        cursor.execute("SELECT COUNT(*) FROM attendance WHERE roll_no=%s", (roll_no,))
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM attendance WHERE roll_no=%s AND status='present'", (roll_no,))
        present    = cursor.fetchone()[0]
        percentage = round((present / total) * 100, 1) if total > 0 else 0
        needed     = max(0, int((0.75*total - present) / 0.25) + 1) if percentage < 75 and total > 0 else 0
        can_skip   = max(0, int((present - 0.75*total) / 0.75)) if percentage >= 75 and total > 0 else 0
        cursor.execute("""
            SELECT DAYNAME(date), COUNT(*) FROM attendance
            WHERE roll_no=%s AND status='absent'
            GROUP BY DAYNAME(date) ORDER BY COUNT(*) DESC LIMIT 1
        """, (roll_no,))
        row      = cursor.fetchone()
        bunk_day = row[0] if row and row[1] >= 2 else None
        stats.append({'roll_no': roll_no, 'name': name, 'email': email,
                      'total': total, 'present': present, 'absent': total-present,
                      'percentage': percentage, 'at_risk': percentage < 75,
                      'needed': needed, 'can_skip': can_skip, 'bunk_day': bunk_day})
    cursor.close()
    db.close()
    return stats

@analytics_bp.route('/analytics/risk')
def risk_prediction():
    if session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized'}), 403
    stats = get_all_student_stats()
    return jsonify({'at_risk': [s for s in stats if s['at_risk']], 'safe': [s for s in stats if not s['at_risk']]})

@analytics_bp.route('/analytics/patterns')
def patterns():
    if session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized'}), 403
    db     = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute("""
        SELECT DAYNAME(date), COUNT(*) FROM attendance WHERE status='absent'
        GROUP BY DAYNAME(date)
        ORDER BY FIELD(DAYNAME(date),'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday')
    """)
    day_patterns = [{'day': r[0], 'absences': r[1]} for r in cursor.fetchall()]
    cursor.execute("""
        SELECT s.name, COUNT(*) as total,
               SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) as present
        FROM attendance a JOIN subjects s ON a.subject_id=s.id
        GROUP BY s.id, s.name
    """)
    subject_stats = [{'subject': r[0], 'total': r[1],
                      'present': r[2], 'percentage': round((r[2]/r[1])*100,1) if r[1]>0 else 0}
                     for r in cursor.fetchall()]
    cursor.close()
    db.close()
    return jsonify({'day_patterns': day_patterns, 'subject_stats': subject_stats})

@analytics_bp.route('/analytics/send_alerts', methods=['POST'])
def send_alerts():
    if session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized'}), 403
    sender_email    = os.getenv("ALERT_EMAIL")
    sender_password = os.getenv("ALERT_PASSWORD")
    if not sender_email or not sender_password:
        return jsonify({'error': 'ALERT_EMAIL and ALERT_PASSWORD not set in .env'}), 400
    stats   = get_all_student_stats()
    at_risk = [s for s in stats if s['at_risk'] and s['email']]
    sent, failed = [], []
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        for student in at_risk:
            try:
                msg = MIMEMultipart('alternative')
                msg['Subject'] = f"⚠️ Low Attendance Alert — {student['name']}"
                msg['From']    = sender_email
                msg['To']      = student['email']
                html = f"""<html><body style="font-family:sans-serif;padding:20px;">
                <h2 style="color:#e74c3c;">⚠️ Low Attendance Warning</h2>
                <p>Dear <strong>{student['name']}</strong>,</p>
                <p>Your attendance is <strong style="color:#e74c3c;">{student['percentage']}%</strong> (required: 75%).</p>
                <p>Attend the next <strong>{student['needed']}</strong> classes consecutively to recover.</p>
                </body></html>"""
                msg.attach(MIMEText(html, 'html'))
                server.sendmail(sender_email, student['email'], msg.as_string())
                sent.append(student['name'])
            except Exception as e:
                failed.append({'name': student['name'], 'error': str(e)})
        server.quit()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'success': True, 'alerts_sent': len(sent), 'sent_to': sent, 'failed': failed})

@analytics_bp.route('/analytics/dashboard')
def analytics_dashboard():
    if session.get('role') != 'teacher':
        return "Unauthorized", 403
    stats = get_all_student_stats()
    return render_template_string(ANALYTICS_HTML, stats=stats)

ANALYTICS_HTML = """
<!DOCTYPE html>
<html>
<head><title>Analytics</title><link rel="stylesheet" href="/static/style.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  .risk-high{background:#fdecea;color:#c0392b;padding:4px 10px;border-radius:20px;font-size:12px;font-weight:bold;}
  .risk-ok{background:#e6f4ea;color:#2d7a3a;padding:4px 10px;border-radius:20px;font-size:12px;font-weight:bold;}
  .stat-box{background:#f8f9ff;border-radius:8px;padding:16px;text-align:center;flex:1;}
  .stat-num{font-size:28px;font-weight:bold;color:#0f3460;}
</style></head>
<body style="background:#f0f2f5;">
<div class="dash">
  <div class="navbar"><span>📊 Analytics Dashboard</span><a href="/teacher/dashboard">← Back</a></div>
  {% set at_risk = stats | selectattr('at_risk') | list %}
  <div class="card" style="display:flex;gap:16px;">
    <div class="stat-box"><div class="stat-num">{{ stats|length }}</div><div>Total Students</div></div>
    <div class="stat-box"><div class="stat-num" style="color:#e74c3c;">{{ at_risk|length }}</div><div>At Risk (&lt;75%)</div></div>
    <div class="stat-box"><div class="stat-num" style="color:#27ae60;">{{ stats|length - at_risk|length }}</div><div>Safe (≥75%)</div></div>
  </div>
  <div class="card" style="display:flex;gap:16px;flex-wrap:wrap;">
    <div style="flex:1;min-width:280px;"><h3 style="margin-bottom:12px;">Distribution</h3><canvas id="pie" height="200"></canvas></div>
    <div style="flex:1;min-width:280px;"><h3 style="margin-bottom:12px;">Day-wise Absences</h3><canvas id="bar" height="200"></canvas></div>
  </div>
  <div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
      <h3>Student Risk Analysis</h3>
      <button onclick="sendAlerts()" style="background:#e74c3c;width:auto;padding:10px 20px;">📧 Send Email Alerts</button>
    </div>
    <div id="alert-msg"></div>
    <table>
      <tr><th>Roll No</th><th>Name</th><th>Present</th><th>Total</th><th>%</th><th>Status</th><th>Action</th><th>Pattern</th></tr>
      {% for s in stats | sort(attribute='percentage') %}
      <tr>
        <td>{{ s.roll_no }}</td><td>{{ s.name }}</td><td>{{ s.present }}</td><td>{{ s.total }}</td>
        <td><strong>{{ s.percentage }}%</strong></td>
        <td><span class="{{ 'risk-high' if s.at_risk else 'risk-ok' }}">{{ '⚠️ At Risk' if s.at_risk else '✅ Safe' }}</span></td>
        <td style="font-size:13px;">{% if s.at_risk %}Attend next <strong>{{ s.needed }}</strong>{% else %}Can skip <strong>{{ s.can_skip }}</strong> more{% endif %}</td>
        <td style="font-size:13px;color:#e67e22;">{{ ('Often absent on '+s.bunk_day) if s.bunk_day else '—' }}</td>
      </tr>
      {% endfor %}
    </table>
  </div>
</div>
<script>
const stats={{ stats|tojson }};
const risk=stats.filter(s=>s.at_risk).length;
new Chart(document.getElementById('pie'),{type:'doughnut',data:{labels:['At Risk','Safe'],datasets:[{data:[risk,stats.length-risk],backgroundColor:['#e74c3c','#27ae60'],borderWidth:0}]},options:{plugins:{legend:{position:'bottom'}}}});
fetch('/analytics/patterns').then(r=>r.json()).then(data=>{
  new Chart(document.getElementById('bar'),{type:'bar',data:{labels:data.day_patterns.map(d=>d.day),datasets:[{label:'Absences',data:data.day_patterns.map(d=>d.absences),backgroundColor:'#e74c3c',borderRadius:6}]},options:{plugins:{legend:{display:false}},scales:{y:{beginAtZero:true}}}});
});
async function sendAlerts(){
  document.getElementById('alert-msg').innerHTML='<p>⏳ Sending...</p>';
  const data=await(await fetch('/analytics/send_alerts',{method:'POST'})).json();
  document.getElementById('alert-msg').innerHTML=data.success?`<div style="background:#e6f4ea;padding:12px;border-radius:8px;">✅ Sent ${data.alerts_sent} alerts to: ${data.sent_to.join(', ')}</div>`:`<div style="color:red;">❌ ${data.error}</div>`;
}
</script>
</body></html>
"""