"""CSQuiz local classroom demo. Run: python app.py

Uses only Python's standard library. Keep quiz.db beside this file.
Learner accounts and host controls are intended for local classroom use.
"""

from contextlib import closing
from datetime import datetime, timezone
import hashlib
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import secrets
import sys
from threading import BoundedSemaphore, Lock
from time import monotonic
from unicodedata import category, normalize
from urllib.parse import parse_qs, urlsplit

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "quiz.db"
HOST = "127.0.0.1"
PORT = 8000
HOST_PASSWORD = "123456789"
HOST_TOKEN = secrets.token_urlsafe(32)
LEARNER_COOKIE = "csquiz_learner"
LOGIN_TTL = 12 * 60 * 60
LOGIN_SESSIONS = {}
LOGIN_LOCK = Lock()
PASSWORD_WORKERS = BoundedSemaphore(2)


RULES_SQL = """
CREATE TRIGGER IF NOT EXISTS trg_sessions_insert_pending BEFORE INSERT ON sessions
WHEN NEW.status <> 'pending' BEGIN SELECT RAISE(ABORT,'New sessions must be pending.'); END;
CREATE TRIGGER IF NOT EXISTS trg_sessions_update_lifecycle BEFORE UPDATE ON sessions
WHEN NOT (
 (NEW.status='pending' AND OLD.status IN ('active','finished')
  AND NEW.started_at IS NULL AND NEW.ended_at IS NULL
  AND NEW.scheduled_start_at IS NOT NULL
  AND NEW.scheduled_start_at > CURRENT_TIMESTAMP
  AND NOT EXISTS(SELECT 1 FROM answers WHERE session_id=OLD.session_id))
 OR (
  (NEW.status=OLD.status OR (OLD.status='pending' AND NEW.status='active')
   OR (OLD.status='active' AND NEW.status='finished') OR (OLD.status='finished' AND NEW.status='active'))
  AND NOT(OLD.status IN ('active','finished') AND NEW.started_at IS NOT OLD.started_at)
  AND NOT(OLD.status='finished' AND NEW.status='finished' AND NEW.ended_at IS NOT OLD.ended_at)
 )
)
BEGIN SELECT RAISE(ABORT,'Invalid session transition or timestamp change.'); END;
CREATE TRIGGER IF NOT EXISTS trg_answers_insert_active BEFORE INSERT ON answers
WHEN NOT EXISTS(SELECT 1 FROM sessions WHERE session_id=NEW.session_id AND status='active')
BEGIN SELECT RAISE(ABORT,'Answers require an active session.'); END;
CREATE TRIGGER IF NOT EXISTS trg_answers_no_update BEFORE UPDATE ON answers
BEGIN SELECT RAISE(ABORT,'Submitted answers cannot be changed.'); END;
CREATE TRIGGER IF NOT EXISTS trg_session_questions_insert_pending BEFORE INSERT ON session_questions
WHEN NOT EXISTS(SELECT 1 FROM sessions WHERE session_id=NEW.session_id AND status='pending')
BEGIN SELECT RAISE(ABORT,'Questions can be added only to pending sessions.'); END;
CREATE TRIGGER IF NOT EXISTS trg_session_questions_update_pending BEFORE UPDATE ON session_questions
WHEN NOT EXISTS(SELECT 1 FROM sessions WHERE session_id=OLD.session_id AND status='pending')
OR NOT EXISTS(SELECT 1 FROM sessions WHERE session_id=NEW.session_id AND status='pending')
BEGIN SELECT RAISE(ABORT,'Started session question lists cannot be changed.'); END;
CREATE TRIGGER IF NOT EXISTS trg_session_questions_delete_pending BEFORE DELETE ON session_questions
WHEN NOT EXISTS(SELECT 1 FROM sessions WHERE session_id=OLD.session_id AND status='pending')
BEGIN SELECT RAISE(ABORT,'Questions can be removed only from pending sessions.'); END;
CREATE TRIGGER IF NOT EXISTS trg_questions_update_protected BEFORE UPDATE ON questions
WHEN EXISTS(SELECT 1 FROM session_questions sq JOIN sessions s ON s.session_id=sq.session_id
WHERE sq.question_id=OLD.question_id AND s.status IN ('active','finished'))
BEGIN SELECT RAISE(ABORT,'Questions used in started sessions cannot be changed.'); END;
"""

def execute_statements(connection, script):
    statement = ""
    for line in script.splitlines():
        statement += line + "\n"
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""


