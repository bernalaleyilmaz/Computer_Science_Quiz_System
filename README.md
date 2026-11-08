# CSQuiz

## Türkçe

Bu projede SQLite ile bir quiz sistemi hazırladım. Sorular yapay zekâ, veritabanları ve API konuları hakkında. Arayüz İngilizce ve pembe renklerde.

### Projede neler var?

- Başlangıçta 50 örnek kullanıcı ve toplam 5 oturum var. Yeni hesaplar açıldıkça kullanıcı sayısı artar.
- 150 farklı soru var. Her konudan 50 soru hazırladım.
- Her oturumda 30 soru bulunuyor: 10 yapay zekâ, 10 veritabanı ve 10 API sorusu.
- Her sorunun dört seçeneği ve bir doğru cevabı var.
- İlk altı kullanıcı berna, lale, damla, sude, beyza ve beril. Diğer kullanıcılar da Türk kadın isimleriyle kayıtlı.

### Nasıl çalıştırılır?

Python dışında bir paket kurmaya gerek yok. Proje Python 3.14.2 ve SQLite 3.50.4 ile kontrol edildi. Uygulama için SQLite 3.35 veya üstü kullanılmalı.

1. Klasörü PyCharm ile açıp Python yorumcusunu seç.
2. `app.py` dosyasını çalıştır.
3. Tarayıcıda `http://127.0.0.1:8000` adresini aç.
4. **New here? Create an account** ile takma ad ve en az 8 karakterli bir şifre oluştur. Hesabın varsa **Sign in** kullan.
5. Açık bir oturuma katıl, soruları cevapla veya boş bırak. Quiz bitince sonuç ekranı açılır. Başka bir hesap için önce **Sign out** seç.

Takma ad 3–30 karakter olmalı. Harf, rakam, alt çizgi ve kısa çizgi kullanılabilir; ilk karakter harf veya rakam olmalı. Takma adlar küçük harfe dönüştürülür. 50 örnek profilden biriyle giriş yapmak için mevcut adını (örneğin `berna`) ve ortak gösterim şifresi `12345678` kullan. Önceki cevaplar o profilde kalır. Yeni kişisel hesap için kullanılmayan bir ad ve kendi şifreni seç.

Host düğmesine basınca şifre istenir. Gösterim için şifre `123456789`.

Host bölümünden oturumları başlatabilir, bitirebilir ve yeniden açabilirsin. Kullanıcıların her oturumdaki sonuçları da burada gösterilir. Uygulamayı kapatmak için PyCharm'daki Stop düğmesini kullan.

**Klasördeki `quiz.db` hazırdır. Normal kullanımda `main.py` ve `seed.py` dosyalarını yeniden çalıştırmaya gerek yok.**

Eski bir veritabanı kullanıyorsan `app.py` ilk açılışta `users` tablosuna `password_hash` sütununu ekler. Mevcut kullanıcı ve cevap satırları korunur. Yeni hesapların şifresi düz metin yerine rastgele salt ile üretilen scrypt özeti olarak saklanır. Giriş bilgisi bu tarayıcıda kalır; sunucu yeniden başlatılınca veya giriş süresi dolunca yeniden giriş gerekir.

### Sıfırdan kurulum

Kaynak dosyaları ayrı bir klasöre kopyala. Bu yeni klasörde `quiz.db` bulunmasın. Mevcut cevapları korumak istiyorsan kullandığın veritabanını silme.

```text
python main.py
python seed.py
python app.py
```

Yeni kurulum 50 kullanıcı, 5 oturum, 150 soru ve 75 örnek cevap oluşturur. İlk oturum bitmiş, ikinci oturum açık, diğer üç oturum başlamamış olur. 75 sabit bir sınır değildir; kullanıcılar cevap verdikçe kayıt sayısı değişir. `seed.py`, dolu bir veritabanını sıfırlamaz ve yeniden veri eklemeyi reddeder.

### Dosyalar

| Dosya | Ne için kullanılıyor? |
| --- | --- |
| `schema.sql` | Tabloları, kısıtları, indeksleri ve trigger'ları oluşturur. |
| `main.py` | Yeni veritabanına şemayı uygular. |
| `seed.py` | İlk kullanıcıları, oturumları, soruları ve örnek cevapları ekler. |
| `questions.json` | 150 soruyu ve doğru cevaplarını tutar. |
| `queries.sql` | Sayım, ilerleme, sonuç, sıralama ve kontrol sorgularını içerir. |
| `quiz.db` | Kullanılan SQLite veritabanıdır. |
| `app.py` | Arayüzün yerel sunucusunu çalıştırır. |
| `web/` | HTML, CSS ve JavaScript dosyalarını içerir. |
| `ER_DIAGRAM.svg` | Tabloların ilişkilerini gösteren diyagramdır. |
| `ER_DIAGRAM.md` | Diyagramın düzenlenebilir metin kaynağıdır. |

