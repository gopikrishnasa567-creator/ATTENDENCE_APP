import os
import json
from datetime import datetime
from flask import Blueprint, request, jsonify, session, render_template_string
import mysql.connector
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
chatbot_bp = Blueprint('chatbot', __name__)
client     = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def get_db():
    return mysql.connector.connect(
        host="localhost", user="root",
        password=os.getenv("DB_PASSWORD"),
        database="attendance_system"
    )

@chatbot_bp.route('/student/chat', methods=['POST'])
def student_chat():
    if session.get('role') != 'student':
        return jsonify({'error': 'Unauthorized'}), 403
    user_message = request.get_json().get('message', '').strip()
    roll_no = session['roll_no']
    db     = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute("""
        SELECT s.name, COUNT(*) as total,
               SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) as present
        FROM attendance a JOIN subjects s ON a.subject_id=s.id
        WHERE a.roll_no=%s GROUP BY s.id, s.name
    """, (roll_no,))
    rows = cursor.fetchall()
    cursor.close()
    db.close()
    subject_data = []
    for subject, total, present in rows:
        total, present = int(total), int(present)
        pct      = round((present/total)*100, 1) if total > 0 else 0
        can_skip = max(0, int((present - 0.75*total)/0.75)) if pct >= 75 else 0
        needed   = max(0, int((0.75*total - present)/0.25)+1) if pct < 75 else 0
        subject_data.append({'subject': subject, 'total': total, 'present': present,
                              'percentage': pct, 'can_skip': can_skip, 'needed': needed})
    system_prompt = f"""You are an AI attendance assistant for a college.
You are talking to student {session['name']} (Roll No: {roll_no}).
Their attendance data: {json.dumps(subject_data, indent=2)}
Rules: Min required attendance is 75%. Answer clearly using only this data.
Keep answers to 2-4 sentences. Today: {datetime.now().strftime('%d %B %Y')}."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )
    return jsonify({'reply': response.content[0].text})

@chatbot_bp.route('/teacher/generate_report', methods=['POST'])
def generate_report():
    if session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized'}), 403
    db     = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute("""
        SELECT st.roll_no, st.name, COUNT(a.id) as total,
               SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) as present
        FROM students st LEFT JOIN attendance a ON st.roll_no=a.roll_no
        GROUP BY st.roll_no, st.name
    """)
    students = cursor.fetchall()
    cursor.close()
    db.close()
    student_list = []
    for row in students:
        roll_no, name, total, present = row
        total, present = int(total or 0), int(present or 0)
        pct = round((present/total)*100, 1) if total > 0 else 0
        student_list.append({'roll_no': roll_no, 'name': name, 'total': total, 'present': present, 'percentage': pct})
    at_risk  = [s for s in student_list if s['percentage'] < 75 and s['total'] > 0]
    avg_pct  = round(sum(s['percentage'] for s in student_list if s['total'] > 0) / max(1, len(student_list)), 1)
    prompt   = f"""Generate a professional attendance report for a college teacher.
Total students: {len(student_list)}, Average attendance: {avg_pct}%, At risk (<75%): {len(at_risk)}
Student data: {json.dumps(student_list, indent=2)}
Write 3 paragraphs: 1) Overall summary 2) At-risk students by name 3) Recommendations. Be factual and clear."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )
    return jsonify({'report': response.content[0].text,
                    'generated_at': datetime.now().strftime('%d %B %Y, %I:%M %p'),
                    'stats': {'total': len(student_list), 'at_risk': len(at_risk), 'avg_pct': avg_pct}})

@chatbot_bp.route('/student/chatbot')
def student_chatbot_page():
    if session.get('role') != 'student':
        return "Unauthorized", 403
    return render_template_string(CHATBOT_HTML, name=session['name'])

@chatbot_bp.route('/teacher/report')
def teacher_report_page():
    if session.get('role') != 'teacher':
        return "Unauthorized", 403
    db     = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute("SELECT * FROM subjects")
    subjects = cursor.fetchall()
    cursor.close()
    db.close()
    return render_template_string(REPORT_HTML, subjects=subjects, username=session['username'])