def collapse_rounds(connection):
    """Keep each learner's latest saved attempt, then remove extra round records."""
    sessions = rows(connection,"SELECT * FROM sessions ORDER BY round_number,session_id")
    roots = {s['session_id']:s for s in sessions if s['root_session_id'] is None}
    if len(roots) != 5:
        raise ValueError("Migration requires the five original quiz sessions; no data was changed.")
    families = {key:[] for key in roots}
    for session in sessions:
        family = session['root_session_id'] or session['session_id']
        if family not in roots:
            raise ValueError("Invalid original session reference; no data was changed.")
        families[family].append(session)
    answers = rows(connection,"SELECT * FROM answers")
    grouped = {}
    for answer in answers:
        grouped.setdefault(answer['session_id'],[]).append(answer)
    latest = {}
    for session in sessions:
        family = session['root_session_id'] or session['session_id']
        for answer in grouped.get(session['session_id'],[]):
            latest[(answer['user_id'],family)] = session['session_id']
    for family,members in families.items():
        assigned = list(connection.execute("SELECT question_id,position FROM session_questions WHERE session_id=? ORDER BY position",(family,)))
        for session in members:
            other = list(connection.execute("SELECT question_id,position FROM session_questions WHERE session_id=? ORDER BY position",(session['session_id'],)))
            if [tuple(r) for r in assigned] != [tuple(r) for r in other]:
                raise ValueError("Round question lists differ; no data was changed.")
    connection.execute("DELETE FROM answers")
    for family,members in families.items():
        newest = members[-1]
        start_times = [s['started_at'] for s in members if s['started_at']]
        started = min(start_times) if start_times else None
        connection.execute("""UPDATE sessions SET status=?,started_at=?,ended_at=?,scheduled_start_at=?
            WHERE session_id=?""",(newest['status'],started,newest['ended_at'],newest['scheduled_start_at'],family))
    for (user_id,family),source in latest.items():
        for answer in grouped[source]:
            if answer['user_id'] == user_id:
                connection.execute("""INSERT INTO answers(user_id,session_id,question_id,selected_option,answered_at)
                    VALUES (?,?,?,?,?)""",(user_id,family,answer['question_id'],answer['selected_option'],answer['answered_at']))
    connection.execute("DELETE FROM session_questions WHERE session_id IN (SELECT session_id FROM sessions WHERE root_session_id IS NOT NULL)")
    connection.execute("DELETE FROM sessions WHERE root_session_id IS NOT NULL")


def upgrade_schema():
    """Upgrade older databases without replacing existing learners or answers."""
    with closing(connect_database()) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(sessions)")}
        old_policy = connection.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='trg_answers_no_delete'").fetchone()
        if 'root_session_id' in columns:
            if sqlite3.sqlite_version_info < (3,35,0):
                raise ValueError("SQLite 3.35 or later is required for this update.")
            backup = DATABASE_PATH.with_name(DATABASE_PATH.stem+'_before_latest_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')+'.db')
            with closing(sqlite3.connect(backup)) as target:
                connection.backup(target)
            print(f"Previous database backed up to: {backup}",flush=True)
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            user_columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
            if "password_hash" not in user_columns:
                connection.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(sessions)")}
            if 'scheduled_start_at' not in columns:
                connection.execute("""ALTER TABLE sessions ADD COLUMN scheduled_start_at TEXT
                    CHECK(scheduled_start_at IS NULL OR
                    (length(scheduled_start_at)=19 AND datetime(scheduled_start_at) IS NOT NULL))""")
            trigger_names = ('trg_sessions_insert_pending','trg_sessions_update_lifecycle',
                'trg_answers_insert_active','trg_answers_no_update','trg_answers_no_delete',
                'trg_session_questions_insert_pending','trg_session_questions_update_pending',
                'trg_session_questions_delete_pending','trg_questions_update_protected',
                'trg_sessions_round_insert','trg_sessions_round_immutable')
            for name in trigger_names:
                connection.execute(f'DROP TRIGGER IF EXISTS {name}')
            if 'root_session_id' in columns:
                collapse_rounds(connection)
                connection.execute('DROP INDEX IF EXISTS idx_sessions_round')
                connection.execute('ALTER TABLE sessions DROP COLUMN root_session_id')
                connection.execute('ALTER TABLE sessions DROP COLUMN round_number')
            count = connection.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
            if count != 5:
                raise ValueError("Exactly five quiz sessions are required; no data was changed.")
            execute_statements(connection,RULES_SQL)
            if connection.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError("Foreign key validation failed; no data was changed.")
        if old_policy:
            print("Scoring policy: latest attempt per learner and session; exactly five sessions.",flush=True)