### Neden beş tablo kullandım?

`users` kullanıcıları, `sessions` oturumları, `questions` soruları tutar. `session_questions`, hangi sorunun hangi oturumda ve hangi sırada olduğunu gösterir. `answers` ise kullanıcının verdiği cevabı ve cevap zamanını saklar.

Bir oturumda birden fazla soru olabilir. Aynı soru da farklı oturumlara atanabilir. Bu yüzden `session_questions` tablosu gereklidir. Soruların seçenek sayısı sabit olduğu için seçenekleri ayrı bir tabloya koymadım. Puanlar cevaplardan hesaplandığı için sonuç tablosu da eklemedim.

`answers` tablosunun anahtarı `(user_id, session_id, question_id)` şeklindedir. Böylece aynı denemede aynı soruya ikinci cevap kaydedilemez. Bu tablodaki `(session_id, question_id)` alanları birlikte `session_questions` tablosuna bağlanır. Kullanıcı, oturumda bulunmayan bir soruya cevap veremez.

### Puan ve tekrar çözme

Doğru cevap 1 puan, yanlış veya boş cevap 0 puandır. Yanlış cevap doğruyu götürmez. Başarı yüzdesi, doğru sayısının 30'a bölünüp 100 ile çarpılmasıyla hesaplanır.

`selected_option` alanının `NULL` olması, sorunun boş bırakıldığını gösterir. Cevap satırı hiç yoksa henüz cevap gönderilmemiştir. Kullanıcı quizi erken bitirirse kalan sorular boş olarak kaydedilir. Kullanıcının bitirmesi ortak oturumu kapatmaz.

Bir kullanıcı tekrar çözmek istediğinde yalnızca kendi o oturumdaki eski cevapları silinir. Son yaptığı denemenin puanı geçerli olur. Diğer kullanıcıların cevapları değişmez. Host aynı oturumu yeniden açar; yeni bir oturum eklenmez. Oturumu yeniden açmak tek başına eski cevapları silmez.

Genel sıralamada yalnızca bitmiş ortak oturumlar sayılır. Eşit puan alanlar aynı sırayı paylaşır. Açık oturumların sonuçları Host bölümünde ayrıca görülebilir.

### Oturum durumu ve ilerleme

Durumlar `pending` (başlamadı), `active` (açık) ve `finished` (bitti) olarak tutulur. Başlamamış oturumun başlangıç ve bitiş zamanı yoktur. Açık oturumun başlangıcı vardır, bitişi yoktur. Bitmiş oturumun ikisi de vardır; bitiş başlangıçtan önce olamaz. Yeniden açıldığında ilk başlangıç korunur, bitiş temizlenir.

Tarihler UTC olarak `YYYY-MM-DD HH:MM:SS` biçiminde saklanır. Soru sırası pozitif tam sayı olmalıdır. Oturum başladıktan sonra soru metni, doğru cevap ve soru listesi değiştirilemez.

İlerleme, kaydedilen cevap sayısının `(en az bir cevap gönderen kullanıcı sayısı × 30)` değerine bölünmesiyle hesaplanır. Bu, herkesin aynı soruda olduğunu göstermez. Toplam 5 oturum ve oturum başına 30 soru, kurulum ve uygulama kontrolleriyle sağlanır; veritabanındaki tablo tanımı tek başına bu kayıt sayılarını zorunlu tutmaz.

### DB Browser'da kontrol

1. `app.py` dosyasını durdur ve DB Browser for SQLite ile `quiz.db` dosyasını aç.
2. Execute SQL bölümünde `PRAGMA foreign_keys = ON;` çalıştır. `PRAGMA foreign_keys;` sonucu 1 olmalı.
3. `queries.sql` içindeki sorguları tek tek çalıştır. Kullanıcı ve soru sayılarını, ilerlemeyi ve sonuçları görebilirsin.
4. Q11 sorgusundaki kullanıcı numarasını değiştirerek bir kullanıcının beş oturumdaki mevcut denemesini görebilirsin.
5. `PRAGMA foreign_key_check;` satır döndürmemeli. `PRAGMA integrity_check;` sonucu `ok` olmalı.

Dosyanın sonundaki D1–D6 örnekleri, hatalı kayıtların reddedildiğini göstermek içindir. Normal sorgularla birlikte çalışmasın diye yorum olarak bırakıldı. Gösterim için veritabanının bir kopyasını kullan. Seçtiğin örneğin başındaki `--` işaretlerini kaldırıp örneği tek başına çalıştır. Cevap örnekleri için açık bir oturum bulunmalı. Beklenen hata geldikten sonra `ROLLBACK TO demo; RELEASE demo;` komutlarını ayrıca çalıştır.

