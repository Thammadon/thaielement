#!/usr/bin/env python3
"""
ThaiElement · ธาตุไท — Backend Server
Flask + SQLite + JWT Authentication
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required,
    get_jwt_identity, create_refresh_token, verify_jwt_in_request
)
import sqlite3, bcrypt, os, json
from datetime import datetime, timedelta
import urllib.request, urllib.error

app = Flask(__name__, static_folder='static')
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'thaielement-secret-change-in-prod-' + os.urandom(16).hex())
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=30)
CORS(app)
jwt = JWTManager(app)

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
GEMINI_API_KEY    = os.environ.get('GEMINI_API_KEY', '')
AI_PROVIDER       = os.environ.get('AI_PROVIDER', 'gemini')  # 'gemini' | 'anthropic'
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '.env.local')

def _load_config():
    global ANTHROPIC_API_KEY, GEMINI_API_KEY, AI_PROVIDER
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            for line in f:
                line = line.strip()
                if line.startswith('ANTHROPIC_API_KEY='):
                    val = line.split('=',1)[1].strip().strip('"').strip("'")
                    if val: ANTHROPIC_API_KEY = val
                elif line.startswith('GEMINI_API_KEY='):
                    val = line.split('=',1)[1].strip().strip('"').strip("'")
                    if val: GEMINI_API_KEY = val
                elif line.startswith('AI_PROVIDER='):
                    val = line.split('=',1)[1].strip().strip('"').strip("'")
                    if val: AI_PROVIDER = val

def _save_config():
    with open(CONFIG_PATH, 'w') as f:
        if ANTHROPIC_API_KEY: f.write(f'ANTHROPIC_API_KEY="{ANTHROPIC_API_KEY}"\n')
        if GEMINI_API_KEY:    f.write(f'GEMINI_API_KEY="{GEMINI_API_KEY}"\n')
        f.write(f'AI_PROVIDER="{AI_PROVIDER}"\n')

_load_config()

DB_PATH = os.path.join(os.path.dirname(__file__), 'thaielement.db')

# ══════════════════════════════════════
# DATABASE INIT
# ══════════════════════════════════════
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT    UNIQUE NOT NULL,
            email       TEXT    UNIQUE NOT NULL,
            password    TEXT    NOT NULL,
            is_admin    INTEGER DEFAULT 0,
            created_at  TEXT    DEFAULT (datetime('now')),
            last_login  TEXT
        );

        CREATE TABLE IF NOT EXISTS profiles (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER UNIQUE NOT NULL REFERENCES users(id),
            display_name    TEXT,
            gender          TEXT,
            birth_day       INTEGER,
            birth_month     INTEGER,
            birth_year      INTEGER,
            birth_element   TEXT,
            onboarding_done INTEGER DEFAULT 0,
            total_points    INTEGER DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS onboarding_answers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            question_key TEXT NOT NULL,
            answer      TEXT NOT NULL,
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, question_key)
        );

        CREATE TABLE IF NOT EXISTS elements (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            date        TEXT NOT NULL,
            fire        REAL DEFAULT 50,
            water       REAL DEFAULT 50,
            wind        REAL DEFAULT 50,
            earth       REAL DEFAULT 50,
            updated_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, date)
        );

        CREATE TABLE IF NOT EXISTS checkins (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            date        TEXT NOT NULL,
            symptoms    TEXT,
            fire_delta  REAL DEFAULT 0,
            water_delta REAL DEFAULT 0,
            wind_delta  REAL DEFAULT 0,
            earth_delta REAL DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sleep_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            date        TEXT NOT NULL,
            bed_time    TEXT,
            wake_time   TEXT,
            hours       REAL,
            quality     TEXT,
            period_type TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, date)
        );

        CREATE TABLE IF NOT EXISTS food_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            date        TEXT NOT NULL,
            meal_time   TEXT,
            food_name   TEXT NOT NULL,
            tags        TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS excretion_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            date        TEXT NOT NULL,
            frequency   TEXT,
            bristol     TEXT,
            note        TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, date)
        );

        CREATE TABLE IF NOT EXISTS challenges (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            challenge_id TEXT NOT NULL,
            total_days  INTEGER,
            joined_at   TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, challenge_id)
        );

        CREATE TABLE IF NOT EXISTS symptoms (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            date        TEXT NOT NULL,
            symptom     TEXT NOT NULL,
            element     TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );
        """)
        # Migration: เพิ่ม is_admin column ถ้า DB เก่าไม่มี
        try:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
        except Exception:
            pass  # column มีอยู่แล้ว
    _ensure_admin()
    print(f"✅ DB initialized at {DB_PATH}")

