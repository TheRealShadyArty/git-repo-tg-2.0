"""Обработчик отчета по темам занятий"""
import logging
import pandas as pd
import re
from telegram import Update
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown
from .report_store import send_and_store

logger = logging.getLogger(__name__)

async def start_lessons_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = "📚 *Отчет по темам занятий*\n\nЗагрузите файл *Темы уроков.xls*\n\nБот проверит формат тем:\n`Урок № X. Тема: ...`\nНекорректные темы будут перечислены."
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode='Markdown')
    else:
        await update.message.reply_text("📚 Загрузите файл с темами уроков (Excel).\nПроверяется формат: 'Урок № X. Тема: ...'")

async def process_lessons_file(update: Update, context: ContextTypes.DEFAULT_TYPE, file_path: str) -> None:
    try:
        df = pd.read_excel(file_path, header=0)

        topic_col = None
        if 'Тема урока' in df.columns:
            topic_col = 'Тема урока'
        else:
            for col in df.columns:
                if isinstance(col, str) and 'тема' in col.lower():
                    topic_col = col
                    break
            if topic_col is None:
                for col in df.columns:
                    sample = df[col].dropna().astype(str).str.strip()
                    if len(sample) > 0:
                        topic_col = col
                        break

        if topic_col is None:
            await update.message.reply_text("❌ Не удалось определить колонку с темами уроков.")
            return

        topics_series = df[topic_col].astype(str).fillna('').str.strip()
        if topics_series.dropna().shape[0] == 0 and all(t == '' for t in topics_series):
            await update.message.reply_text("❌ Нет тем уроков в выбранной колонке.")
            return

        pattern = re.compile(r'^Урок\s*№\s*\d+\.?\s*Тема\s*:\s*.+', re.IGNORECASE)

        correct = []
        incorrect = []

        for idx, topic in topics_series.items():
            topic_text = topic if isinstance(topic, str) else str(topic)
            if pattern.match(topic_text):
                correct.append(topic_text)
            else:
                row_no = int(idx) + 2 if hasattr(idx, '__int__') else idx
                incorrect.append((row_no, topic_text))

        report_lines = [
            "📚 Отчет по темам занятий",
            "",
            f"✅ Корректных тем: {len(correct)}",
            f"❌ Некорректных тем: {len(incorrect)}",
            ""
        ]

        if incorrect:
            report_lines.append("примеры некорректных тем (первые 100):")
            for row_no, topic_text in incorrect[:100]:
                report_lines.append(f"• [строка {row_no}] {topic_text}")
            if len(incorrect) > 100:
                report_lines.append(f"... и ещё {len(incorrect) - 100} некорректных.")
        else:
            report_lines.append("🎉 Все темы в правильном формате!")

        report = "\n".join(report_lines)
        MAX_LEN = 4000

        if not incorrect:
            escaped = escape_markdown(report, version=2)
            await update.message.reply_text(escaped, parse_mode='MarkdownV2')
            return

        header_lines = report_lines[:5]
        header = "\n".join(header_lines) + "\n"
        item_lines = [f"• [строка {row_no}] {topic_text}" for row_no, topic_text in incorrect]

        cur = header
        for line in item_lines:
            candidate = cur + line + "\n"
            if len(candidate) > MAX_LEN:
                escaped = escape_markdown(cur, version=2)
                await send_and_store(update, context, escaped, parse_mode='MarkdownV2', metadata={'type': 'lessons'})
                cur = line + "\n"
            else:
                cur = candidate

        if cur.strip():
            escaped = escape_markdown(cur, version=2)
            await send_and_store(update, context, escaped, parse_mode='MarkdownV2', metadata={'type': 'lessons'})

    except Exception:
        logger.exception("ошибка при обработке тем занятий")
        await update.message.reply_text("❌ Ошибка при чтении файла.")