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