def _ensure_admin():
    """สร้าง admin account ถ้ายังไม่มี"""
    admin_user = os.environ.get('ADMIN_USERNAME', 'admin')
    admin_pass = os.environ.get('ADMIN_PASSWORD', 'admin1234')
    admin_email = os.environ.get('ADMIN_EMAIL', 'admin@thaielement.local')
    with get_db() as conn:
        exists = conn.execute(
            "SELECT id FROM users WHERE username=? OR is_admin=1", (admin_user,)
        ).fetchone()
        if not exists:
            hashed = bcrypt.hashpw(admin_pass.encode(), bcrypt.gensalt()).decode()
            cur = conn.execute(
                "INSERT INTO users (username, email, password, is_admin) VALUES (?,?,?,1)",
                (admin_user, admin_email, hashed)
            )
            conn.execute(
                "INSERT INTO profiles (user_id, display_name, onboarding_done) VALUES (?,?,1)",
                (cur.lastrowid, 'Admin')
            )
            print(f"👑 Admin account created — username: {admin_user}  password: {admin_pass}")
        else:
            # อัปเดต is_admin=1 ให้แน่ใจ
            conn.execute("UPDATE users SET is_admin=1 WHERE username=?", (admin_user,))

# ══════════════════════════════════════
# HELPERS
# ══════════════════════════════════════
def today():
    return datetime.now().strftime('%Y-%m-%d')

def ensure_elements(conn, user_id, date):
    """Create element row for today if not exists"""
    conn.execute("""
        INSERT OR IGNORE INTO elements (user_id, date, fire, water, wind, earth)
        VALUES (?, ?, 50, 50, 50, 50)
    """, (user_id, date))

def get_elements(conn, user_id, date=None) -> 'dict[str, float]':
    d = date or today()
    ensure_elements(conn, user_id, d)
    row = conn.execute(
        "SELECT fire, water, wind, earth FROM elements WHERE user_id=? AND date=?",
        (user_id, d)
    ).fetchone()
    if row:
        return {'fire': float(row['fire']), 'water': float(row['water']), 'wind': float(row['wind']), 'earth': float(row['earth'])}
    return {'fire': 50.0, 'water': 50.0, 'wind': 50.0, 'earth': 50.0}

def clamp(v, lo=10, hi=100):
    return max(lo, min(hi, v))

def is_admin_user(uid: int) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT is_admin FROM users WHERE id=?", (uid,)).fetchone()
        return bool(row and row['is_admin'])

def require_admin():
    """คืน (uid, error_response) — ถ้า error_response ไม่ใช่ None ให้ return ทันที"""
    try:
        verify_jwt_in_request()
        uid = int(get_jwt_identity())
    except Exception:
        return None, (jsonify(error='กรุณาเข้าสู่ระบบ'), 401)
    if not is_admin_user(uid):
        return None, (jsonify(error='เฉพาะ Admin เท่านั้น'), 403)
    return uid, None

# ══════════════════════════════════════
# AUTH ROUTES
# ══════════════════════════════════════
@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    email    = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not username or not email or not password:
        return jsonify(error='กรุณากรอกข้อมูลให้ครบ'), 400
    if len(password) < 6:
        return jsonify(error='รหัสผ่านต้องมีอย่างน้อย 6 ตัวอักษร'), 400

    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    try:
        with get_db() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, email, password) VALUES (?,?,?)",
                (username, email, hashed)
            )
            user_id = cur.lastrowid
            conn.execute(
                "INSERT INTO profiles (user_id, display_name) VALUES (?,?)",
                (user_id, username)
            )
        token = create_access_token(identity=str(user_id))
        refresh = create_refresh_token(identity=str(user_id))
        return jsonify(token=token, refresh=refresh, user_id=user_id, username=username, onboarding_done=0)
    except sqlite3.IntegrityError as e:
        if 'username' in str(e):
            return jsonify(error='ชื่อผู้ใช้นี้ถูกใช้แล้ว'), 409
        return jsonify(error='อีเมลนี้ถูกใช้แล้ว'), 409

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    identifier = (data.get('identifier') or '').strip()
    password   = data.get('password') or ''

    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username=? OR email=?",
            (identifier, identifier.lower())
        ).fetchone()

    if not user or not bcrypt.checkpw(password.encode(), user['password'].encode()):
        return jsonify(error='ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง'), 401

    with get_db() as conn:
        conn.execute("UPDATE users SET last_login=datetime('now') WHERE id=?", (user['id'],))
        profile = conn.execute("SELECT * FROM profiles WHERE user_id=?", (user['id'],)).fetchone()

    token = create_access_token(identity=str(user['id']))
    refresh = create_refresh_token(identity=str(user['id']))
    return jsonify(
        token=token, refresh=refresh,
        user_id=user['id'], username=user['username'],
        onboarding_done=profile['onboarding_done'] if profile else 0
    )