Olmayan kullanıcı, olmayan soru, oturum dışındaki soru, tekrar cevap, geçersiz tarih ve ondalıklı soru sırası örnekleri var. Bu kontroller için ayrı bir SQL dosyasına gerek yok.

Genel sıralama boşsa cevap içeren oturumların bitmiş olup olmadığını kontrol et. Aktif oturumlar genel sıralamaya dahil edilmez.

### Uygulamayla ilgili notlar

Bu uygulama yerel ders gösterimi için hazırlandı. 15 dakikalık sayaç tarayıcıda tutulur; sunucunun zorunlu tuttuğu bir sınav süresi değildir. Sayfa yenilendiğinde ekran seçimi geri yüklenir, kaydedilmiş cevaplar veritabanından okunur. Görünür canlı paneller 15 saniyede bir güncellenir. Planlanan oturumun açılması için saati geldikten sonra sunucuya bir istek gelmesi gerekir.

## English

I made this quiz project with SQLite. The questions cover AI, databases and APIs. The interface is in English and uses a pink theme.

### What is included?

The starting data has 50 sample users, 5 sessions and 150 different questions. The user count grows as new accounts are created. Each topic has 50 questions. Each session has 30 questions: 10 from each topic. Every question has four choices and one correct answer.

The first six users are berna, lale, damla, sude, beyza and beril. The other profiles also use Turkish female names. Answers are linked to user IDs, not names.

### Running the project

No extra Python packages are needed. The project was checked with Python 3.14.2 and SQLite 3.50.4. Use SQLite 3.35 or later.

1. Open the folder in PyCharm and select a Python interpreter.
2. Run `app.py`.
3. Open `http://127.0.0.1:8000` in a browser.
4. Use **New here? Create an account** to choose a nickname and a password with at least eight characters. Use **Sign in** if you already have an account.
5. Join an active session and answer or skip the questions. Finish to see your result. Use **Sign out** to switch accounts.

Nicknames are 3–30 characters, start with a letter or number and can include letters, numbers, underscores and hyphens. Nicknames are converted to lowercase. To sign in to any of the 50 sample profiles, use its existing nickname (for example `berna`) and the shared demo password `12345678`. Its saved answers are kept. Choose an unused nickname and your own password for a new personal account.

Click Host and enter `123456789` to open the panel.

The Host panel starts, finishes and reopens sessions. It also shows each user's results for the selected session. Use PyCharm's Stop button to stop the server.

**The included `quiz.db` is ready to use. Do not run the setup scripts again for normal use.**

When opening an older database, `app.py` adds `password_hash` to `users` without replacing existing users or answers. Passwords are stored as salted scrypt hashes. The browser stays signed in across refreshes; a server restart or login expiry requires signing in again.

### Fresh setup

Copy the source files to a separate folder without a `quiz.db` file. Keep your existing database if you want to keep its saved answers.

```text
python main.py
python seed.py
python app.py
```

This creates 50 users, 5 sessions, 150 questions and 75 sample answer records. Session 1 is finished, session 2 is active, and the other three are pending. The answer count changes as users answer questions. `seed.py` refuses to overwrite a populated database.

### Files and tables

`schema.sql` defines the tables and rules. `main.py` applies the schema, and `seed.py` adds the starting data from `questions.json`. `queries.sql` contains the count, progress, result, ranking and integrity queries. `quiz.db` stores the data. `app.py` serves the interface, and `web/` contains its HTML, CSS and JavaScript. `ER_DIAGRAM.svg` shows the table relationships; `ER_DIAGRAM.md` is its editable source.

I used five tables:

- `users`: names, registration times and password hashes for accounts that can sign in.
- `sessions`: quiz titles, states and times.
- `questions`: question text, choices and correct answers.
- `session_questions`: questions assigned to each session and their order.
- `answers`: each user's submitted choices and answer times.

A session can contain many questions, and a question can be used in different sessions. The `session_questions` table connects them. Four fixed choices are stored as columns. Scores are calculated from answers, so there is no separate results table.

The primary key of `answers` is `(user_id, session_id, question_id)`. It prevents repeated submissions within the same attempt. Its composite foreign key `(session_id, question_id)` references `session_questions`, so a user cannot answer a question outside the selected session.

### Scoring and retakes

A correct answer gives 1 point. A wrong or blank answer gives 0. Wrong answers do not subtract points. The percentage is `correct / 30 × 100`.

`selected_option=NULL` means a submitted blank answer. A missing answer row means the question has not been submitted. Finishing early saves missing questions as blanks. A learner finishing does not close the shared session.

Retaking deletes only that user's previous answers in the selected session. Only the current attempt counts, and other users' answers stay unchanged. The Host reopens the same session instead of creating another one. Reopening alone does not delete answers.

The overall ranking includes finished shared sessions only. Equal scores share a rank. The Host panel also shows results for active sessions.

### States and progress