CHATBOT_HTML = """
<!DOCTYPE html><html>
<head><title>AI Assistant</title><link rel="stylesheet" href="/static/style.css">
<style>
  #chat{height:380px;overflow-y:auto;padding:16px;background:#f8f9ff;border-radius:8px;margin-bottom:12px;}
  .msg{margin-bottom:14px;display:flex;gap:10px;align-items:flex-start;}
  .msg.user{flex-direction:row-reverse;}
  .bubble{max-width:75%;padding:10px 14px;border-radius:12px;font-size:14px;line-height:1.5;}
  .msg.bot .bubble{background:#0f3460;color:white;}
  .msg.user .bubble{background:#e6f4ea;color:#1a1a2e;}
  .av{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0;background:#0f3460;color:white;}
  .msg.user .av{background:#27ae60;}
  .qbtns{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px;}
  .qbtn{padding:6px 12px;background:white;border:1.5px solid #0f3460;border-radius:20px;cursor:pointer;font-size:13px;color:#0f3460;}
  .qbtn:hover{background:#0f3460;color:white;}
</style></head>
<body style="background:#f0f2f5;">
<div class="dash">
  <div class="navbar"><span>🤖 AI Attendance Assistant</span><a href="/student/dashboard">← Back</a></div>
  <div class="card">
    <h3 style="margin-bottom:8px;">Ask anything about your attendance</h3>
    <div class="qbtns">
      <button class="qbtn" onclick="ask('What is my current attendance percentage?')">What is my %?</button>
      <button class="qbtn" onclick="ask('Which subjects am I at risk in?')">Am I at risk?</button>
      <button class="qbtn" onclick="ask('How many more classes can I miss?')">How many can I skip?</button>
      <button class="qbtn" onclick="ask('What do I need to do to reach 75%?')">How to reach 75%?</button>
    </div>
    <div id="chat">
      <div class="msg bot"><div class="av">🤖</div>
        <div class="bubble">Hi {{ name }}! 👋 I can see your real attendance data. Ask me anything!</div>
      </div>
    </div>
    <p id="typing" style="color:#888;font-size:13px;display:none;">🤖 Thinking...</p>
    <div style="display:flex;gap:8px;">
      <input type="text" id="inp" placeholder="Type your question..." onkeypress="if(event.key==='Enter')send()" style="flex:1;">
      <button onclick="send()" style="width:auto;padding:11px 20px;">Send</button>
    </div>
  </div>
</div>
<script>
function ask(q){document.getElementById('inp').value=q;send();}
async function send(){
  const inp=document.getElementById('inp');
  const msg=inp.value.trim();
  if(!msg)return;
  inp.value='';
  addMsg(msg,'user');
  document.getElementById('typing').style.display='block';
  const data=await(await fetch('/student/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg})})).json();
  document.getElementById('typing').style.display='none';
  addMsg(data.reply||'Sorry, something went wrong.','bot');
}
function addMsg(text,type){
  const c=document.getElementById('chat');
  c.innerHTML+=`<div class="msg ${type}"><div class="av">${type==='bot'?'🤖':'👤'}</div><div class="bubble">${text.replace(/\\n/g,'<br>')}</div></div>`;
  c.scrollTop=c.scrollHeight;
}
</script>
</body></html>
"""

REPORT_HTML = """
<!DOCTYPE html><html>
<head><title>AI Report</title><link rel="stylesheet" href="/static/style.css">
<style>#report-box{background:#f8f9ff;border-radius:8px;padding:20px;white-space:pre-wrap;font-size:14px;line-height:1.7;display:none;}</style>
</head>
<body style="background:#f0f2f5;">
<div class="dash">
  <div class="navbar"><span>📋 AI Report Generator</span><a href="/teacher/dashboard">← Back</a></div>
  <div class="card">
    <h3 style="margin-bottom:16px;">Generate Attendance Report</h3>
    <div style="display:flex;gap:12px;align-items:flex-end;">
      <div style="flex:1;">
        <label style="font-size:13px;color:#555;display:block;margin-bottom:6px;">Subject (optional)</label>
        <select id="sub"><option value="">All Subjects (Full Report)</option>
          {% for s in subjects %}<option value="{{ s[0] }}">{{ s[1] }} ({{ s[4] }})</option>{% endfor %}
        </select>
      </div>
      <button onclick="gen()" id="btn" style="width:auto;padding:12px 24px;">✨ Generate AI Report</button>
    </div>
  </div>
  <div class="card" id="report-card" style="display:none;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
      <h3>Generated Report</h3>
      <button onclick="navigator.clipboard.writeText(document.getElementById('report-box').textContent).then(()=>alert('Copied!'))" style="width:auto;padding:8px 16px;background:#555;font-size:13px;">📋 Copy</button>
    </div>
    <p id="meta" style="font-size:12px;color:#888;margin-bottom:12px;"></p>
    <div id="report-box"></div>
  </div>
</div>
<script>
async function gen(){
  const btn=document.getElementById('btn');
  btn.textContent='⏳ Generating...';btn.disabled=true;
  const data=await(await fetch('/teacher/generate_report',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({subject_id:document.getElementById('sub').value||null})})).json();
  btn.textContent='✨ Generate AI Report';btn.disabled=false;
  document.getElementById('report-card').style.display='block';
  document.getElementById('report-box').style.display='block';
  document.getElementById('report-box').textContent=data.report;
  document.getElementById('meta').textContent=`Generated on ${data.generated_at} | ${data.stats.total} students | ${data.stats.at_risk} at risk | Avg: ${data.stats.avg_pct}%`;
  document.getElementById('report-card').scrollIntoView({behavior:'smooth'});
}
</script>
</body></html>
"""