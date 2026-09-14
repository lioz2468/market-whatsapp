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
| `email_digest.json` | פלט — נקרא ע"י `send_newsletter.py` |

## שליחת הניוזלטר (רב מסר / Responder)

`send_newsletter.py` קורא את `email_digest.json`, מושך תמונת מצב שוקים חיה (S&P/Nasdaq/Dow/VIX/10Y/DXY/USD-ILS דרך Yahoo Finance), מנסח את גוף ה-HTML המלא עם Claude, ושולח דרך ה-API של רב מסר (`responder_client.py`).

```bash
python send_newsletter.py --list-lists   # פעם ראשונה: מוצא את RESPONDER_LIST_ID
python send_newsletter.py --dry-run      # ניסוח בלבד, בלי קריאות לרב מסר
python send_newsletter.py                # ניסוח + יצירת הודעה + שליחת TEST בלבד (ברירת מחדל, בטוח)
python send_newsletter.py --send-live    # אחרי שאימתת את ה-TEST: שליחה בפועל לרשימה
```

**בטיחות כברירת מחדל:** בלי `--send-live` שום דבר לא נשלח לרשימה האמיתית — רק שליחת בדיקה ל-`NEWSLETTER_TEST_EMAIL` (ברירת מחדל: lioz2468@gmail.com). `--send-live` דורש גם `NEWSLETTER_ALLOW_LIVE_SEND=true` — שני אישורים נפרדים, כי שליחה אמיתית לרשימה היא בלתי הפיכה וחוק הספאם הישראלי (תיקון 40) דורש הסכמה מפורשת + מנגנון הסרה בכל שליחה. **ודא שהרשימה ברב מסר היא opt-in אמיתי לפני שאי פעם מדליקים שליחה אוטומטית.**

צריך ב-`.env` (או ב-GitHub Secrets, ראה `.github/workflows/send-newsletter.yml`): `RESPONDER_C_KEY` / `RESPONDER_C_SECRET` / `RESPONDER_U_KEY` / `RESPONDER_U_SECRET` / `RESPONDER_LIST_ID` — משיגים דרך הגדרות "חיבורים חיצוניים (API)" בחשבון הרב מסר, או תמיכה: 03-7177777.

ה-workflow `send-newsletter.yml` כרגע **ידני בלבד** (`workflow_dispatch`) — לא רץ אוטומטית עד שיש credentials ואומתו כמה שליחות TEST. להפעלת שליחה יומית אוטומטית: הוסיפו `schedule:`/`workflow_run:` לקובץ, אחרי ה-06:00 של Email Digest Pool.

| קובץ נוסף | תפקיד |
|------|--------|
| `market_data.py` | תמונת מצב שוקים חיה (Yahoo Finance, בלי מפתח API) |
| `newsletter_composer.py` | ניסוח גוף ה-HTML המלא של הניוזלטר (Claude, נפרד מ-`composer.py`) |
| `responder_client.py` | לקוח API של רב מסר — חתימת Auth, יצירת/בדיקת/שליחת הודעה |
| `send_newsletter.py` | ה-CLI שמחבר הכל: digest → שוק → Claude → רב מסר |
