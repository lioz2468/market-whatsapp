# Style Extractor

מערכת Python שמנתחת את סגנון הכתיבה והדיבור שלך ובונה פרופיל מפורט.

## דרישות מקדימות
- Python 3.10+
- ANTHROPIC_API_KEY
- HUGGINGFACE_TOKEN (רק אם רוצים diarization)

## התקנה

```bash
cd style-extractor
pip install -r requirements.txt
cp .env.example .env
# ← ערוך את .env והכנס מפתחות API
```

לdiarization (אופציונלי):
```bash
pip install pyannote.audio whisperx torch
```

## הכנת החומר

```
raw_content/
├── podcasts/   ← קבצי mp3/m4a
├── posts/      ← קבצי txt/md/docx
├── whatsapp/   ← ייצוא צ'אט (txt)
└── tweets/     ← טוויטים (txt)
```

## שימוש

```bash
# כל הפייפליין בבת אחת
python main.py all

# שלבים נפרדים
python main.py ingest                     # תמלול + עיבוד
python main.py ingest --skip-diarization  # בלי זיהוי דוברים
python main.py analyze                    # ניתוח סגנון
python main.py validate                   # אישור ושמירה

# טסט מהיר
python main.py test "הפד הוריד ריבית"
```

## פלט

`style_profile.json` — הפרופיל המלא עם:
- אוצר מילים, סלנג, אנגלית בעברית
- מבנה משפטים וסימני פיסוק
- טון ואישיות
- דפוסים ייחודיים
- 50 דוגמאות אופייניות

## מבנה קבצים

```
style-extractor/
├── main.py              ← CLI entry point
├── config.py            ← הגדרות
├── ingest/
│   ├── audio.py         ← תמלול + diarization
│   └── text_reader.py   ← קריאת פוסטים/WhatsApp
├── analyzer/
│   ├── style_analyzer.py   ← ניתוח עם Claude
│   └── profile_builder.py  ← מיזוג + שמירה
├── raw_content/         ← חומר גולמי (לא נשמר ב-git)
├── processed/           ← תמלולים + ניתוחים (cache)
└── style_profile.json   ← הפרופיל הסופי
```
