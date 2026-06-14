import face_recognition
import cv2
import numpy as np
import mysql.connector
import base64
import json
import os
from datetime import datetime
from flask import Blueprint, request, jsonify, session, render_template_string
from dotenv import load_dotenv

load_dotenv()
face_bp = Blueprint('face', __name__)

def get_db():
    return mysql.connector.connect(
        host="localhost", user="root",
        password=os.getenv("DB_PASSWORD"),
        database="attendance_system"
    )

def setup_face_column():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS face_encoding TEXT DEFAULT NULL")
    db.commit()
    cursor.close()
    db.close()

@face_bp.route('/register_face', methods=['POST'])
def register_face():
    if session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized'}), 403
    data       = request.get_json()
    roll_no    = data.get('roll_no')
    img_base64 = data.get('image_base64')
    img_bytes  = base64.b64decode(img_base64.split(',')[-1])
    img_array  = np.frombuffer(img_bytes, dtype=np.uint8)
    img        = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    rgb_img    = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    encodings  = face_recognition.face_encodings(rgb_img)
    if len(encodings) == 0:
        return jsonify({'error': 'No face detected'}), 400
    if len(encodings) > 1:
        return jsonify({'error': 'Multiple faces detected'}), 400
    encoding_json = json.dumps(encodings[0].tolist())
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE students SET face_encoding=%s WHERE roll_no=%s", (encoding_json, roll_no))
    db.commit()
    cursor.close()
    db.close()
    return jsonify({'success': True, 'message': f'Face registered for {roll_no}'})

@face_bp.route('/mark_attendance_face', methods=['POST'])
def mark_attendance_face():
    if session.get('role') != 'teacher':
        return jsonify({'error': 'Unauthorized'}), 403
    data       = request.get_json()
    subject_id = data.get('subject_id')
    img_base64 = data.get('image_base64')
    img_bytes  = base64.b64decode(img_base64.split(',')[-1])
    img_array  = np.frombuffer(img_bytes, dtype=np.uint8)
    img        = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    rgb_img    = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    db     = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute("SELECT roll_no, name, face_encoding FROM students WHERE face_encoding IS NOT NULL")
    students = cursor.fetchall()
    known_encodings, known_roll_nos, known_names = [], [], []
    for roll_no, name, enc_json in students:
        known_encodings.append(np.array(json.loads(enc_json)))
        known_roll_nos.append(roll_no)
        known_names.append(name)
    face_locations = face_recognition.face_locations(rgb_img)
    face_encs      = face_recognition.face_encodings(rgb_img, face_locations)
    date    = datetime.now().date()
    marked  = []
    for face_enc in face_encs:
        distances = face_recognition.face_distance(known_encodings, face_enc)
        best_idx  = np.argmin(distances)
        if distances[best_idx] < 0.5:
            roll_no = known_roll_nos[best_idx]
            name    = known_names[best_idx]
            cursor.execute("SELECT id FROM attendance WHERE roll_no=%s AND subject_id=%s AND date=%s", (roll_no, subject_id, date))
            if cursor.fetchone():
                cursor.execute("UPDATE attendance SET status='present' WHERE roll_no=%s AND subject_id=%s AND date=%s", (roll_no, subject_id, date))
            else:
                cursor.execute("INSERT INTO attendance (roll_no, subject_id, date, status) VALUES (%s,%s,%s,'present')", (roll_no, subject_id, date))
            marked.append({'roll_no': roll_no, 'name': name})
    db.commit()
    cursor.close()
    db.close()
    return jsonify({'success': True, 'students_marked': marked, 'date': str(date)})

@face_bp.route('/face_attendance')
def face_attendance_page():
    if session.get('role') != 'teacher':
        return "Unauthorized", 403
    db     = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute("SELECT * FROM subjects")
    subjects = cursor.fetchall()
    cursor.close()
    db.close()
    return render_template_string(FACE_HTML, subjects=subjects)

FACE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Face Attendance</title><link rel="stylesheet" href="/static/style.css">
<style>
  #video-container{position:relative;display:inline-block;}
  .result-ok{background:#e6f4ea;border-radius:8px;padding:12px 16px;margin-top:12px;}
  .result-err{background:#fdecea;border-radius:8px;padding:12px 16px;margin-top:12px;}
</style></head>
<body style="background:#f0f2f5;">
<div class="dash">
  <div class="navbar"><span>📸 Face Attendance</span><a href="/teacher/dashboard">← Back</a></div>
  <div class="card">
    <h3 style="margin-bottom:16px;">Select Subject</h3>
    <select id="sub" style="margin-bottom:16px;">
      <option value="">-- Select Subject --</option>
      {% for s in subjects %}
      <option value="{{ s[0] }}">{{ s[1] }} ({{ s[4] }})</option>
      {% endfor %}
    </select>
    <h3 style="margin-bottom:12px;">📷 Camera</h3>
    <video id="video" width="480" height="360" autoplay style="border-radius:8px;display:block;"></video>
    <canvas id="canvas" width="480" height="360" style="display:none;"></canvas>
    <div style="margin-top:16px;display:flex;gap:12px;">
      <button onclick="startCam()">▶ Start Camera</button>
      <button onclick="capture()" id="capBtn" disabled style="background:#27ae60;">📸 Capture & Mark</button>
    </div>
  </div>
  <div class="card" id="result" style="display:none;"><div id="result-content"></div></div>
</div>
<script>
async function startCam(){
  const s=await navigator.mediaDevices.getUserMedia({video:true});
  document.getElementById('video').srcObject=s;
  document.getElementById('capBtn').disabled=false;
}
async function capture(){
  const subId=document.getElementById('sub').value;
  if(!subId){alert('Select a subject!');return;}
  const canvas=document.getElementById('canvas');
  canvas.getContext('2d').drawImage(document.getElementById('video'),0,0,480,360);
  const img=canvas.toDataURL('image/jpeg',0.9);
  document.getElementById('capBtn').textContent='⏳ Processing...';
  const res=await fetch('/mark_attendance_face',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({subject_id:subId,image_base64:img})});
  const data=await res.json();
  document.getElementById('capBtn').textContent='📸 Capture & Mark';
  document.getElementById('result').style.display='block';
  if(data.success){
    const names=data.students_marked.map(s=>`<li>✅ ${s.roll_no} — ${s.name}</li>`).join('');
    document.getElementById('result-content').innerHTML=`<div class="result-ok"><strong>${data.students_marked.length} student(s) marked present</strong><ul>${names}</ul></div>`;
  } else {
    document.getElementById('result-content').innerHTML=`<div class="result-err">❌ ${data.error}</div>`;
  }
}
</script>
</body></html>
"""