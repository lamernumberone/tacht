import qrcode, socket, sqlite3, json, os, random, threading, webbrowser, csv
from datetime import datetime
from fastapi import FastAPI, Request, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI()
TIMESTAMP = ""; DB_NAME = ""
ACTIVE_QUIZ_FILE = "questions.json" # Файл за замовчуванням

def refresh_session_id(quiz_file="questions.json"):
    global TIMESTAMP, DB_NAME, ACTIVE_QUIZ_FILE
    ACTIVE_QUIZ_FILE = quiz_file
    TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M')
    DB_NAME = f"quiz_{TIMESTAMP}.db"
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (username TEXT PRIMARY KEY, ip TEXT, current_q INTEGER DEFAULT 0, 
                       correct_count INTEGER DEFAULT 0, score REAL DEFAULT 0, v_count INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS results 
                      (username TEXT PRIMARY KEY, score REAL, violations TEXT, details TEXT, ip TEXT, 
                       correct_count INTEGER, total_count INTEGER, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit(); conn.close()

os.makedirs('data', exist_ok=True); os.makedirs('static', exist_ok=True); refresh_session_id()

class UserProgress(BaseModel):
    username: str
    current_q: int
    correct_count: int
    total_q: int
    v_count: int

class RegisterUser(BaseModel):
    username: str

# Ендпоінт для отримання списку доступних тестів
@app.get("/api/list_tests")
def list_tests():
    files = [f for f in os.listdir('data') if f.endswith('.json')]
    return {"tests": files, "current": ACTIVE_QUIZ_FILE}

@app.post("/api/restart")
def restart_quiz(test_file: str = Query("questions.json")): 
    refresh_session_id(test_file)
    return {"status": "ok", "active_test": test_file}

@app.post("/api/register")
def register_user(user: RegisterUser, request: Request):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users WHERE username=?", (user.username,))
    if cursor.fetchone():
        conn.close()
        return {"status": "forbidden"}
    cursor.execute("INSERT INTO users (username, ip) VALUES (?, ?)", (user.username, request.client.host))
    conn.commit(); conn.close()
    return {"status": "ok"}

@app.get("/api/questions")
def get_questions():
    # Використовуємо вибраний вчителем файл
    path = os.path.join("data", ACTIVE_QUIZ_FILE)
    if not os.path.exists(path): path = "data/questions.json"
    
    with open(path, "r", encoding="utf-8") as f: data = json.load(f)
    qs = data["questions"]; random.shuffle(qs)
    for q in qs:
        cv = q["options"][q["correct_index"]]; random.shuffle(q["options"])
        q["correct_index"] = q["options"].index(cv)
    return {
        "quiz_id": TIMESTAMP, 
        "quiz_title": data.get("quiz_title", "Тест"), 
        "questions": qs, 
        "time_limit_seconds": data.get("time_limit_minutes", 10)*60,
        "max_score": data.get("max_score", 100),
        "min_pass_score": data.get("min_pass_score", 50)
    }

@app.post("/api/update_progress")
def update_p(data: UserProgress):
    path = os.path.join("data", ACTIVE_QUIZ_FILE)
    with open(path, "r", encoding="utf-8") as f: config = json.load(f)
    max_s = config.get("max_score", 100)
    raw = (data.correct_count / data.total_q) * max_s if data.total_q > 0 else 0
    penalty = data.v_count * (max_s * 0.1)
    score = max(0, round(raw - penalty, 1))
    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
    cursor.execute("UPDATE users SET current_q=?, correct_count=?, score=?, v_count=? WHERE username=?", 
                   (data.current_q, data.correct_count, score, data.v_count, data.username))
    conn.commit(); conn.close(); return {"status": "ok"}

@app.get("/api/active_users")
def get_users():
    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
    cursor.execute("""SELECT u.username, u.ip, u.current_q, r.username IS NOT NULL, 
                      COALESCE(r.score, u.score), u.v_count, COALESCE(r.correct_count, u.correct_count) 
                      FROM users u LEFT JOIN results r ON u.username = r.username 
                      GROUP BY u.username ORDER BY u.rowid ASC""")
    rows = cursor.fetchall(); conn.close()
    return {"users": [{"name": r[0], "ip": r[1], "progress": r[2], "finished": bool(r[3]), "score": r[4], "v_count": r[5], "correct": r[6]} for r in rows]}

@app.post("/api/save_result")
def save_r(res: dict, request: Request):
    path = os.path.join("data", ACTIVE_QUIZ_FILE)
    with open(path, "r", encoding="utf-8") as f: config = json.load(f)
    max_s = config.get("max_score", 100)
    min_pass = config.get("min_pass_score", 50)
    raw_score = (res['score'] / res['total']) * max_s if res['total'] > 0 else 0
    penalty = len(res['violations']) * (max_s * 0.1)
    final_grade = max(0, round(raw_score - penalty, 1))
    passed = final_grade >= min_pass
    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO results VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)", 
                   (res['username'], final_grade, ";".join(res['violations']), json.dumps(res['details']), request.client.host, res['score'], res['total']))
    conn.commit(); conn.close()
    return {"final_grade": final_grade, "is_passed": passed, "min_pass_score": min_pass, "max_score": max_s}

@app.get("/")
def s_p(): return FileResponse('static/index.html')
@app.get("/admin")
def t_p(): return FileResponse('static/admin.html')
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:8000/admin")).start()
    uvicorn.run(app, host="0.0.0.0", port=8000)