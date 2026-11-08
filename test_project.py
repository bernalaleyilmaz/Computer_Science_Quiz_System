"""Reproducible integrity and workflow tests; only temporary databases are written.

Run: python -m unittest -v test_project
No migration script or separate check_queries.sql is required.
"""
from contextlib import closing
from http.client import HTTPResponse
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

BASE = Path(__file__).resolve().parent
TABLES = ('users', 'sessions', 'questions', 'session_questions', 'answers')


def snapshot(connection):
    return {table: connection.execute(f'SELECT * FROM {table} ORDER BY 1,2,3').fetchall()
            for table in TABLES}


def execute_statements(connection, script):
    statement = ''
    for line in script.splitlines():
        statement += line + '\n'
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ''



def module(name):
    spec = importlib.util.spec_from_file_location(name, BASE / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class ProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        for name in ('schema.sql', 'main.py', 'seed.py', 'questions.json'):
            shutil.copy2(BASE / name, cls.directory / name)
        for script in ('main.py', 'seed.py'):
            result = subprocess.run([sys.executable, str(cls.directory / script)],
                                    capture_output=True, text=True)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
        cls.seed_db = cls.directory / 'quiz.db'
        cls.app = module('app')

    def setUp(self):
        self.database = self.directory / (self._testMethodName + '.db')
        shutil.copy2(self.seed_db, self.database)
        self.app.DATABASE_PATH = self.database
        self.db = sqlite3.connect(self.database)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.q = self.db.execute('SELECT question_id FROM session_questions WHERE session_id=2 ORDER BY position LIMIT 1').fetchone()[0]

    def tearDown(self):
        self.db.close()

    def reject(self, sql, parameters=()):
        self.db.execute('SAVEPOINT invalid_record')
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql, parameters)
        finally:
            self.db.execute('ROLLBACK TO invalid_record')
            self.db.execute('RELEASE invalid_record')

    def test_account_column_preserves_sample_data(self):
        self.db.execute('ALTER TABLE users DROP COLUMN password_hash')
        self.db.commit()
        old_users = self.db.execute('SELECT * FROM users ORDER BY user_id').fetchall()
        old_answers = self.db.execute('SELECT * FROM answers ORDER BY 1,2,3').fetchall()
        self.app.upgrade_schema()
        self.app.upgrade_schema()
        self.assertEqual(self.db.execute('SELECT * FROM users ORDER BY user_id').fetchall(),
                         [(*user, None) for user in old_users])
        self.assertEqual(self.db.execute('SELECT * FROM answers ORDER BY 1,2,3').fetchall(), old_answers)
        self.assertFalse(self.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_learner_accounts_and_quiz_permissions(self):
        class QuietHandler(self.app.Handler):
            def log_message(self, *args):
                pass

        def request(path, data=None, cookie=None, host=None):
            # Exercise the real HTTP handler and response headers in memory.
            payload = b'' if data is None else json.dumps(data).encode('utf-8')
            verb = 'GET' if data is None else 'POST'
            headers = {'Host': '127.0.0.1:8000', 'Content-Type': 'application/json',
                       'Content-Length': str(len(payload))}
            if cookie:
                headers['Cookie'] = cookie
            if host:
                headers['X-CSQuiz-Host'] = host
            raw = f'{verb} {path} HTTP/1.0\r\n' + ''.join(f'{name}: {value}\r\n' for name, value in headers.items())
            request_file = BytesIO(raw.encode('ascii') + b'\r\n' + payload)
            response_file = BytesIO()
            socket = SimpleNamespace(makefile=lambda *args: request_file, sendall=response_file.write)
            QuietHandler(socket, ('127.0.0.1', 0), SimpleNamespace(server_port=8000))
            response_file.seek(0)
            with closing(HTTPResponse(SimpleNamespace(makefile=lambda *args: response_file))) as response:
                response.begin()
                return response.status, json.load(response), response.getheader('Set-Cookie', '')

        sample = {'nickname': 'berna', 'password': 'Sample-pass-1'}
        credentials = {'nickname': 'Kitap_Kurdu', 'password': 'Sample-pass-1'}
        answer = {'session_id': 2, 'question_id': self.q, 'selected_option': 'A'}
        self.assertEqual(request('/api/overview')[0], 401)
        self.assertEqual(request('/api/session?session_id=2')[0], 401)
        self.assertEqual(request('/api/answers', answer)[0], 401)
        self.assertEqual(request('/api/account/login', sample)[0], 401)
        self.assertEqual(request('/api/account/register', sample)[0], 409)
        status, sample_result, _ = request('/api/account/login', {**sample, 'password': '12345678'})
        self.assertEqual((status, sample_result['user']), (200, {'user_id': 1, 'username': 'berna'}))
        hashes = self.db.execute('SELECT password_hash FROM users').fetchall()
        self.assertEqual(len(set(hashes)), 50)
        self.assertTrue(all(value and value.startswith('scrypt-v1$') for (value,) in hashes))
        self.assertEqual(request('/api/account/register', {**credentials, 'password': 'short'})[0], 400)
        status, result, cookie = request('/api/account/register', credentials)
        self.assertEqual(status, 201)
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Strict', cookie)
        cookie = cookie.split(';')[0]
        user = result['user']
        user_id = user['user_id']
        self.assertEqual(user['username'], 'kitap_kurdu')
        self.assertEqual(request('/api/account/me', cookie=cookie)[1], {'user': user})
        self.assertEqual(request('/api/account/register', {**credentials, 'nickname': 'kitap_kurdu'})[0], 409)
        self.assertEqual(request('/api/account/login', {**credentials, 'password': 'wrong-password'})[0], 401)
        self.assertEqual(request('/api/session?session_id=2&user_id=1', cookie=cookie)[0], 403)
        self.assertEqual(request('/api/profile?user_id=1', cookie=cookie)[0], 403)
        self.assertEqual(request('/api/answers', {**answer, 'user_id': 1}, cookie)[0], 403)
        self.assertEqual(request('/api/attempts/restart', {'session_id': 1, 'user_id': 1}, cookie)[0], 403)
        self.assertEqual(request('/api/answers', answer, cookie)[0], 200)
        self.assertEqual(request('/api/attempts/finish', {'session_id': 2}, cookie)[0], 200)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM answers WHERE user_id=?', (user_id,)).fetchone()[0], 30)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM answers WHERE user_id=1').fetchone()[0], 30)
        stored = self.db.execute('SELECT password_hash FROM users WHERE user_id=?', (user_id,)).fetchone()[0]
        self.assertTrue(stored.startswith('scrypt-v1$'))
        self.assertNotIn(credentials['password'], stored)
        self.assertEqual(request('/api/sessions/finish', {'session_id': 2}, cookie)[0], 401)
        host = request('/api/host/login', {'password': self.app.HOST_PASSWORD})[1]['token']
        self.assertEqual(request('/api/host-results?session_id=2', host=host)[0], 200)
        self.assertEqual(request('/api/account/logout', {}, cookie)[0], 200)
        self.assertEqual(request('/api/account/me', cookie=cookie)[1], {'user': None})
        self.assertEqual(request('/api/session?session_id=2', cookie=cookie)[0], 401)
        status, result, new_cookie = request('/api/account/login', credentials)
        self.assertEqual((status, result['user']), (200, user))
        self.assertNotEqual(new_cookie.split(';')[0], cookie)
        self.assertTrue(request('/api/session?session_id=2', cookie=new_cookie.split(';')[0])[1]['completed'])

    def test_counts_and_integrity(self):
        for table, count in zip(TABLES, (50, 5, 150, 150, 75)):
            self.assertEqual(self.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], count)
        self.assertEqual(self.db.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(), [])
        with closing(self.app.connect_database()) as connection:
            self.assertEqual(connection.execute('PRAGMA foreign_keys').fetchone()[0], 1)

    def test_invalid_dates_and_calendar(self):
        for value in ('not-a-date', '2026-02-30 12:00:00', '2026-13-01 00:00:00',
                      '2026-01-01 24:00:00', '2026-01-01', '2026-01-01T12:00:00', ''):
            with self.subTest(value=value):
                self.reject('INSERT INTO users(username,created_at) VALUES (?,?)', ('date_test', value))
                self.reject("UPDATE sessions SET status='active',started_at=? WHERE session_id=3", (value,))
                self.reject("UPDATE sessions SET status='finished',ended_at=? WHERE session_id=2", (value,))
                self.reject('UPDATE sessions SET scheduled_start_at=? WHERE session_id=3', (value,))
                self.reject('INSERT INTO answers VALUES (50,2,?,NULL,?)', (self.q, value))
        # Valid leap-day and default CURRENT_TIMESTAMP must still work.
        self.db.execute("INSERT INTO users(username,created_at) VALUES ('valid_date','2024-02-29 23:59:59')")

    def test_position_requires_positive_integer(self):
        for value in (1.5, 0, -1, 'word', None):
            with self.subTest(value=value):
                self.reject('UPDATE session_questions SET position=? WHERE session_id=3 AND position=1', (value,))
        self.db.execute('UPDATE session_questions SET position=31 WHERE session_id=3 AND position=1')

    def test_foreign_keys_duplicates_and_options(self):
        self.reject('INSERT INTO answers(user_id,session_id,question_id) VALUES (9999,2,?)', (self.q,))
        self.reject('INSERT INTO answers(user_id,session_id,question_id) VALUES (50,2,9999)')
        outside = self.db.execute('SELECT question_id FROM session_questions WHERE session_id=3 LIMIT 1').fetchone()[0]
        self.reject('INSERT INTO answers(user_id,session_id,question_id) VALUES (50,2,?)', (outside,))
        self.reject("INSERT INTO answers(user_id,session_id,question_id,selected_option) VALUES (50,2,?,'E')", (self.q,))
        self.db.execute('INSERT INTO answers(user_id,session_id,question_id) VALUES (50,2,?)', (self.q,))
        self.reject('INSERT INTO answers(user_id,session_id,question_id) VALUES (50,2,?)', (self.q,))
        self.reject("UPDATE answers SET selected_option='A' WHERE user_id=50 AND session_id=2")
        self.reject("INSERT INTO users(username) VALUES ('berna')")
        self.reject('INSERT INTO users(username) VALUES (NULL)')

    def test_lifecycle_and_protected_questions(self):
        closed_q = self.db.execute('SELECT question_id FROM session_questions WHERE session_id=1 LIMIT 1').fetchone()[0]
        self.reject('INSERT INTO answers(user_id,session_id,question_id) VALUES (50,1,?)', (closed_q,))
        self.reject("UPDATE sessions SET status='pending',started_at=NULL WHERE session_id=2")
        self.reject("UPDATE sessions SET started_at='2026-01-01 00:00:00' WHERE session_id=2")
        self.reject("UPDATE questions SET correct_option='A' WHERE question_id=?", (self.q,))
        self.reject('DELETE FROM session_questions WHERE session_id=2 AND question_id=?', (self.q,))

    def test_retake_and_host_reopen(self):
        self.app.upgrade_schema()
        self.app.post_data('/api/answers', {'user_id': 1, 'session_id': 2, 'question_id': self.q, 'selected_option': 'A'})
        before = snapshot(self.db)['answers']
        other = [row for row in before if not (row[0] == 1 and row[1] == 2)]
        self.app.post_data('/api/attempts/restart', {'user_id': 1, 'session_id': 2})
        remaining = snapshot(self.db)['answers']
        self.assertEqual(other, remaining)
        correct = self.db.execute('SELECT correct_option FROM questions WHERE question_id=?', (self.q,)).fetchone()[0]
        self.app.post_data('/api/answers', {'user_id': 1, 'session_id': 2, 'question_id': self.q, 'selected_option': correct})
        self.app.post_data('/api/attempts/finish', {'user_id': 1, 'session_id': 2})
        result = self.app.get_data('/api/host-results', {'session_id': ['2']})
        learner = next(row for row in result['results'] if row['user_id'] == 1)
        self.assertEqual((learner['correct'], learner['blank'], learner['unanswered']), (1, 29, 0))
        self.app.post_data('/api/sessions/finish', {'session_id': 2})
        self.app.post_data('/api/sessions/start', {'session_id': 2})
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0], 5)
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_postpone_empty_sessions(self):
        from datetime import datetime, timedelta, timezone
        future = (datetime.now(timezone.utc) + timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')
        self.app.upgrade_schema()
        # Both active and finished empty sessions can return to pending.
        for finished in (False, True):
            self.app.post_data('/api/sessions/start', {'session_id': 3})
            if finished:
                self.app.post_data('/api/sessions/finish', {'session_id': 3})
            before = snapshot(self.db)['answers']
            self.app.post_data('/api/sessions/schedule', {'session_id': 3, 'scheduled_start_at': future})
            self.assertEqual(self.db.execute('SELECT status,started_at,ended_at,scheduled_start_at FROM sessions WHERE session_id=3').fetchone(), ('pending', None, None, future))
            self.assertEqual(snapshot(self.db)['answers'], before)
        self.app.post_data('/api/sessions/start', {'session_id': 3})
        for value in (None, '2000-01-01 00:00:00', 'bad date'):
            with self.assertRaises(self.app.APIError):
                self.app.post_data('/api/sessions/schedule', {'session_id': 3, 'scheduled_start_at': value})
        before = snapshot(self.db)
        with self.assertRaises(self.app.APIError):
            self.app.post_data('/api/sessions/schedule', {'session_id': 1, 'scheduled_start_at': future})
        self.reject("UPDATE sessions SET status='pending',started_at=NULL,ended_at=NULL,scheduled_start_at=? WHERE session_id=1", (future,))
        self.assertEqual(snapshot(self.db), before)

    def test_queries(self):
        before = snapshot(self.db)
        for name in ('queries.sql',):
            execute_statements(self.db, (BASE / name).read_text(encoding='utf-8-sig'))
        self.assertEqual(snapshot(self.db), before)

    def test_reseed_does_not_replace_data(self):
        before = snapshot(self.db)
        result = subprocess.run([sys.executable, str(self.directory / 'seed.py')], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already contains data', result.stderr)
        self.assertEqual(before, snapshot(self.db))


if __name__ == '__main__':
    unittest.main(verbosity=2)
