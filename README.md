# Market WhatsApp Bot

RSS feeds → Claude מסנן → Claude מנסח → WhatsApp

## התקנה

```bash
cd market-whatsapp
pip install -r requirements.txt
cp .env.example .env
# ← ערוך .env עם המפתחות שלך
```

## הגדרת WhatsApp

### אופציה A — Twilio
1. צור חשבון ב-twilio.com
2. הפעל WhatsApp Sandbox: `console.twilio.com → Messaging → WhatsApp`
3. מלא `TWILIO_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`

### אופציה B — Green API (מומלץ לקבוצות)
1. צור חשבון ב-green-api.com
2. חבר את מספר הטלפון
3. מלא `GREEN_API_INSTANCE`, `GREEN_API_TOKEN`
4. לקבוצה: `WHATSAPP_TO=972501234567-1234567890@g.us`

## שימוש

```bash
python main.py                      # preview + confirm
python main.py --auto               # שלח בלי לשאול
python main.py --dry-run            # preview בלבד
python main.py --morning-digest     # סיכום בוקר
python main.py --provider green     # Green API
python main.py --skip-humanizer     # בלי כתיבה בסגנון שלי
python main.py --ab                 # לפני/אחרי humanizer
```

## Humanizer (אופציונלי)

אם קיים `../style-extractor/style_profile.json`, ההודעות יעברו שכתוב בסגנון שלך.
צור אותו עם: `cd ../style-extractor && python main.py all`

## לוגיקת סינון

כתבה עוברת אם עונה על **לפחות 2 מתוך 15 קריטריונים**:
- השפעה מוחשית על המציאות
- גיבוי בנתוני מאקרו
- שיבוש תעשיות
- טריגר רגולטורי
- ... (ראה classifier.py לרשימה המלאה)

רק כתבות עם `דירוג ≥ MIN_IMPORTANCE_SCORE` (ברירת מחדל: 6) נשלחות.

## קבצים

| קובץ | תפקיד |
|------|--------|
| `feeds.py` | משיכת RSS feeds במקביל |
| `classifier.py` | סינון עם Claude (15 קריטריונים) |
| `composer.py` | ניסוח הודעות WhatsApp |
| `humanizer.py` | שכתוב בסגנון אישי |
| `whatsapp_twilio.py` | שליחה דרך Twilio |
| `whatsapp_green.py` | שליחה דרך Green API |
| `sent_log.json` | לוג הודעות שנשלחו (dedup) |

## Email digest pool (בריף בוקר במייל)

צינור נפרד לגמרי מהוואטסאפ, שמייצר `email_digest.json` פעם ביום — קובץ שמשמש כמקור נתונים לבריף בוקר שנשלח במייל (ניסוח ושליחה קורים מחוץ לריפו הזה).

```bash
python main.py --collect-email-pool
```

מה זה עושה:
1. מושך חדשות עולם מ-`WORLD_RSS_FEEDS` (config.py) ומסנן אותן עם `email_classifier.py` — קריטריון של משמעות גלובלית/גיאופוליטית, **לא** קשור לקריטריונים הכלכליים של `classifier.py`.
2. שולף כתבות עסקים/טכנולוגיה שכבר אושרו לוואטסאפ ב-`sent_log.json` ב-24 השעות האחרונות (ברירת מחדל) — בלי קריאות נוספות ל-Claude.
3. כותב הכל ל-`email_digest.json`, מחולק ל-`world` / `business` / `tech`.

Workflow נפרד (`email-digest-pool.yml`) מריץ את זה פעם ביום. הוא לא נוגע ב-`sent_log.json`, לא שולח וואטסאפ, ולא יכול להשפיע על ה-workflow הקיים (`market-news.yml`) — concurrency group נפרד לגמרי.

| קובץ נוסף | תפקיד |
|------|--------|
| `email_classifier.py` | סינון חדשות עולם לבריף המייל (Claude, קריטריון גיאופוליטי) |
| `email_digest.json` | פלט — נקרא ע"י `send_morning_brief.py` |

## שליחת בריף הבוקר — קבוצת WhatsApp

`send_morning_brief.py` קורא את `email_digest.json`, מושך תמונת מצב שוקים חיה (S&P/Nasdaq/Dow/VIX/10Y/DXY/USD-ILS דרך Yahoo Finance), מנסח הודעת WhatsApp (עם עיצוב WhatsApp טבעי — *מודגש*, לא HTML) עם Claude, ושולח לקבוצת "בריף בוקר" דרך אותו נתיב שליחה שהבוט הראשי כבר משתמש בו (Green API / Twilio).

```bash
python send_morning_brief.py --dry-run   # ניסוח בלבד, בלי שליחה
python send_morning_brief.py             # preview + אישור ידני
python send_morning_brief.py --auto      # שליחה בלי לשאול
```

**הגדרה:** צרו קבוצת WhatsApp ל-"בריף בוקר", הוסיפו אליה את המספר שהבוט שולח ממנו, ומלאו ב-`.env` את `MORNING_BRIEF_TO` עם ה-chat ID שלה (פורמט קבוצה ב-Green API: `1234567890-1234567890@g.us` — ראו "הגדרת WhatsApp" למעלה). בלי `MORNING_BRIEF_TO` זה נופל חזרה ל-`WHATSAPP_TO` הרגיל.

ה-workflow `send-morning-brief.yml` רץ אוטומטית כל יום ב-08:34 שעון ישראל (כ-2.5 שעות אחרי ה-06:00 של Email Digest Pool, כדי ש-`email_digest.json` יהיה טרי) — וגם ניתן להפעלה ידנית מטאב ה-Actions. דורש GitHub Secret נוסף: `MORNING_BRIEF_TO` (ליד `ANTHROPIC_API_KEY`/`GREEN_API_INSTANCE`/`GREEN_API_TOKEN` שכבר קיימים).

| קובץ נוסף | תפקיד |
|------|--------|
| `market_data.py` | תמונת מצב שוקים חיה (Yahoo Finance, בלי מפתח API) |
| `morning_brief_composer.py` | ניסוח הודעת ה-WhatsApp של הבריף (Claude, נפרד מ-`composer.py`) |
| `send_morning_brief.py` | ה-CLI שמחבר הכל: digest → שוק → Claude → WhatsApp |

### מסלול שננטש: מייל דרך רב מסר (Responder)

`responder_client.py` / `responder_v2_client.py` / `newsletter_composer.py` / `send_newsletter.py` / `.github/workflows/send-newsletter.yml` נשארו בריפו אבל **לא בשימוש** — נבנו לפני שהתברר ש-API V1 של רב מסר (היחיד שיודע לשלוח הודעות) עומד להתבטל, ו-V2.0 (החדש) לא כולל בכלל endpoint לשליחת הודעות (רק ניהול רשימות/נרשמים — אומת מול ה-Swagger הרשמי שלהם). הוחלט לעבור לקבוצת WhatsApp במקום. `responder_v2_client.py` עדיין תקף אם ירצו בעתיד לנהל נרשמים/תגיות ברב מסר.