The states are `pending`, `active` and `finished`. Pending sessions have no start or end time. Active sessions have a start but no end. Finished sessions have both, and the end cannot be earlier than the start. Reopening keeps the original start and clears the end.

Dates are stored in UTC as `YYYY-MM-DD HH:MM:SS`. Question positions must be positive integers. Questions and their assignments are protected after a session starts. Five sessions and 30 questions per session are checked by setup and application code; the table definitions alone do not enforce those row counts.

Shared progress is `saved answer records / (users with at least one submission × 30)`. It measures submitted answers, not a shared current question number.

### Checking with DB Browser

Stop the app and open `quiz.db` in DB Browser for SQLite. Run `PRAGMA foreign_keys=ON;` in Execute SQL and check that `PRAGMA foreign_keys;` returns 1. Run the queries in `queries.sql` separately. Q11 shows one user's current attempts across all sessions; change the user ID in its settings.

`PRAGMA foreign_key_check;` should return no rows. `PRAGMA integrity_check;` should return `ok`.

The commented D1–D6 examples at the end demonstrate missing users, missing questions, questions outside a session, repeated answers, invalid dates and decimal question positions. Use a copy of the database. Uncomment and run one example at a time. The answer examples need an active session. After the expected error, run `ROLLBACK TO demo; RELEASE demo;` separately to undo the example.

If the overall ranking is empty, check whether any session with answers has been finished. Active sessions do not count in that ranking.

### Notes

This is a local classroom demo. The 15-minute timer runs in the browser and is not a server-enforced exam deadline. Refresh restores the selected screen, while saved answers are read from SQLite. Visible live panels refresh every 15 seconds. A scheduled session starts when an API request arrives after its planned start time.


## Testleri çalıştırma / Running the tests

PyCharm'da `test_project.py` dosyasını çalıştırabilirsin. Terminalden de:

```text
python -m unittest -v test_project
```

Dosyada 11 test var. Kurulum, veri kuralları, oturum yönetimi, yeniden çözme,
SQL sorguları, hesap geçişi ve giriş yetkileri kontrol edilir. Testler geçici
veritabanları oluşturur; kullanılan `quiz.db` dosyasını
değiştirmez. Yedekteki yükseltme betiğine veya ek kontrol dosyasına ihtiyaç yoktur.

Run `test_project.py` in PyCharm or use the command above. The 11 tests check
setup, data constraints, session rules, retakes, SQL queries, account migration
and sign-in permissions. They use temporary databases and do not change
the working `quiz.db`. No archived migration or extra query file is needed.

## Kayıt sayılarını doğrulama / Checking record counts

DB Browser içinde aşağıdaki sorgu kullanıcı, oturum, soru, soru ataması ve cevap sayılarını gösterir. Kullanıcı sayısı başlangıçta 50'dir ve yeni kayıtlarla artar. Oturum, soru ve atama sayıları 5, 150 ve 150'dir. Cevap sayısı kullanıma göre değişir.

Run this query in DB Browser to check the stored counts. Users start at 50 and increase with registrations. Sessions, questions and assignments are 5, 150 and 150. The answer count changes during use.

```sql
SELECT 'users' AS table_name, COUNT(*) AS record_count FROM users
UNION ALL SELECT 'sessions', COUNT(*) FROM sessions
UNION ALL SELECT 'questions', COUNT(*) FROM questions
UNION ALL SELECT 'session_questions', COUNT(*) FROM session_questions
UNION ALL SELECT 'answers', COUNT(*) FROM answers;

SELECT COUNT(DISTINCT question_id) AS distinct_assigned_questions
FROM session_questions;
```

İkinci sorgunun sonucu 150 olmalıdır; aynı sorunun tekrar atanması bu sayıyı artırmaz.
The second query should return 150; assigning the same question again does not increase this count.


### Oturumu erteleme / Postponing a session

Host bölümünde, hiç cevap kaydı olmayan açık veya bitmiş oturumlar için tarih
seçip **Postpone session** düğmesine basabilirsiniz. Tarih gelecekte olmalıdır.
Oturum `pending` olur; eski başlangıç ve bitiş zamanları temizlenir. Cevap içeren
oturumlar ertelenemez ve cevaplar silinmez. Tarih alanı yerel saatinizle çalışır;
veritabanına UTC kaydedilir. Uygulama açıkken planlanan saatten sonra gelen ilk
API isteği oturumu başlatır. Güncellemeden sonra uygulamayı yeniden başlatın;
mevcut veritabanının trigger kuralları otomatik güncellenir.

Hosts can postpone active or finished sessions with no saved answers by choosing
 a future local date and clicking Postpone session. This returns the session to
pending and clears its previous start/end timestamps without deleting answers.
Sessions containing answers cannot be postponed. The first API request at or
after the scheduled time starts the session. Restart the application after updating.