@app.route('/api/auth/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh_token():
    uid = get_jwt_identity()
    token = create_access_token(identity=uid)
    return jsonify(token=token)

@app.route('/api/auth/me', methods=['GET'])
@jwt_required()
def me():
    uid = int(get_jwt_identity())
    with get_db() as conn:
        user    = conn.execute("SELECT id, username, email, created_at FROM users WHERE id=?", (uid,)).fetchone()
        profile = conn.execute("SELECT * FROM profiles WHERE user_id=?", (uid,)).fetchone()
    if not user:
        return jsonify(error='not found'), 404
    return jsonify(user=dict(user), profile=dict(profile) if profile else {})

# ══════════════════════════════════════
# ONBOARDING
# ══════════════════════════════════════
@app.route('/api/onboarding', methods=['POST'])
@jwt_required()
def save_onboarding():
    uid  = int(get_jwt_identity())
    data = request.json or {}

    answers   = dict(data.get('answers') or {})      # {question_key: answer}
    profile_d = dict(data.get('profile') or {})

    with get_db() as conn:
        # Save profile
        conn.execute("""
            UPDATE profiles SET
                display_name=?, gender=?, birth_day=?, birth_month=?, birth_year=?,
                birth_element=?, onboarding_done=1, updated_at=datetime('now')
            WHERE user_id=?
        """, (
            profile_d.get('display_name'),
            profile_d.get('gender'),
            profile_d.get('birth_day'),
            profile_d.get('birth_month'),
            profile_d.get('birth_year'),
            profile_d.get('birth_element'),
            uid
        ))
        # Save each answer
        for qkey, ans in answers.items():
            conn.execute("""
                INSERT OR REPLACE INTO onboarding_answers (user_id, question_key, answer)
                VALUES (?,?,?)
            """, (uid, qkey, str(ans)))

        # Adjust initial elements based on answers
        el = {'fire':50,'water':50,'wind':50,'earth':50}
        sleep_time = answers.get('sleep_time') or ''
        if sleep_time in ['21:00-22:00','ก่อน 21:00']:
            el['water'] += 10
        elif sleep_time in ['23:00-00:00','หลัง 00:00']:
            el['fire'] += 15

        diet = str(answers.get('diet_type') or '')
        if 'เผ็ด' in diet:   el['fire'] += 10
        if 'หวาน' in diet:   el['earth'] += 8
        if 'เค็ม' in diet:   el['water'] += 8
        if 'ผัก' in diet:    el['wind']  += 5

        stress = str(answers.get('stress_level') or '')
        if stress == 'สูงมาก': el['fire'] += 10; el['wind'] += 8
        elif stress == 'ปานกลาง': el['fire'] += 5

        exercise = str(answers.get('exercise') or '')
        if exercise == 'ไม่ค่อยออก': el['earth'] += 10
        elif exercise == 'ออกมาก':   el['wind']  += 5

        chronic = str(answers.get('chronic_disease') or '')
        if 'ความดัน' in chronic: el['water'] += 10
        if 'เบาหวาน' in chronic: el['earth'] += 10
        if 'หัวใจ'   in chronic: el['fire']  += 12
        if 'ไต'      in chronic: el['water'] += 12

        for k in el: el[k] = clamp(el[k])

        ensure_elements(conn, uid, today())
        conn.execute("""
            UPDATE elements SET fire=?,water=?,wind=?,earth=?,updated_at=datetime('now')
            WHERE user_id=? AND date=?
        """, (el['fire'],el['water'],el['wind'],el['earth'], uid, today()))

    return jsonify(success=True, elements=el)

@app.route('/api/onboarding/answers', methods=['GET'])
@jwt_required()
def get_onboarding_answers():
    uid = int(get_jwt_identity())
    with get_db() as conn:
        rows = conn.execute(
            "SELECT question_key, answer FROM onboarding_answers WHERE user_id=?", (uid,)
        ).fetchall()
    return jsonify({r['question_key']: r['answer'] for r in rows})

# ══════════════════════════════════════
# PROFILE
# ══════════════════════════════════════
@app.route('/api/profile', methods=['GET'])
@jwt_required()
def get_profile():
    uid = int(get_jwt_identity())
    with get_db() as conn:
        p = conn.execute("SELECT * FROM profiles WHERE user_id=?", (uid,)).fetchone()
        stats = {
            'sleep_count': conn.execute("SELECT COUNT(*) FROM sleep_logs WHERE user_id=?", (uid,)).fetchone()[0],
            'food_count':  conn.execute("SELECT COUNT(*) FROM food_logs WHERE user_id=?", (uid,)).fetchone()[0],
            'checkin_count': conn.execute("SELECT COUNT(*) FROM checkins WHERE user_id=?", (uid,)).fetchone()[0],
        }
    return jsonify(profile=dict(p) if p else {}, stats=stats)

@app.route('/api/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    uid  = int(get_jwt_identity())
    data = request.json or {}
    with get_db() as conn:
        conn.execute("""
            UPDATE profiles SET display_name=?, gender=?,
                birth_day=?, birth_month=?, birth_year=?, birth_element=?,
                updated_at=datetime('now')
            WHERE user_id=?
        """, (
            data.get('display_name'), data.get('gender'),
            data.get('birth_day'),    data.get('birth_month'),
            data.get('birth_year'),   data.get('birth_element'),
            uid
        ))
    return jsonify(success=True)

# ══════════════════════════════════════
# ELEMENTS
# ══════════════════════════════════════
@app.route('/api/elements/today', methods=['GET'])
@jwt_required()
def elements_today():
    uid = int(get_jwt_identity())
    with get_db() as conn:
        el = get_elements(conn, uid)
    return jsonify(el)

@app.route('/api/elements/history', methods=['GET'])
@jwt_required()
def elements_history():
    uid  = int(get_jwt_identity())
    days = int(request.args.get('days', 7))
    with get_db() as conn:
        rows = conn.execute("""
            SELECT date, fire, water, wind, earth FROM elements
            WHERE user_id=? ORDER BY date DESC LIMIT ?
        """, (uid, days)).fetchall()
    return jsonify([dict(r) for r in rows])

# ══════════════════════════════════════
# CHECK-IN
# ══════════════════════════════════════
@app.route('/api/checkin', methods=['POST'])
@jwt_required()
def save_checkin():
    uid  = int(get_jwt_identity())
    data = request.json or {}
    symptoms = data.get('symptoms', [])
    delta    = data.get('delta', {})
    d        = today()

    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO checkins (user_id, date, symptoms, fire_delta, water_delta, wind_delta, earth_delta)
            VALUES (?,?,?,?,?,?,?)
        """, (uid, d, json.dumps(symptoms, ensure_ascii=False),
              delta.get('fire',0), delta.get('water',0),
              delta.get('wind',0), delta.get('earth',0)))

        ensure_elements(conn, uid, d)
        el = get_elements(conn, uid, d)
        for k in ['fire','water','wind','earth']:
            el[k] = clamp(el[k] + delta.get(k, 0) - 3)

        conn.execute("""
            UPDATE elements SET fire=?,water=?,wind=?,earth=?,updated_at=datetime('now')
            WHERE user_id=? AND date=?
        """, (el['fire'],el['water'],el['wind'],el['earth'], uid, d))

    return jsonify(success=True, elements=el)

# ══════════════════════════════════════
# SLEEP
# ══════════════════════════════════════
@app.route('/api/sleep', methods=['POST'])
@jwt_required()
def save_sleep():
    uid  = int(get_jwt_identity())
    data = request.json or {}
    d    = today()

    bed_h = int(data.get('bed_time','22:00').split(':')[0])
    if bed_h >= 18 and bed_h < 22:   period = 'เสมหะ (น้ำ)'
    elif bed_h >= 22 or bed_h < 2:   period = 'พิตตะ (ไฟ)'
    else:                              period = 'วาตะ (ลม)'

    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO sleep_logs (user_id,date,bed_time,wake_time,hours,quality,period_type)
            VALUES (?,?,?,?,?,?,?)
        """, (uid, d, data.get('bed_time'), data.get('wake_time'),
              data.get('hours',0), data.get('quality',''), period))

        ensure_elements(conn, uid, d)
        el = get_elements(conn, uid, d)
        if bed_h >= 18 and bed_h < 22: el['water'] = clamp(el['water'] + 5)
        elif bed_h >= 22:              el['fire']  = clamp(el['fire']  + 8)
        hrs = data.get('hours', 7)
        if hrs < 5: el['fire'] = clamp(el['fire'] + 10)
        elif hrs > 9: el['water'] = clamp(el['water'] + 5)

        conn.execute("""
            UPDATE elements SET fire=?,water=?,wind=?,earth=?,updated_at=datetime('now')
            WHERE user_id=? AND date=?
        """, (el['fire'],el['water'],el['wind'],el['earth'], uid, d))

    return jsonify(success=True, period=period, elements=el)

@app.route('/api/sleep', methods=['GET'])
@jwt_required()
def get_sleep():
    uid  = int(get_jwt_identity())
    days = int(request.args.get('days', 7))
    with get_db() as conn:
        rows = conn.execute("""
            SELECT date,bed_time,wake_time,hours,quality,period_type
            FROM sleep_logs WHERE user_id=? ORDER BY date DESC LIMIT ?
        """, (uid, days)).fetchall()
    return jsonify([dict(r) for r in rows])

# ══════════════════════════════════════
# FOOD
# ══════════════════════════════════════
@app.route('/api/food', methods=['POST'])
@jwt_required()
def add_food():
    uid  = int(get_jwt_identity())
    data = request.json or {}
    d    = today()

    tags = data.get('tags', [])
    with get_db() as conn:
        conn.execute("""
            INSERT INTO food_logs (user_id,date,meal_time,food_name,tags)
            VALUES (?,?,?,?,?)
        """, (uid, d, data.get('meal_time',''), data.get('food_name',''), json.dumps(tags, ensure_ascii=False)))

        ensure_elements(conn, uid, d)
        el = get_elements(conn, uid, d)
        for t in tags:
            if 'hot'    in t: el['fire']  = clamp(el['fire']  + 4)
            if 'cool'   in t: el['water'] = clamp(el['water'] + 3)
            if 'bitter' in t: el['wind']  = clamp(el['wind']  + 2)
            if 'sour'   in t: el['wind']  = clamp(el['wind']  + 2)
            if 'salty'  in t: el['water'] = clamp(el['water'] + 2)
            if 'sweet'  in t: el['earth'] = clamp(el['earth'] + 2)

        conn.execute("""
            UPDATE elements SET fire=?,water=?,wind=?,earth=?,updated_at=datetime('now')
            WHERE user_id=? AND date=?
        """, (el['fire'],el['water'],el['wind'],el['earth'], uid, d))

    return jsonify(success=True, elements=el)

@app.route('/api/food', methods=['GET'])
@jwt_required()
def get_food():
    uid  = int(get_jwt_identity())
    date = request.args.get('date', today())
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, meal_time, food_name, tags, created_at
            FROM food_logs WHERE user_id=? AND date=? ORDER BY id ASC
        """, (uid, date)).fetchall()
    result = []
    for r in rows:
        item = {
            'id': r['id'],
            'meal_time': r['meal_time'],
            'food_name': r['food_name'],
            'created_at': r['created_at'],
            'tags': []
        }
        try: item['tags'] = json.loads(r['tags'])
        except: pass
        result.append(item)
    return jsonify(result)

@app.route('/api/food/<int:food_id>', methods=['DELETE'])
@jwt_required()
def delete_food(food_id):
    uid = int(get_jwt_identity())
    with get_db() as conn:
        conn.execute("DELETE FROM food_logs WHERE id=? AND user_id=?", (food_id, uid))
    return jsonify(success=True)

# ══════════════════════════════════════
# EXCRETION
# ══════════════════════════════════════
@app.route('/api/excretion', methods=['POST'])
@jwt_required()
def save_excretion():
    uid  = int(get_jwt_identity())
    data = request.json or {}
    d    = today()

    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO excretion_logs (user_id,date,frequency,bristol,note)
            VALUES (?,?,?,?,?)
        """, (uid, d, data.get('frequency',''), data.get('bristol',''), data.get('note','')))

        ensure_elements(conn, uid, d)
        el = get_elements(conn, uid, d)
        freq = data.get('frequency','')
        if 'ท้องผูก' in freq: el['earth'] = clamp(el['earth'] + 10)
        elif 'ปกติ'  in freq: el['earth'] = clamp(el['earth'] - 5)
        elif 'เสีย'  in freq: el['earth'] = clamp(el['earth'] + 5)

        conn.execute("""
            UPDATE elements SET fire=?,water=?,wind=?,earth=?,updated_at=datetime('now')
            WHERE user_id=? AND date=?
        """, (el['fire'],el['water'],el['wind'],el['earth'], uid, d))

    return jsonify(success=True, elements=el)