def start_due_sessions():
    """Start scheduled sessions when an API request observes their due time."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with closing(connect_database()) as connection:
        due = connection.execute("SELECT 1 FROM sessions WHERE status='pending' AND scheduled_start_at<=? LIMIT 1", (now,)).fetchone()
        if due:
            with connection:
                connection.execute("""UPDATE sessions SET status='active',started_at=?
                    WHERE status='pending' AND scheduled_start_at<=?
                    AND (SELECT COUNT(*) FROM session_questions sq WHERE sq.session_id=sessions.session_id)=30""", (now,now))


def personal_summary(connection, user_id, session_id=None):
    condition = "AND a.session_id=?" if session_id is not None else ""
    parameters = (user_id, session_id) if session_id is not None else (user_id,)
    summaries = rows(connection, f"""
        SELECT a.session_id, COUNT(*) AS submitted,
            SUM(CASE WHEN a.selected_option=q.correct_option THEN 1 ELSE 0 END) AS correct,
            SUM(CASE WHEN a.selected_option IS NOT NULL AND a.selected_option<>q.correct_option THEN 1 ELSE 0 END) AS wrong,
            SUM(CASE WHEN a.selected_option IS NULL THEN 1 ELSE 0 END) AS blank,
            (SELECT COUNT(*) FROM session_questions sq WHERE sq.session_id=a.session_id) AS total
        FROM answers a JOIN questions q ON q.question_id=a.question_id
        WHERE a.user_id=? {condition} GROUP BY a.session_id
    """, parameters)
    return summaries


def session_leaderboard(connection, session_id):
    return rows(connection, """
        WITH scores AS (
            SELECT u.user_id,u.username,COUNT(*) AS submitted,
                SUM(CASE WHEN a.selected_option=q.correct_option THEN 1 ELSE 0 END) AS score,
                SUM(CASE WHEN a.selected_option IS NOT NULL AND a.selected_option<>q.correct_option THEN 1 ELSE 0 END) AS wrong,
                SUM(CASE WHEN a.selected_option IS NULL THEN 1 ELSE 0 END) AS blank
            FROM answers a JOIN users u ON u.user_id=a.user_id
            JOIN questions q ON q.question_id=a.question_id
            WHERE a.session_id=? GROUP BY u.user_id,u.username
        )
        SELECT RANK() OVER (ORDER BY score DESC) AS rank,* FROM scores
        ORDER BY score DESC,user_id
    """, (session_id,))

SESSION_SQL = """
WITH sizes AS (
    SELECT session_id, COUNT(*) AS question_count
    FROM session_questions GROUP BY session_id
), submissions AS (
    SELECT session_id, COUNT(DISTINCT user_id) AS participants,
           COUNT(*) AS submitted_records
    FROM answers GROUP BY session_id
)
SELECT s.*, COALESCE(z.question_count, 0) AS question_count,
       COALESCE(a.participants, 0) AS participants,
       COALESCE(a.submitted_records, 0) AS submitted_records,
       ROUND(100.0 * a.submitted_records /
           NULLIF(a.participants * z.question_count, 0), 2) AS progress_percent
FROM sessions s
LEFT JOIN sizes z ON z.session_id = s.session_id
LEFT JOIN submissions a ON a.session_id = s.session_id
ORDER BY s.session_id
"""

LEADERBOARD_SQL = """
WITH sizes AS (
    SELECT session_id, COUNT(*) AS total FROM session_questions GROUP BY session_id
), scores AS (
    SELECT a.user_id, a.session_id,
           SUM(CASE WHEN a.selected_option = q.correct_option THEN 1 ELSE 0 END) AS score
    FROM answers a JOIN questions q ON q.question_id = a.question_id
    JOIN sessions s ON s.session_id = a.session_id
    WHERE s.status = 'finished'
    GROUP BY a.user_id, a.session_id
), totals AS (
    SELECT sc.user_id, COUNT(*) AS session_count, SUM(sc.score) AS score,
           SUM(sz.total) AS maximum_score
    FROM scores sc JOIN sizes sz ON sz.session_id = sc.session_id
    GROUP BY sc.user_id
)
SELECT RANK() OVER (ORDER BY t.score DESC) AS rank, u.username, t.*,
       ROUND(100.0 * t.score / NULLIF(t.maximum_score, 0), 2) AS percentage
