PRAGMA foreign_keys = ON; /* PRAGMA: SQLite ayarları ve kontrolleri için kullanılan komut.*/
CREATE TABLE IF NOT EXISTS users (
 user_id INTEGER PRIMARY KEY,
 username TEXT NOT NULL UNIQUE CHECK(length(trim(username)) BETWEEN 3 AND 30), /*trim(username)	Başındaki ve sonundaki normal boşlukları kontrol için çıkarır.*/
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP /*CURRENT_TIMESTAMP: SQLite’ın o andaki UTC tarih ve saatini verir.*/
 CHECK(
     typeof(created_at)='text'
         AND length(created_at)=19
         AND created_at GLOB
             '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
         AND datetime(created_at, '+0 days') IS NOT NULL
         AND datetime(created_at, '+0 days')=created_at),
 password_hash TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
 session_id INTEGER PRIMARY KEY,
 title TEXT NOT NULL CHECK(length(trim(title)) > 0),
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','active','finished')),
 started_at TEXT CHECK(started_at IS NULL OR (typeof(started_at)='text' AND length(started_at)=19
                                                  AND started_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
                                                  AND datetime(started_at, '+0 days') IS NOT NULL
                                                  AND datetime(started_at, '+0 days')=started_at)),
 ended_at TEXT CHECK(ended_at IS NULL OR (typeof(ended_at)='text'
                                              AND length(ended_at)=19
                                              AND ended_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
                                              AND datetime(ended_at, '+0 days') IS NOT NULL
                                              AND datetime(ended_at, '+0 days')=ended_at)),
 scheduled_start_at TEXT CHECK(scheduled_start_at IS NULL
                                   OR (typeof(scheduled_start_at)='text'
                                                                  AND length(scheduled_start_at)=19
                                           AND scheduled_start_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
                                           AND datetime(scheduled_start_at, '+0 days') IS NOT NULL
                                           AND datetime(scheduled_start_at, '+0 days')=scheduled_start_at)),
 CHECK((status='pending' AND started_at IS NULL AND ended_at IS NULL)
 OR (status='active' AND started_at IS NOT NULL AND ended_at IS NULL)
 OR (status='finished' AND started_at IS NOT NULL AND ended_at IS NOT NULL AND ended_at>=started_at))
);
CREATE TABLE IF NOT EXISTS questions (
 question_id INTEGER PRIMARY KEY,
 topic TEXT NOT NULL CHECK(topic IN ('AI','Database','API')),
 question_text TEXT NOT NULL UNIQUE CHECK(length(trim(question_text))>0),
 option_a TEXT NOT NULL CHECK(length(trim(option_a))>0),
 option_b TEXT NOT NULL CHECK(length(trim(option_b))>0),
 option_c TEXT NOT NULL CHECK(length(trim(option_c))>0),
 option_d TEXT NOT NULL CHECK(length(trim(option_d))>0),
 correct_option TEXT NOT NULL CHECK(correct_option IN ('A','B','C','D')) /*Neden ayrı options tablosu yok?
Bu projede bütün soruların dört seçeneği var. Sabit yapı için dört sütun kullandık.*/
);
CREATE TABLE IF NOT EXISTS session_questions ( /* Hangi soru, hangi oturumda, kaçıncı sırada bulunuyor?*/
 session_id INTEGER NOT NULL, question_id INTEGER NOT NULL,
 position INTEGER NOT NULL CHECK(typeof(position)='integer' AND position>0),
 PRIMARY KEY(session_id,question_id), UNIQUE(session_id,position),
 FOREIGN KEY(session_id) REFERENCES sessions(session_id),
 FOREIGN KEY(question_id) REFERENCES questions(question_id)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS answers (
 user_id INTEGER NOT NULL, session_id INTEGER NOT NULL, question_id INTEGER NOT NULL,
 selected_option TEXT CHECK(selected_option IN ('A','B','C','D')),
 answered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
 CHECK(typeof(answered_at)='text' AND length(answered_at)=19 AND answered_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]' AND datetime(answered_at, '+0 days') IS NOT NULL AND datetime(answered_at, '+0 days')=answered_at),
 PRIMARY KEY(user_id,session_id,question_id),
 FOREIGN KEY(user_id) REFERENCES users(user_id),
 FOREIGN KEY(session_id,question_id) REFERENCES session_questions(session_id,question_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_session_questions_question ON session_questions(question_id);
CREATE INDEX IF NOT EXISTS idx_answers_session_question ON answers(session_id,question_id);
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