@app.route('/api/excretion', methods=['GET'])
@jwt_required()
def get_excretion():
    uid = int(get_jwt_identity())
    with get_db() as conn:
        rows = conn.execute("""
            SELECT date,frequency,bristol,note FROM excretion_logs
            WHERE user_id=? ORDER BY date DESC LIMIT 7
        """, (uid,)).fetchall()
    return jsonify([dict(r) for r in rows])

# ══════════════════════════════════════
# SYMPTOMS (DAILY SCAN)
# ══════════════════════════════════════
@app.route('/api/symptoms', methods=['POST'])
@jwt_required()
def save_symptoms():
    uid  = int(get_jwt_identity())
    data = request.json or {}
    d    = today()
    syms = data.get('symptoms', [])  # [{text, element}]

    with get_db() as conn:
        conn.execute("DELETE FROM symptoms WHERE user_id=? AND date=?", (uid, d))
        for s in syms:
            conn.execute("""
                INSERT INTO symptoms (user_id,date,symptom,element) VALUES (?,?,?,?)
            """, (uid, d, s.get('text',''), s.get('element','')))

        el = get_elements(conn, uid, d)
        counts = {}
        for s in syms:
            k = s.get('element','')
            if k in ['fire','water','wind','earth']:
                counts[k] = counts.get(k,0) + 1

        for k, v in counts.items():
            el[k] = clamp(el[k] + v*6)

        conn.execute("""
            UPDATE elements SET fire=?,water=?,wind=?,earth=?,updated_at=datetime('now')
            WHERE user_id=? AND date=?
        """, (el['fire'],el['water'],el['wind'],el['earth'], uid, d))

    return jsonify(success=True, elements=el, counts=counts)

