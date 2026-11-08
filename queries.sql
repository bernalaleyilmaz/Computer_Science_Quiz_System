-- CSQuiz: verification, progress and results.
-- Run a selected statement in DB Browser for SQLite's Execute SQL tab.
-- All executable statements in this file are read-only except the
-- connection-level foreign key setting. No quiz data is changed.
-- Times are stored in UTC. Correct = 1 point, wrong or blank = 0.
-- A participant is a user with at least one answer record in that session.
-- A NULL selected_option is an explicitly skipped question.
-- No answer record means the question has not been submitted.

PRAGMA foreign_keys = ON;

-- Q1. Verify the foreign key setting for this connection (expected: 1).
PRAGMA foreign_keys;

-- Q2. Verify all required record counts.
SELECT 'users' AS table_name, COUNT(*) AS record_count FROM users
UNION ALL
SELECT 'sessions', COUNT(*) FROM sessions
UNION ALL
SELECT 'questions', COUNT(*) FROM questions
UNION ALL
SELECT 'session_questions', COUNT(*) FROM session_questions
UNION ALL
SELECT 'answers', COUNT(*) FROM answers;

-- Q3. Verify 50 questions per topic.
SELECT topic, COUNT(*) AS question_count
FROM questions
GROUP BY topic
ORDER BY topic;

-- Q4. Verify 30 questions per session, with 10 from each topic.
SELECT
    s.session_id,
    s.title,
    COUNT(sq.question_id) AS total_questions,
    SUM(CASE WHEN q.topic = 'AI' THEN 1 ELSE 0 END) AS ai_questions,
    SUM(CASE WHEN q.topic = 'Database' THEN 1 ELSE 0 END) AS database_questions,
    SUM(CASE WHEN q.topic = 'API' THEN 1 ELSE 0 END) AS api_questions
FROM sessions AS s
LEFT JOIN session_questions AS sq ON sq.session_id = s.session_id
LEFT JOIN questions AS q ON q.question_id = sq.question_id
GROUP BY s.session_id, s.title
ORDER BY s.session_id;

-- Q5. Session status and live progress for all sessions.
-- Re-run to read the current committed data.
-- Progress measures submitted records, including explicit skips, among
-- observed participants. It does not assume all registered users joined.
-- With no participants, progress is NULL (unknown/not applicable), not 100%.
WITH question_totals AS (
    SELECT session_id, COUNT(*) AS question_count
    FROM session_questions
    GROUP BY session_id
), answer_totals AS (
    SELECT
        session_id,
        COUNT(DISTINCT user_id) AS participant_count,
        COUNT(*) AS submitted_records,
        COUNT(selected_option) AS selected_answers,
        SUM(CASE WHEN selected_option IS NULL THEN 1 ELSE 0 END) AS skipped_answers
    FROM answers
    GROUP BY session_id
)
SELECT
    s.session_id,
    s.title,
    s.status,
    s.started_at,
    s.ended_at,
    COALESCE(q.question_count, 0) AS question_count,
    COALESCE(a.participant_count, 0) AS participant_count,
    COALESCE(a.submitted_records, 0) AS submitted_records,
    COALESCE(a.selected_answers, 0) AS selected_answers,
    COALESCE(a.skipped_answers, 0) AS skipped_answers,
    COALESCE(a.participant_count, 0) * COALESCE(q.question_count, 0)
        AS possible_records_for_participants,
    COALESCE(a.participant_count, 0) * COALESCE(q.question_count, 0)
        - COALESCE(a.submitted_records, 0) AS unsubmitted_questions,
    ROUND(
        100.0 * COALESCE(a.submitted_records, 0)
        / NULLIF(a.participant_count * q.question_count, 0),
        2
    ) AS submission_progress_percent
FROM sessions AS s
LEFT JOIN question_totals AS q ON q.session_id = s.session_id
LEFT JOIN answer_totals AS a ON a.session_id = s.session_id
ORDER BY s.session_id;

