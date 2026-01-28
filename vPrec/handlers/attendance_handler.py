import logging
import pandas as pd
from telegram import Update
from telegram.ext import ContextTypes
from .report_store import send_and_store

logger = logging.getLogger(__name__)

async def start_attendance_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    #запуск отчета по посещаемости
    text = "📊 Загрузите файл посещаемости (Excel).\nФайл должен содержать информацию по преподавателям и их посещаемость."
    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)

async def process_attendance_file(update: Update, context: ContextTypes.DEFAULT_TYPE, file_path: str) -> None:
    #обработка файла посещаемости
    try:
        df = pd.read_excel(file_path)

        columns = df.columns.tolist()
        teacher_col = None
        attendance_col = None
        attendance_keywords = ['посещ', 'сред', 'процент', '%', 'присут', 'avg']
        teacher_keywords = ['преподават', 'учител', 'фио', 'преподав']

        for col in columns:
            col_lower = str(col).lower()
            if any(k in col_lower for k in teacher_keywords):
                teacher_col = col
            if any(k in col_lower for k in attendance_keywords):
                attendance_col = col

        if teacher_col is None:
            teacher_col = columns[0]
        if attendance_col is None:
            attendance_col = columns[1] if len(columns) > 1 else columns[0]

        s = df[attendance_col].astype(str).fillna('').str.replace('\xa0', ' ')
        s_clean = s.str.replace(r"[^0-9,\.%-]", "", regex=True)
        s_clean = s_clean.str.replace('%', '', regex=False).str.replace(',', '.', regex=False)
        nums = pd.to_numeric(s_clean, errors='coerce')

        problem_teachers = []
        for idx, row in df.iterrows():
            try:
                name = row[teacher_col]
                if pd.isna(name):
                    continue
                name = str(name).strip()

                val = nums.iloc[idx]
                if pd.isna(val):
                    continue
                attendance = float(val)
                if 0.0 <= attendance <= 1.0:
                    attendance *= 100.0

                if attendance < 40.0:
                    problem_teachers.append((name, attendance))
            except Exception:
                continue

        problem_teachers.sort(key=lambda x: x[1])

        lines = ["📊 Отчет по посещаемости преподавателей:"]
        if problem_teachers:
            lines.append(f"⚠️ Преподавателей с посещаемостью < 40%: {len(problem_teachers)}")
            for name, att in problem_teachers:
                lines.append(f"• {name}: {att:.1f}%")
        else:
            lines.append("✅ Все преподаватели имеют посещаемость ≥ 40%.")

        text = "\n".join(lines)
        await send_and_store(update, context, text, parse_mode=None, metadata={'type': 'attendance'})

    except Exception:
        logger.exception("ошибка при обработке файла посещаемости")
        if update.message:
            await update.message.reply_text("❌ Ошибка обработки файла.")
        elif update.callback_query:
            await update.callback_query.edit_message_text("❌ Ошибка обработки файла.")