# ══════════════════════════════════════
# CHALLENGES
# ══════════════════════════════════════
@app.route('/api/challenges', methods=['GET'])
@jwt_required()
def get_challenges():
    uid = int(get_jwt_identity())
    with get_db() as conn:
        rows = conn.execute(
            "SELECT challenge_id, total_days, joined_at FROM challenges WHERE user_id=?", (uid,)
        ).fetchall()
    result = {}
    for r in rows:
        joined = datetime.fromisoformat(r['joined_at'])
        elapsed = (datetime.now() - joined).days + 1
        result[r['challenge_id']] = {
            'total_days': r['total_days'],
            'joined_at':  r['joined_at'],
            'elapsed':    min(elapsed, r['total_days']),
            'pct':        round(min(elapsed, r['total_days']) / r['total_days'] * 100)
        }
    return jsonify(result)

@app.route('/api/challenges', methods=['POST'])
@jwt_required()
def join_challenge():
    uid  = int(get_jwt_identity())
    data = request.json or {}
    cid  = data.get('challenge_id')
    days = data.get('total_days', 7)
    with get_db() as conn:
        try:
            conn.execute("""
                INSERT INTO challenges (user_id,challenge_id,total_days) VALUES (?,?,?)
            """, (uid, cid, days))
            # Add points
            conn.execute("""
                UPDATE profiles SET total_points=total_points+50 WHERE user_id=?
            """, (uid,))
        except sqlite3.IntegrityError:
            pass
    return jsonify(success=True)

