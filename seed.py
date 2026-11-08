"""Create the quiz demo data using only the Python standard library.

Place this file beside schema.sql and questions.json, then run it once.
An existing populated database is never reset or overwritten by this script.
All inserted data is committed together or rolled back on failure.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import secrets
import sys


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "quiz.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"
QUESTIONS_PATH = BASE_DIR / "questions.json"
TOPICS = ("AI", "Database", "API")
SAMPLE_PASSWORD = "12345678"  # Shared password for the local demonstration accounts only.
USER_NAMES = ('berna', 'lale', 'damla', 'sude', 'beyza', 'beril', 'ayşe', 'fatma', 'zeynep', 'elif', 'esra', 'eda', 'ece', 'selin', 'ceren', 'irem', 'duru', 'nazlı', 'deniz', 'melis', 'yağmur', 'özge', 'gizem', 'büşra', 'kübra', 'merve', 'dilara', 'simge', 'pelin', 'yasemin', 'aslı', 'başak', 'tuğçe', 'gökçe', 'sema', 'sena', 'nur', 'nisa', 'hande', 'hazal', 'aleyna', 'duygu', 'sevgi', 'bahar', 'gül', 'açelya', 'sıla', 'defne', 'nehir', 'beste')
TABLES = ("users", "sessions", "questions", "session_questions", "answers")
QUESTION_FIELDS = (
    "question_id", "topic", "question_text", "option_a", "option_b",
    "option_c", "option_d", "correct_option",
)


def timestamp(value):
    """Store UTC timestamps in the same format as CURRENT_TIMESTAMP."""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def sample_password_hash():
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(SAMPLE_PASSWORD.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt-v1${salt.hex()}${digest.hex()}"


def load_questions():
    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    if not isinstance(questions, list) or len(questions) != 150:
        raise ValueError("The question bank must contain exactly 150 questions.")

    seen_ids = set() # daha önce görülen soru kimlikleri
    seen_texts = set()
    topic_counts = Counter()

    for question in questions:
        if not isinstance(question, dict) or set(question) != set(QUESTION_FIELDS):
            raise ValueError("A question has missing or unexpected fields.")

        question_id = question["question_id"]
        if type(question_id) is not int or not 1 <= question_id <= 150:
            raise ValueError("Question IDs must be integers from 1 to 150.")
        if question_id in seen_ids:
            raise ValueError(f"Duplicate question ID: {question_id}")
        seen_ids.add(question_id)

        for field in QUESTION_FIELDS[1:]:
            value = question[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Question {question_id}: invalid {field}.")

        normalized_text = " ".join(question["question_text"].split()).casefold()
        if normalized_text in seen_texts:
            raise ValueError(f"Duplicate question text: {question_id}")
        seen_texts.add(normalized_text)

        if question["topic"] not in TOPICS:
            raise ValueError(f"Question {question_id}: unsupported topic.")
        topic_counts[question["topic"]] += 1

        if question["correct_option"] not in ("A", "B", "C", "D"):
            raise ValueError(f"Question {question_id}: invalid answer key.")

        options = [question[f"option_{letter}"].strip().casefold() for letter in "abcd"] # kısa liste oluşturma ifadesi
        if len(set(options)) != 4:
            raise ValueError(f"Question {question_id}: duplicate options.")

    if topic_counts != Counter({topic: 50 for topic in TOPICS}):
        raise ValueError("Each topic must contain exactly 50 questions.")

    def get_question_id(question):
        return question["question_id"]

    return sorted(questions, key=get_question_id) #SIRALAMADA HANGİ DEĞERN KULLANILACAĞI BELİRTİR




def insert_data(connection, questions): #BU FONK BALANTIYI AÇMAZ AÇIK OLANI KULLANIR
    now = datetime.now(timezone.utc).replace(microsecond=0)
    registered_at = timestamp(now - timedelta(hours=1))
    first_started = now - timedelta(minutes=30)
    first_ended = now - timedelta(minutes=10)

    connection.executemany(
        "INSERT INTO users (user_id, username, created_at, password_hash)"
        " VALUES (?, ?, ?, ?)",
        [(user_id, name, registered_at, sample_password_hash()) for user_id, name in enumerate(USER_NAMES, start=1)],
    )

    connection.executemany(
        "INSERT INTO sessions (session_id, title) VALUES (?, ?)",
        [(session_id, f"Computer Science Quiz {session_id}") for session_id in range(1, 6)],
    )

    connection.executemany(
        """INSERT INTO questions (
            question_id, topic, question_text, option_a, option_b,
            option_c, option_d, correct_option
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [tuple(question[field] for field in QUESTION_FIELDS) for question in questions],
    )

    by_topic = {
        topic: [question for question in questions if question["topic"] == topic]
        for topic in TOPICS
    }
    session_lists = {}
    assignments = []
    for session_id in range(1, 6):
        start = (session_id - 1) * 10
        # HER KONUDAN 10 SORU
        selected = [
            by_topic[topic][index]
            for index in range(start, start + 10)
            for topic in TOPICS
        ]
        session_lists[session_id] = selected
        assignments.extend(
            (session_id, question["question_id"], position) #HER SORU İÇİN OTURUM KİMLİĞİ SOEU KİMLİĞİ GÖSTERİM SIRASI OLUŞTURULUR
            for position, question in enumerate(selected, start=1)
        )

    connection.executemany(
        """INSERT INTO session_questions (session_id, question_id, position)
        VALUES (?, ?, ?)""", #BU YAPILINCA HALA PENDİNG DURUMUNDA ÇÜNKÜ BAŞLAMAMIŞ OTURUMA SORU ATANABİLİR
        assignments,
    )

    # OTURUM KAYDINI DEĞİŞTİR SET: YENİ DEĞERLERİ BELİRT
    connection.execute(
        "UPDATE sessions SET status = 'active', started_at = ? WHERE session_id = 1",
        (timestamp(first_started),), #BU TEK ELEMANLI BİR TUPLE
    )

    demo_answers = []
    # 30, 25 and 20 records demonstrate complete and partial submissions.
    for user_id, answer_count in ((1, 30), (2, 25), (3, 20)):
        for position, question in enumerate(session_lists[1][:answer_count], start=1):
            correct = question["correct_option"]
            if position % 7 == 0:
                selected_option = None  # Explicitly skipped question.
            elif (position + user_id) % 4 == 0:
                selected_option = "ABCD"[("ABCD".index(correct) + 1) % 4] #DOĞRU CEVABIN BİR SONRAKİ HARFİNİ SEÇEREK YANLIŞ CEVAP OLUŞTURUR %4 BAŞA DÖNMEYİ SAĞLAR
            else:
                selected_option = correct

            answered_at = first_started + timedelta(seconds=position * 20 + user_id)
            demo_answers.append(
                (user_id, 1, question["question_id"], selected_option, timestamp(answered_at)) #KULLANICI 1. OTURUM SORU SEÇİLEN SEÇENEK VE CEVAP ZAMANI
            )

    connection.executemany(
        """INSERT INTO answers (
            user_id, session_id, question_id, selected_option, answered_at
        ) VALUES (?, ?, ?, ?, ?)""",
        demo_answers,
    )

    connection.execute(
        "UPDATE sessions SET status = 'finished', ended_at = ? WHERE session_id = 1",
        (timestamp(first_ended),),
    )
    connection.execute(
        "UPDATE sessions SET status = 'active', started_at = ? WHERE session_id = 2",
        (timestamp(now),),
    )