-- Q6. Results for one session. Change the number in settings to select it.
-- Every participant is evaluated against all session questions.
-- For active sessions these are provisional results.
WITH settings AS (
    SELECT 1 AS session_id
), participants AS (
    SELECT DISTINCT a.user_id, a.session_id
    FROM answers AS a
    JOIN settings AS cfg ON cfg.session_id = a.session_id
), results AS (
    SELECT
        p.session_id,
        u.user_id,
        u.username,
        COUNT(*) AS total_questions,
        COUNT(a.question_id) AS submitted_records,
        SUM(CASE WHEN a.selected_option = q.correct_option THEN 1 ELSE 0 END)
            AS correct_answers,
        SUM(CASE WHEN a.selected_option IS NOT NULL
                      AND a.selected_option <> q.correct_option THEN 1 ELSE 0 END)
            AS wrong_answers,
        SUM(CASE WHEN a.question_id IS NOT NULL
                      AND a.selected_option IS NULL THEN 1 ELSE 0 END)
            AS skipped_answers,
        SUM(CASE WHEN a.question_id IS NULL THEN 1 ELSE 0 END)
            AS unanswered_questions
    FROM participants AS p
    JOIN users AS u ON u.user_id = p.user_id
    JOIN session_questions AS sq ON sq.session_id = p.session_id
    JOIN questions AS q ON q.question_id = sq.question_id
    LEFT JOIN answers AS a
        ON a.user_id = p.user_id
       AND a.session_id = sq.session_id
       AND a.question_id = sq.question_id
    GROUP BY p.session_id, u.user_id, u.username
)
SELECT
    r.session_id,
    s.status,
    RANK() OVER (ORDER BY r.correct_answers DESC) AS rank,
    r.user_id,
    r.username,
    r.total_questions,
    r.submitted_records,
    r.correct_answers,
    r.wrong_answers,
    r.skipped_answers,
    r.unanswered_questions,
    r.correct_answers AS score,
    ROUND(100.0 * r.correct_answers / NULLIF(r.total_questions, 0), 2)
        AS score_percent
FROM results AS r
JOIN sessions AS s ON s.session_id = r.session_id
ORDER BY r.correct_answers DESC, r.user_id;

-- Q7. Top 10 users by total points from FINISHED sessions only.
-- Only sessions in which the user participated enter that user's denominator.
-- Ranking uses total points, not percentage, and equal scores share a rank.
-- More participated sessions can produce more total points.
WITH session_sizes AS (
    SELECT session_id, COUNT(*) AS question_count
    FROM session_questions
    GROUP BY session_id
), user_session_scores AS (
    SELECT
        a.user_id,
        a.session_id,
        SUM(CASE WHEN a.selected_option = q.correct_option THEN 1 ELSE 0 END)
            AS score
    FROM answers AS a
    JOIN sessions AS s ON s.session_id = a.session_id
    JOIN questions AS q ON q.question_id = a.question_id
    WHERE s.status = 'finished'
    GROUP BY a.user_id, a.session_id
), totals AS (
    SELECT
        us.user_id,
        COUNT(*) AS finished_sessions_participated,
        SUM(us.score) AS total_score,
        SUM(sz.question_count) AS maximum_possible_score
    FROM user_session_scores AS us
    JOIN session_sizes AS sz ON sz.session_id = us.session_id
    GROUP BY us.user_id
)
SELECT
    RANK() OVER (ORDER BY t.total_score DESC) AS rank,
    u.user_id,
    u.username,
    t.finished_sessions_participated,
    t.total_score,
    t.maximum_possible_score,
    ROUND(100.0 * t.total_score / NULLIF(t.maximum_possible_score, 0), 2)
        AS score_percent
FROM totals AS t
JOIN users AS u ON u.user_id = t.user_id
ORDER BY t.total_score DESC, u.user_id
LIMIT 10;

-- Q8. Inspect one participant's answers in display order, not question-ID order.
-- Change the two values in settings to choose a user and a session.
-- This is an instructor/admin query: it includes the answer key.
-- Do not send the answer key to the browser during an active quiz.
WITH settings AS (
    SELECT 1 AS session_id, 2 AS user_id
)
SELECT
    u.username,
    sq.session_id,
    sq.position AS question_number,
    q.question_id,
    q.topic,
    q.question_text,
    a.selected_option,
    q.correct_option,
    CASE
        WHEN a.question_id IS NULL THEN 'Not submitted'
        WHEN a.selected_option IS NULL THEN 'Skipped'
        WHEN a.selected_option = q.correct_option THEN 'Correct'
        ELSE 'Wrong'
    END AS answer_status,
    a.answered_at
FROM settings AS cfg
JOIN users AS u ON u.user_id = cfg.user_id
JOIN session_questions AS sq ON sq.session_id = cfg.session_id
JOIN questions AS q ON q.question_id = sq.question_id
LEFT JOIN answers AS a
    ON a.user_id = cfg.user_id
   AND a.session_id = sq.session_id
   AND a.question_id = sq.question_id
WHERE EXISTS (
    SELECT 1 FROM answers AS participation
    WHERE participation.user_id = cfg.user_id
      AND participation.session_id = cfg.session_id
)
ORDER BY sq.position;

-- Q9. Foreign key violations: expect no rows.
PRAGMA foreign_key_check;

-- Q10. Structural integrity: expect one row containing 'ok'.
PRAGMA integrity_check;

-- Q11. Current attempt for one learner across all five sessions.
-- Change user_id in settings. User 1 is berna.
WITH settings AS (SELECT 1 AS user_id)
SELECT s.session_id,s.title,s.status,
       COUNT(a.question_id) AS saved,
       SUM(CASE WHEN a.selected_option=q.correct_option THEN 1 ELSE 0 END) AS correct,
       SUM(CASE WHEN a.selected_option IS NOT NULL AND a.selected_option<>q.correct_option THEN 1 ELSE 0 END) AS wrong,
       SUM(CASE WHEN a.question_id IS NOT NULL AND a.selected_option IS NULL THEN 1 ELSE 0 END) AS blank,
       COUNT(*)-COUNT(a.question_id) AS unanswered,
       ROUND(100.0*SUM(CASE WHEN a.selected_option=q.correct_option THEN 1 ELSE 0 END)/COUNT(*),2) AS score_percent