# ══════════════════════════════════════
# STATS / DASHBOARD
# ══════════════════════════════════════
@app.route('/api/dashboard', methods=['GET'])
@jwt_required()
def dashboard():
    uid = int(get_jwt_identity())
    d   = today()
    with get_db() as conn:
        el      = get_elements(conn, uid, d)
        profile = conn.execute("SELECT * FROM profiles WHERE user_id=?", (uid,)).fetchone()
        sleep   = conn.execute("SELECT * FROM sleep_logs WHERE user_id=? AND date=?", (uid,d)).fetchone()
        foods   = conn.execute("SELECT COUNT(*) FROM food_logs WHERE user_id=? AND date=?", (uid,d)).fetchone()[0]
        exret   = conn.execute("SELECT * FROM excretion_logs WHERE user_id=? AND date=?", (uid,d)).fetchone()
        checkin = conn.execute("SELECT * FROM checkins WHERE user_id=? AND date=?", (uid,d)).fetchone()
        el_hist = conn.execute("""
            SELECT date, fire, water, wind, earth FROM elements
            WHERE user_id=? ORDER BY date DESC LIMIT 7
        """, (uid,)).fetchall()

    sleep_score = 0
    if sleep:
        hrs = sleep['hours'] or 0
        sleep_score = 95 if 7 <= hrs <= 9 else (75 if hrs >= 6 else (55 if hrs >= 5 else 30))

    food_score = min(100, 50 + foods * 10) if foods else 0
    ex_score   = {'✅ ปกติ 1 ครั้ง':95,'✅✅ 2+ ครั้ง':85,'⚠️ ท้องผูก':40,'⚡ ท้องเสีย':35,'❌ ไม่ถ่าย':20}
    ex_val     = ex_score.get(exret['frequency'] if exret else '', 0)

    return jsonify(
        elements   = el,
        profile    = dict(profile) if profile else {},
        scores     = {'sleep': sleep_score, 'food': food_score, 'excretion': ex_val},
        has_sleep  = sleep is not None,
        has_food   = foods > 0,
        has_excretion = exret is not None,
        has_checkin   = checkin is not None,
        el_history = [dict(r) for r in el_hist]
    )

