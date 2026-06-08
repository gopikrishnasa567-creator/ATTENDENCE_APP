from flask import Flask, render_template, request, redirect, session
import mysql.connector
from datetime import datetime

app = Flask(__name__)
app.secret_key = "attendance_secret_key"

db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="YOUR_PASSWORD_HERE",
    database="attendance_system",
)
cursor = db.cursor(buffered=True)

# HOME
@app.route('/')
def home():
    return render_template('login.html')

# LOGIN — handles both teacher and student
@app.route('/login', methods=['POST'])
def login():
    role     = request.form['role']
    username = request.form['username']
    password = request.form['password']

    if role == 'teacher':
        cursor.execute("SELECT * FROM teachers WHERE username=%s AND password=%s",
                       (username, password))
        user = cursor.fetchone()
        if user:
            session['role']     = 'teacher'
            session['username'] = username
            session['id']       = user[0]
            return redirect('/teacher/dashboard')
        else:
            return render_template('login.html', error="Invalid teacher credentials")

    elif role == 'student':
        cursor.execute("SELECT * FROM students WHERE roll_no=%s AND password=%s",
                       (username, password))
        user = cursor.fetchone()
        if user:
            session['role']    = 'student'
            session['roll_no'] = username
            session['name']    = user[1]
            return redirect('/student/dashboard')
        else:
            return render_template('login.html', error="Invalid roll number or password")

# TEACHER DASHBOARD — view timetable and mark attendance
@app.route('/teacher/dashboard')
def teacher_dashboard():
    if session.get('role') != 'teacher':
        return redirect('/')
    cursor.execute("SELECT * FROM subjects ORDER BY FIELD(day,'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'), start_time")
    subjects = cursor.fetchall()
    return render_template('teacher_dashboard.html',
                           subjects=subjects,
                           username=session['username'])

# MARK ATTENDANCE (teacher marks present/absent per subject)
@app.route('/mark_attendance', methods=['POST'])
def mark_attendance():
    if session.get('role') != 'teacher':
        return redirect('/')
    subject_id = request.form['subject_id']
    date       = datetime.now().date()   # ← auto picks today's date
    cursor.execute("SELECT roll_no FROM students")
    students = cursor.fetchall()
    for student in students:
        roll_no = student[0]
        status  = request.form.get(f'status_{roll_no}', 'absent')
        # check if record exists
        cursor.execute(
            "SELECT id FROM attendance WHERE roll_no=%s AND subject_id=%s AND date=%s",
            (roll_no, subject_id, date)
        )
        existing = cursor.fetchone()
        if existing:
            cursor.execute(
                "UPDATE attendance SET status=%s WHERE roll_no=%s AND subject_id=%s AND date=%s",
                (status, roll_no, subject_id, date)
            )
        else:
            cursor.execute(
                "INSERT INTO attendance (roll_no, subject_id, date, status) VALUES (%s,%s,%s,%s)",
                (roll_no, subject_id, date, status)
            )
    db.commit()
    return redirect('/teacher/dashboard')

# STUDENT DASHBOARD — see attendance % subject wise
@app.route('/student/dashboard')
def student_dashboard():
    if session.get('role') != 'student':
        return redirect('/')
    roll_no = session['roll_no']
    cursor.execute("SELECT DISTINCT s.id, s.name FROM subjects s JOIN attendance a ON s.id=a.subject_id WHERE a.roll_no=%s", (roll_no,))
    subjects = cursor.fetchall()
    stats = []
    for sub in subjects:
        sub_id   = sub[0]
        sub_name = sub[1]
        cursor.execute("SELECT COUNT(*) FROM attendance WHERE roll_no=%s AND subject_id=%s", (roll_no, sub_id))
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM attendance WHERE roll_no=%s AND subject_id=%s AND status='present'", (roll_no, sub_id))
        present = cursor.fetchone()[0]
        percentage = round((present / total) * 100, 1) if total > 0 else 0
        stats.append({'subject': sub_name, 'total': total, 'present': present, 'percentage': percentage})
    # timetable
    cursor.execute("SELECT * FROM subjects ORDER BY FIELD(day,'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'), start_time")
    timetable = cursor.fetchall()
    return render_template('student_dashboard.html',
                           name=session['name'],
                           roll_no=roll_no,
                           stats=stats,
                           timetable=timetable)

# LOGOUT
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == '__main__':
    app.run(debug=True)