FROM totals t JOIN users u ON u.user_id = t.user_id
ORDER BY t.score DESC, t.user_id LIMIT 10
"""


class APIError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


def connect_database():
    # mode=rw avoids silently creating an empty database in the wrong directory.
    connection = sqlite3.connect(DATABASE_PATH.as_uri() + "?mode=rw", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def rows(connection, sql, parameters=()):
    return [dict(row) for row in connection.execute(sql, parameters)]


def positive_integer(value, name):
    if type(value) is not int or value <= 0:
        raise APIError(400, f"{name} must be a positive integer.")
    return value


def require_user(connection, user_id):
    user = connection.execute("SELECT user_id, username FROM users WHERE user_id=?", (user_id,)).fetchone()
    if user is None:
        raise APIError(404, "Learner not found.")
    return dict(user)


def account_credentials(data):
    nickname, password = data.get("nickname"), data.get("password")
    if not isinstance(nickname, str):
        raise APIError(400, "Enter a nickname.")
    nickname = normalize("NFKC", nickname.strip()).casefold()
    if not 3 <= len(nickname) <= 30 or not nickname[0].isalnum() or not all(
            ch.isalnum() or ch in "_-" or category(ch).startswith("M") for ch in nickname):
        raise APIError(400, "Use 3–30 letters, numbers, underscores or hyphens. Start with a letter or number.")
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise APIError(400, "Use a password between 8 and 128 characters.")
    try:
        return nickname, password.encode("utf-8")
    except UnicodeError:
        raise APIError(400, "Invalid password characters.") from None


def password_digest(password, salt):
    if not PASSWORD_WORKERS.acquire(blocking=False):
        raise APIError(503, "Sign-in is busy. Try again in a moment.")
    try:
        return hashlib.scrypt(password, salt=salt, n=16384, r=8, p=1, dklen=32)
    finally:
        PASSWORD_WORKERS.release()


def learner_account(data, registering=False):
    nickname, password = account_credentials(data)
    if registering:
        salt = secrets.token_bytes(16)
        stored = f"scrypt-v1${salt.hex()}${password_digest(password, salt).hex()}"
        with closing(connect_database()) as connection, connection:
            try:
                cursor = connection.execute(
                    "INSERT INTO users(username, password_hash) VALUES (?, ?)", (nickname, stored))
            except sqlite3.IntegrityError as error:
                if error.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                    raise APIError(409, "That nickname is already taken. Choose another.") from None
                raise
            return {"user_id": cursor.lastrowid, "username": nickname}
    with closing(connect_database()) as connection:
        account = connection.execute(
            "SELECT user_id, username, password_hash FROM users WHERE username=?", (nickname,)).fetchone()
    stored = account["password_hash"] if account else None
    if stored:
        version, salt_hex, digest_hex = stored.split("$")
        if version != "scrypt-v1":
            raise APIError(401, "Incorrect nickname or password.")
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
    else:
        # Run the same password calculation for unregistered and sample names.
        salt, expected = bytes(16), bytes(32)
    matches = secrets.compare_digest(password_digest(password, salt), expected)
    if not stored or not matches:
        raise APIError(401, "Incorrect nickname or password.")
    return {"user_id": account["user_id"], "username": account["username"]}


def require_session(connection, session_id):
    session = connection.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    if session is None:
        raise APIError(404, "Session not found.")
    return dict(session)


def session_results(connection, session_id, user_id):
    # Called after personal completion or after the shared session ends.
    details = rows(connection, """
        SELECT sq.position, q.question_id, q.question_text, q.topic,
               q.option_a, q.option_b, q.option_c, q.option_d, q.correct_option,
               a.selected_option, a.answered_at,
               CASE WHEN a.question_id IS NULL THEN 'unanswered'
                    WHEN a.selected_option IS NULL THEN 'skipped'
                    WHEN a.selected_option=q.correct_option THEN 'correct'
                    ELSE 'wrong' END AS outcome
        FROM session_questions sq JOIN questions q ON q.question_id=sq.question_id
        LEFT JOIN answers a ON a.session_id=sq.session_id
            AND a.question_id=sq.question_id AND a.user_id=?
        WHERE sq.session_id=? ORDER BY sq.position
    """, (user_id, session_id))
    counts = {kind: sum(item["outcome"] == kind for item in details)
              for kind in ("correct", "wrong", "skipped", "unanswered")}
    count = len(details)
    return {**counts, "total": count, "score": counts["correct"],
            "percentage": round(100 * counts["correct"] / count, 2) if count else 0,
            "participated": any(item["outcome"] != "unanswered" for item in details),
            "questions": details}


def get_data(path, parameters):
    start_due_sessions()
    with closing(connect_database()) as connection:
        # Keep the status, question list and results in one consistent snapshot.
        connection.execute("BEGIN")
        if path == "/api/overview":
            progress = []
            if "user_id" in parameters:
                try:
                    user_id = positive_integer(int(parameters["user_id"][0]), "user_id")
                except (ValueError, IndexError):
                    raise APIError(400, "Invalid user_id.") from None
                require_user(connection, user_id)
                progress = rows(connection, "SELECT session_id, COUNT(*) AS submitted FROM answers WHERE user_id=? GROUP BY session_id", (user_id,))
            return {
                "sessions": rows(connection, SESSION_SQL),
                "leaderboard": rows(connection, LEADERBOARD_SQL),
                "question_count": connection.execute("SELECT COUNT(*) FROM questions").fetchone()[0],
                "personal_progress": progress,
            }
        if path == "/api/host-results":
            try:
                session_id=positive_integer(int(parameters["session_id"][0]),"session_id")
            except (KeyError,ValueError,IndexError):
                raise APIError(400,"A valid session_id is required.") from None
            session=require_session(connection,session_id)
            results=rows(connection,"""
                WITH scores AS (
                    SELECT u.user_id,u.username,COUNT(*) AS total,
                        COUNT(a.question_id) AS saved,
                        SUM(CASE WHEN a.selected_option=q.correct_option THEN 1 ELSE 0 END) AS correct,
                        SUM(CASE WHEN a.selected_option IS NOT NULL AND a.selected_option<>q.correct_option THEN 1 ELSE 0 END) AS wrong,
                        SUM(CASE WHEN a.question_id IS NOT NULL AND a.selected_option IS NULL THEN 1 ELSE 0 END) AS blank,
                        COUNT(*)-COUNT(a.question_id) AS unanswered
                    FROM users u CROSS JOIN session_questions sq
                    JOIN questions q ON q.question_id=sq.question_id
                    LEFT JOIN answers a ON a.user_id=u.user_id AND a.session_id=sq.session_id AND a.question_id=sq.question_id
                    WHERE sq.session_id=? GROUP BY u.user_id,u.username
                )
                SELECT *,CASE WHEN saved>0 THEN RANK() OVER (ORDER BY (saved>0) DESC,correct DESC) END AS rank,
                    ROUND(100.0*correct/NULLIF(total,0),2) AS score_percent
                FROM scores ORDER BY (saved>0) DESC,correct DESC,user_id
            """,(session_id,))
            return {"session":session,"results":results,
                    "participants":sum(item["saved"]>0 for item in results)}
        if path == "/api/profile":
            try:
                user_id = positive_integer(int(parameters["user_id"][0]), "user_id")
            except (KeyError, ValueError, IndexError):
                raise APIError(400, "A valid user_id is required.") from None
            profile = require_user(connection, user_id)
            history = personal_summary(connection, user_id)
            completed = sum(item["submitted"] == item["total"] and item["total"] > 0 for item in history)
            correct = sum(item["correct"] for item in history)
            answered = sum(item["submitted"] - item["blank"] for item in history)
            badges = []
            if history: badges.append("First steps")
            if completed: badges.append("Quiz finisher")
            if correct >= 20: badges.append("Knowledge explorer")
            if any(item["correct"] == item["total"] and item["total"] > 0 for item in history): badges.append("Perfect score")
            return {**profile,"sessions_joined":len(history),"completed":completed,
                "correct":correct,"answered":answered,"accuracy":round(100*correct/answered,1) if answered else None,
                "badges":badges,"history":history}
        if path == "/api/session":
            try:
                session_id = positive_integer(int(parameters["session_id"][0]), "session_id")
                user_id = positive_integer(int(parameters["user_id"][0]), "user_id")
            except (KeyError, ValueError, IndexError):
                raise APIError(400, "A valid session_id and user_id are required.") from None
            user = require_user(connection, user_id)
            session = require_session(connection, session_id)
            questions = []
            if session["status"] != "pending":
                questions = rows(connection, """
                    SELECT sq.position, q.question_id, q.topic, q.question_text,
                           q.option_a, q.option_b, q.option_c, q.option_d,
                           a.question_id IS NOT NULL AS submitted, a.selected_option,
                           CASE WHEN a.selected_option IS NOT NULL THEN q.correct_option END AS revealed_answer
                    FROM session_questions sq JOIN questions q ON q.question_id=sq.question_id
                    LEFT JOIN answers a ON a.session_id=sq.session_id
                        AND a.question_id=sq.question_id AND a.user_id=?
                    WHERE sq.session_id=? ORDER BY sq.position
                """, (user_id, session_id))
            submitted = sum(question["submitted"] for question in questions)
            completed = bool(questions) and submitted == len(questions)
            result = session_results(connection, session_id, user_id) if completed or session["status"] == "finished" else None
            if result is not None and session["status"] != "finished":
                # Return aggregates immediately but protect item-level keys
                # until the shared session has ended for everyone.
                result["questions"] = []
            return {
                "user": user, "session": session, "questions": questions,
                "completed": completed, "results": result,
                "personal_stats": personal_summary(connection,user_id,session_id),
                "leaderboard": session_leaderboard(connection,session_id),
            }
        raise APIError(404, "Endpoint not found.")


def post_data(path, data):
    start_due_sessions()
    if path not in ("/api/answers", "/api/attempts/finish", "/api/sessions/start", "/api/sessions/finish", "/api/sessions/schedule", "/api/attempts/restart"):
        raise APIError(404, "Endpoint not found.")
    session_id = positive_integer(data.get("session_id"), "session_id")
    with closing(connect_database()) as connection:
        with connection:
            # Serialize the state check and write to prevent finish/submit races.
            connection.execute("BEGIN IMMEDIATE")
            session = require_session(connection, session_id)
            if path == "/api/attempts/restart":
                user_id = positive_integer(data.get("user_id"), "user_id")
                require_user(connection,user_id)
                if session["status"] != "active":
                    raise APIError(409,"Ask the host to reopen this session before retrying.")
                count=connection.execute("SELECT COUNT(*) FROM answers WHERE user_id=? AND session_id=?",(user_id,session_id)).fetchone()[0]
                if not count:
                    raise APIError(409,"No saved answers to reset. Open the quiz to begin.")
                connection.execute("DELETE FROM answers WHERE user_id=? AND session_id=?",(user_id,session_id))
                return {"message":"Your previous answers were replaced. Only your new attempt will count."}
            if path == "/api/sessions/schedule":
                rescheduling = session["status"] != "pending"
                if rescheduling and connection.execute(
                    "SELECT 1 FROM answers WHERE session_id=? LIMIT 1", (session_id,)
                ).fetchone():
                    raise APIError(409, "Sessions with saved answers cannot be postponed.")
                schedule=data.get("scheduled_start_at")
                if rescheduling and schedule is None:
                    raise APIError(400, "Choose a future start time to postpone this session.")
                if schedule is not None:
                    if not isinstance(schedule,str):
                        raise APIError(400,"Use a UTC date and time or null.")
                    try:
                        planned=datetime.strptime(schedule,"%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    except ValueError:
                        raise APIError(400,"Invalid scheduled date and time.") from None
                    if planned<=datetime.now(timezone.utc):
                        raise APIError(400,"Choose a future start time.")
                if rescheduling:
                    connection.execute(
                        "UPDATE sessions SET status='pending', started_at=NULL, ended_at=NULL, scheduled_start_at=? WHERE session_id=?",
                        (schedule, session_id),
                    )
                    return {"message": "Session postponed. It will open at the scheduled time when the app receives a request."}
                connection.execute("UPDATE sessions SET scheduled_start_at=? WHERE session_id=?",(schedule,session_id))
                return {"message":"Start time saved." if schedule else "Schedule cleared."}
            if path == "/api/attempts/finish":
                user_id = positive_integer(data.get("user_id"), "user_id")
                require_user(connection, user_id)
                if session["status"] != "active":
                    raise APIError(409, "This session is no longer accepting submissions. Refresh to see your results.")
                count = connection.execute("SELECT COUNT(*) FROM session_questions WHERE session_id=?", (session_id,)).fetchone()[0]
                if count != 30:
                    raise APIError(409, "The session must contain 30 questions.")
                # Add only missing answers, preserving every existing answer.
                # A repeat finish request inserts zero rows.
                connection.execute("""INSERT INTO answers
                    (user_id, session_id, question_id, selected_option)
                    SELECT ?, sq.session_id, sq.question_id, NULL
                    FROM session_questions sq WHERE sq.session_id=?
                      AND NOT EXISTS (SELECT 1 FROM answers a
                        WHERE a.user_id=? AND a.session_id=sq.session_id
                        AND a.question_id=sq.question_id)
                """, (user_id, session_id, user_id))
                return {"message": "Your quiz is complete. Other learners can keep answering."}
            if path == "/api/answers":
                user_id = positive_integer(data.get("user_id"), "user_id")
                question_id = positive_integer(data.get("question_id"), "question_id")
                require_user(connection, user_id)
                if "selected_option" not in data:
                    raise APIError(400, "selected_option is required, including null for a skip.")
                selected = data["selected_option"]
                if selected is not None and (not isinstance(selected, str) or selected not in ("A", "B", "C", "D")):
                    raise APIError(400, "Choose A, B, C or D, or skip the question.")
                if session["status"] != "active":
                    raise APIError(409, "This session is not accepting answers.")
                if not connection.execute("SELECT 1 FROM session_questions WHERE session_id=? AND question_id=?", (session_id, question_id)).fetchone():
                    raise APIError(400, "This question does not belong to the session.")
                if connection.execute("SELECT 1 FROM answers WHERE user_id=? AND session_id=? AND question_id=?", (user_id, session_id, question_id)).fetchone():
                    raise APIError(409, "This answer has already been submitted.")
                connection.execute("""INSERT INTO answers
                    (user_id, session_id, question_id, selected_option)
                    VALUES (?, ?, ?, ?)""", (user_id, session_id, question_id, selected))
                correct = connection.execute("SELECT correct_option FROM questions WHERE question_id=?",(question_id,)).fetchone()[0]
                return {"message":"Answer saved." if selected is not None else "Blank saved.",
                    "correct":selected==correct if selected is not None else None,
                    "correct_option":correct if selected is not None else None}
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            if path.endswith("/start"):
                if session["status"] == "finished":
                    connection.execute("UPDATE sessions SET status='active',ended_at=NULL WHERE session_id=?",(session_id,))
                    return {"message":"Session reopened. Learners can retake it; existing scores stay until they restart."}
                if session["status"] != "pending":
                    raise APIError(409, "This session is already active.")
                count = connection.execute("SELECT COUNT(*) FROM session_questions WHERE session_id=?", (session_id,)).fetchone()[0]
                if count != 30:
                    raise APIError(409, "A session must have 30 assigned questions before starting.")
                connection.execute("UPDATE sessions SET status='active', started_at=? WHERE session_id=?", (now, session_id))
                return {"message": "Session started."}
            if session["status"] != "active":
                raise APIError(409, "Only an active session can be finished.")
            if now < session["started_at"]:
                raise APIError(409, "The system clock is earlier than the session start time.")
            connection.execute("UPDATE sessions SET status='finished', ended_at=? WHERE session_id=?", (now, session_id))
            return {"message": "Session finished. Results are now available."}


class Handler(BaseHTTPRequestHandler):
    server_version = "CSQuiz"

    def send_content(self, status, content, content_type, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(content)

    def json_response(self, status, payload, cookie=None):
        self.send_content(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", cookie)

    def check_host(self):
        port = self.server.server_port
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            raise APIError(403, "Use the local CSQuiz address.")

    def has_host_access(self):
        token = self.headers.get("X-CSQuiz-Host", "")
        return secrets.compare_digest(token.encode("utf-8"), HOST_TOKEN.encode("utf-8"))

    def require_host_access(self):
        if not self.has_host_access():
            raise APIError(401, "Enter the host password first.")

    def learner_token(self):
        try:
            value = SimpleCookie(self.headers.get("Cookie", "")).get(LEARNER_COOKIE)
            return value.value if value else None
        except CookieError:
            return None

    def learner_id(self, required=True):
        token = self.learner_token()
        with LOGIN_LOCK:
            session = LOGIN_SESSIONS.get(token)
            if session and session[1] > monotonic():
                return session[0]
            LOGIN_SESSIONS.pop(token, None)
        if required:
            raise APIError(401, "Sign in to your learner account first.")

    def learner_login(self, account):
        token = secrets.token_urlsafe(32)
        now = monotonic()
        with LOGIN_LOCK:
            LOGIN_SESSIONS.pop(self.learner_token(), None)
            for expired in [key for key, (_, expiry) in LOGIN_SESSIONS.items() if expiry <= now]:
                LOGIN_SESSIONS.pop(expired)
            if len(LOGIN_SESSIONS) >= 1024:
                LOGIN_SESSIONS.pop(next(iter(LOGIN_SESSIONS)))
            LOGIN_SESSIONS[token] = (account["user_id"], now + LOGIN_TTL)
        return f"{LEARNER_COOKIE}={token}; Path=/; Max-Age={LOGIN_TTL}; HttpOnly; SameSite=Strict"

    def handle_error(self, error):
        if isinstance(error, APIError):
            self.json_response(error.status, {"error": error.message})
        elif isinstance(error, sqlite3.IntegrityError):
            self.json_response(409, {"error": "The operation conflicts with a database rule."})
        elif isinstance(error, sqlite3.OperationalError) and "locked" in str(error).lower():
            self.json_response(503, {"error": "The database is busy. Save or revert DB Browser edits, then retry."})
        else:
            self.log_error("Request failed: %s", error)
            self.json_response(500, {"error": "The request could not be completed. Check the Python console."})

    def do_GET(self):
        try:
            self.check_host()
            url = urlsplit(self.path)
            assets = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
                "/live.css": ("live.css", "text/css; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            }
            if url.path in assets:
                name, content_type = assets[url.path]
                self.send_content(200, (BASE_DIR / "web" / name).read_bytes(), content_type)
            elif url.path.startswith("/api/"):
                path = url.path
                parameters = parse_qs(url.query)
                if path == "/api/account/me":
                    user_id = self.learner_id(required=False)
                    with closing(connect_database()) as connection:
                        account = require_user(connection, user_id) if user_id else None
                    self.json_response(200, {"user": account})
                    return
                if path == "/api/host-results":
                    self.require_host_access()
                elif path in ("/api/overview", "/api/profile", "/api/session"):
                    user_id = self.learner_id(required=path != "/api/overview" or not self.has_host_access())
                    if "user_id" in parameters and parameters["user_id"] != [str(user_id)]:
                        raise APIError(403, "You can only access your own quiz account.")
                    if user_id is not None:
                        parameters["user_id"] = [str(user_id)]
                self.json_response(200, get_data(path, parameters))
            else:
                raise APIError(404, "Page not found.")
        except Exception as error:
            self.handle_error(error)

    def do_POST(self):
        try:
            self.check_host()
            origin = self.headers.get("Origin")
            port = self.server.server_port
            if origin is not None and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
                raise APIError(403, "Cross-origin writes are not allowed.")
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                raise APIError(415, "Send application/json content.")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise APIError(400, "Invalid content length.") from None
            if not 0 < length <= 8192:
                raise APIError(413, "Request body must be between 1 and 8192 bytes.")
            try:
                data = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeError):
                raise APIError(400, "Invalid JSON body.") from None
            if not isinstance(data, dict):
                raise APIError(400, "Send a JSON object.")
            path = urlsplit(self.path).path
            if path == "/api/host/login":
                password = data.get("password")
                if not isinstance(password, str) or not secrets.compare_digest(
                        password.encode("utf-8"), HOST_PASSWORD.encode("utf-8")):
                    raise APIError(401, "Incorrect host password.")
                self.json_response(200, {"token": HOST_TOKEN})
            elif path in ("/api/account/register", "/api/account/login"):
                registering = path.endswith("/register")
                account = learner_account(data, registering)
                self.json_response(201 if registering else 200, {"user": account}, self.learner_login(account))
            elif path == "/api/account/logout":
                with LOGIN_LOCK:
                    LOGIN_SESSIONS.pop(self.learner_token(), None)
                self.json_response(200, {"message": "Signed out."},
                                   f"{LEARNER_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict")
            else:
                if path.startswith("/api/sessions/"):
                    self.require_host_access()
                elif path in ("/api/answers", "/api/attempts/finish", "/api/attempts/restart"):
                    user_id = self.learner_id()
                    if "user_id" in data and (type(data["user_id"]) is not int or data["user_id"] != user_id):
                        raise APIError(403, "You can only modify your own quiz answers.")
                    data["user_id"] = user_id
                self.json_response(200, post_data(path, data))
        except Exception as error:
            self.handle_error(error)


def main():
    if not DATABASE_PATH.is_file():
        print("quiz.db was not found beside app.py. Run main.py and seed.py first.", file=sys.stderr)
        return 1
    upgrade_schema()
    with closing(connect_database()) as connection:
        required = {"users", "sessions", "questions", "session_questions", "answers"}
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required.issubset(tables):
            print("The database schema is incomplete. Run main.py first.", file=sys.stderr)
            return 1
        if not connection.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            print("The database is empty. Run seed.py first.", file=sys.stderr)
            return 1
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"CSQuiz is running at http://{HOST}:{PORT}", flush=True)
    print("Keep this process running. Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping CSQuiz.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"Could not start CSQuiz: {error}", file=sys.stderr)
        sys.exit(1)