def validate_database(connection):
    expected = dict(zip(TABLES, (50, 5, 150, 150, 75))) #ZİP İKİ YAPININ ELEMANLARINI SIRAYLA EŞLEŞTİRİR SON 2: SESSİON QUESTİON VE ANSWERS (DİCT BU EŞLEŞMELERİ SÖZLÜĞE DÖNÜŞTÜRÜR
    for table, count in expected.items():
        # Table names come exclusively from the fixed TABLES tuple.
        actual = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] #FETCHONE : BİR SONUÇ SATIRI 0 İLK SÜTUN
        if actual != count:
            raise ValueError(f"Unexpected row count for {table}: {actual}")

    distribution = connection.execute("""
        SELECT sq.session_id, q.topic, COUNT(*)
        FROM session_questions AS sq
        JOIN questions AS q ON q.question_id = sq.question_id -- İki tablodaki bilgileri ortak bir numara üzerinden yan yana getirmek demek. Sorular tablosuna bak. Soru numarası, oturuma atanan sorunun numarasıyla aynıysa bilgilerini yan yana getir.
        GROUP BY sq.session_id, q.topic
    """).fetchall()
    expected_distribution = {
        (session_id, topic, 10)
        for session_id in range(1, 6)
        for topic in TOPICS
    }
    if set(distribution) != expected_distribution:
        raise ValueError("Unexpected topic distribution across sessions.")

    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("Foreign key validation failed.")
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]: #VERİTABANININ YAPISINDA Bİ BOZUKLUK VAR MI KONTROL ET
        raise ValueError("Database integrity validation failed.")


def main():
    questions = load_questions()
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    connection = sqlite3.connect(DATABASE_PATH)

    try:
        connection.execute("PRAGMA foreign_keys = ON") #YABANCI ANAHTAR KONTROLÜNÜ AÇAR
        # The schema and all sample data are applied in one transaction.
        # The schema file must not contain its own BEGIN/COMMIT statements.
        connection.executescript("BEGIN IMMEDIATE;\n" + schema) #BEGIN IMMEDIATE;: Veritabanına yazacağımız işlem grubunu başlatır. Başka bir işlem aynı anda yazmaya çalışıyorsa yazma hakkını baştan almaya çalışır.

        for table in TABLES:
            if connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone(): # Kullanıcı bilgilerini getirme; kayıt varsa sonuç olarak sadece sabit 1 göster. En fazla bir satır getir.
                raise ValueError(
                    "The database already contains data. No changes were saved. "
                    "Seed this project only once; this script does not reset it."
                )

        insert_data(connection, questions)
        validate_database(connection)
        connection.commit()

        print("Demo data created successfully.")
        print("Database location:", DATABASE_PATH)
        for table in TABLES:
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"{table}: {count}")

        print("\nSession states:")
        for session_id, status in connection.execute(
            "SELECT session_id, status FROM sessions ORDER BY session_id"
        ):
            print(f"  {session_id}: {status}")

        print("\nTopic distribution: AI=50, Database=50, API=50")
        print("Each session: 30 questions (10 per topic)")
        print("Foreign key check: OK")
        print("Integrity check: OK")

    except Exception:
        connection.rollback() #rollback(): Kaydedilmemiş transaction değişikliklerini geri alır.
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