# ══════════════════════════════════════
# AI PROXY — Gemini & Anthropic
# ══════════════════════════════════════
def _call_gemini(prompt: str, system: str = '', max_tokens: int = 400):
    key = GEMINI_API_KEY
    if not key:
        return None, 'ยังไม่ได้ตั้งค่า Gemini API Key — ไปที่ ⚙️ ตั้งค่า'
    url = f'https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={key}'
    parts = []
    if system:
        parts.append({'text': system + '\n\n'})
    parts.append({'text': prompt})
    body = json.dumps({
        'contents': [{'role': 'user', 'parts': parts}],
        'generationConfig': {'maxOutputTokens': max_tokens, 'temperature': 0.7}
    }).encode()
    req = urllib.request.Request(url, data=body,
        headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            text = data['candidates'][0]['content']['parts'][0]['text']
            return text, None
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode()).get('error', {}).get('message', '')
        except Exception:
            detail = e.reason
        return None, f'Gemini {e.code}: {detail}'
    except Exception as e:
        return None, str(e)

def _call_anthropic_raw(prompt: str, system: str = '', history: list | None = None, max_tokens: int = 400):
    key = ANTHROPIC_API_KEY
    if not key:
        return None, 'ยังไม่ได้ตั้งค่า Anthropic API Key — ไปที่ ⚙️ ตั้งค่า'
    messages = history if history else [{'role': 'user', 'content': prompt}]
    payload  = {'model': 'claude-sonnet-4-20250514', 'max_tokens': max_tokens, 'messages': messages}
    if system: payload['system'] = system
    body = json.dumps(payload).encode()
    req  = urllib.request.Request('https://api.anthropic.com/v1/messages', data=body,
        headers={'Content-Type': 'application/json', 'x-api-key': key,
                 'anthropic-version': '2023-06-01'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data['content'][0]['text'], None
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode()).get('error', {}).get('message', '')
        except Exception:
            detail = e.reason
        return None, f'Anthropic {e.code}: {detail}'
    except Exception as e:
        return None, str(e)

def _call_ai(prompt: str, system: str = '', history: list | None = None, max_tokens: int = 400):
    """เรียก AI ตาม provider ที่เลือกไว้"""
    if AI_PROVIDER == 'anthropic':
        return _call_anthropic_raw(prompt, system, history, max_tokens)
    else:  # gemini (default)
        # Gemini ไม่รองรับ multi-turn history แบบ Anthropic — รวม history เป็น text
        if history and len(history) > 1:
            combined = '\n'.join(
                f"{'ผู้ใช้' if m['role']=='user' else 'AI'}: {m['content']}"
                for m in history
            )
            return _call_gemini(combined, system, max_tokens)
        return _call_gemini(prompt, system, max_tokens)

# ── Status & Settings (admin only) ──
@app.route('/api/ai/status', methods=['GET'])
@jwt_required()
def ai_status():
    uid, err = require_admin()
    if err: return err
    provider = AI_PROVIDER
    if provider == 'anthropic':
        key = ANTHROPIC_API_KEY
        label = 'Anthropic Claude'
    else:
        key = GEMINI_API_KEY
        label = 'Google Gemini'
    if not key:
        return jsonify(ok=False, provider=provider, message=f'ยังไม่ได้ตั้งค่า {label} API Key')
    masked = key[:10] + '...' + key[-4:]
    return jsonify(ok=True, provider=provider, message=f'{label} พร้อมใช้งาน ({masked})')

@app.route('/api/settings/apikey', methods=['POST'])
@jwt_required()
def save_apikey():
    uid, err = require_admin()
    if err: return err
    global ANTHROPIC_API_KEY, GEMINI_API_KEY, AI_PROVIDER
    data     = request.json or {}
    key      = (data.get('key') or '').strip()
    provider = (data.get('provider') or 'gemini').strip()
    if not key:
        return jsonify(error='กรุณากรอก API Key'), 400
    if provider == 'anthropic':
        if not key.startswith('sk-'):
            return jsonify(error='Anthropic Key ต้องขึ้นต้นด้วย sk-'), 400
        ANTHROPIC_API_KEY = key
    else:
        GEMINI_API_KEY = key
    AI_PROVIDER = provider
    _save_config()
    masked = key[:10] + '...' + key[-4:]
    label  = 'Anthropic Claude' if provider == 'anthropic' else 'Google Gemini'
    return jsonify(ok=True, provider=provider, message=f'บันทึก {label} Key สำเร็จ ({masked})')

@app.route('/api/settings/apikey', methods=['DELETE'])
@jwt_required()
def delete_apikey():
    uid, err = require_admin()
    if err: return err
    global ANTHROPIC_API_KEY, GEMINI_API_KEY, AI_PROVIDER
    provider = (request.args.get('provider') or AI_PROVIDER)
    if provider == 'anthropic':
        ANTHROPIC_API_KEY = ''
    else:
        GEMINI_API_KEY = ''
    _save_config()
    return jsonify(ok=True, message='ลบ API Key แล้ว')

@app.route('/api/settings/provider', methods=['POST'])
@jwt_required()
def set_provider():
    uid, err = require_admin()
    if err: return err
    global AI_PROVIDER
    data = request.json or {}
    p    = data.get('provider','gemini')
    if p not in ('gemini','anthropic'):
        return jsonify(error='provider ต้องเป็น gemini หรือ anthropic'), 400
    AI_PROVIDER = p
    _save_config()
    return jsonify(ok=True, provider=p)

# ── AI endpoints (ใช้ได้ทุก user) ──
@app.route('/api/ai/analyze', methods=['POST'])
@jwt_required()
def ai_analyze():
    data   = request.json or {}
    prompt = data.get('prompt', '')
    if not prompt:
        return jsonify(error='prompt required'), 400
    text, err = _call_ai(prompt, max_tokens=400)
    if err: return jsonify(error=err), 502
    return jsonify(text=text)

@app.route('/api/ai/chat', methods=['POST'])
@jwt_required()
def ai_chat():
    data    = request.json or {}
    system  = data.get('system', '')
    history = data.get('messages', [])
    if not history:
        return jsonify(error='messages required'), 400
    last_msg = history[-1]['content'] if history else ''
    text, err = _call_ai(last_msg, system=system, history=history, max_tokens=300)
    if err: return jsonify(error=err), 502
    return jsonify(text=text)

@app.route('/api/ai/food', methods=['POST'])
@jwt_required()
def ai_food():
    data = request.json or {}
    name = data.get('name', '')
    if not name:
        return jsonify(tags=['p-sweet หวาน'])
    system = 'วิเคราะห์รสยาอาหารไทย 9 รส ตอบเป็น JSON array เท่านั้น เช่น ["p-hot เผ็ดร้อน","p-sour เปรี้ยว"] เลือก 1-4 รส ห้ามมีข้อความอื่น'
    text, err = _call_ai(f'รสยาของ: {name}', system=system, max_tokens=100)
    if err or text is None:
        return jsonify(tags=['p-sweet หวาน'])
    try:
        tags = json.loads(text.replace('```json','').replace('```','').strip())
        return jsonify(tags=tags)
    except Exception:
        return jsonify(tags=['p-sweet หวาน'])

@app.route('/api/settings/admin', methods=['GET'])
@jwt_required()
def check_admin():
    uid = int(get_jwt_identity())
    return jsonify(is_admin=is_admin_user(uid))

# ══════════════════════════════════════
# SERVE FRONTEND
# ══════════════════════════════════════
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('static', path)

# ══════════════════════════════════════
# MAIN
# ══════════════════════════════════════
if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5055))
    print(f"🌿 ThaiElement Server running at http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)