FROM sessions s
JOIN session_questions sq ON sq.session_id=s.session_id
JOIN questions q ON q.question_id=sq.question_id
LEFT JOIN answers a ON a.session_id=sq.session_id AND a.question_id=sq.question_id AND a.user_id=(SELECT user_id FROM settings)
GROUP BY s.session_id
ORDER BY s.session_id;


-- WRITE TEMPLATES (intentionally commented out).
-- Use parameter binding in Python. A colon introduces a named parameter.
-- For the presentation, execute these individually on a disposable demo copy.
-- Commit successful writes and roll back errors.

-- Start a pending session, assigning the actual start time:
-- UPDATE sessions
-- SET status = 'active', started_at = CURRENT_TIMESTAMP
-- WHERE session_id = :session_id AND status = 'pending';

-- Submit one answer. Bind selected_option to A/B/C/D or None for a skip:
-- INSERT INTO answers (user_id, session_id, question_id, selected_option)
-- VALUES (:user_id, :session_id, :question_id, :selected_option);

-- Finish an active session:
-- UPDATE sessions
-- SET status = 'finished', ended_at = CURRENT_TIMESTAMP
-- WHERE session_id = :session_id AND status = 'active';


-- INTEGRITY DEMONSTRATION: expected errors, not normal application queries.
-- All examples below are comments. Run ONE example on a COPY of quiz.db.
-- Remove the leading -- from the chosen example only.
-- The answer examples require an active session.
-- After each expected error, run ROLLBACK TO demo; RELEASE demo; separately.
-- Never save the failed demonstration changes.

-- D1. Missing user: expected FOREIGN KEY constraint failed.
-- SAVEPOINT demo;
-- INSERT INTO answers(user_id,session_id,question_id)
-- SELECT 999999,sq.session_id,sq.question_id
-- FROM session_questions sq JOIN sessions s USING(session_id)
-- WHERE s.status='active' ORDER BY sq.session_id,sq.position LIMIT 1;
-- ROLLBACK TO demo; RELEASE demo;

-- D2. Missing question: expected FOREIGN KEY constraint failed.
-- SAVEPOINT demo;
-- INSERT INTO answers(user_id,session_id,question_id)
-- SELECT 1,session_id,999999 FROM sessions WHERE status='active' ORDER BY session_id LIMIT 1;
-- ROLLBACK TO demo; RELEASE demo;

-- D3. Question outside the selected session: expected FOREIGN KEY failure.
-- SAVEPOINT demo;
-- INSERT INTO answers(user_id,session_id,question_id)
-- SELECT 1,s.session_id,q.question_id FROM sessions s CROSS JOIN questions q
-- WHERE s.status='active' AND NOT EXISTS
-- (SELECT 1 FROM session_questions sq WHERE sq.session_id=s.session_id AND sq.question_id=q.question_id)
-- ORDER BY s.session_id,q.question_id LIMIT 1;
-- ROLLBACK TO demo; RELEASE demo;

-- D4. Repeated answer: expected UNIQUE failure on the second answer insert.
-- SAVEPOINT demo;
-- INSERT INTO users(username) VALUES ('duplicate_demo_user');
-- INSERT INTO answers(user_id,session_id,question_id)
-- SELECT u.user_id,sq.session_id,sq.question_id FROM users u
-- CROSS JOIN session_questions sq JOIN sessions s ON s.session_id=sq.session_id
-- WHERE u.username='duplicate_demo_user' AND s.status='active'
-- ORDER BY sq.session_id,sq.position LIMIT 1;
-- INSERT INTO answers SELECT a.* FROM answers a JOIN users u USING(user_id)
-- WHERE u.username='duplicate_demo_user';
-- ROLLBACK TO demo; RELEASE demo;

-- D5. Invalid calendar date: expected CHECK failure.
-- SAVEPOINT demo;
-- INSERT INTO users(username,created_at) VALUES ('date_demo','2026-02-30 12:00:00');
-- ROLLBACK TO demo; RELEASE demo;

-- D6. Decimal question order: expected CHECK failure.
-- A temporary pending session avoids the protection on started assignments.
-- This temporary session is rolled back; it is not a sixth saved quiz.
-- SAVEPOINT demo;
-- INSERT INTO sessions(session_id,title) VALUES (999999,'Temporary SQL check');
-- INSERT INTO session_questions(session_id,question_id,position)
-- SELECT 999999,question_id,1.5 FROM questions ORDER BY question_id LIMIT 1;
-- ROLLBACK TO demo; RELEASE demo;
