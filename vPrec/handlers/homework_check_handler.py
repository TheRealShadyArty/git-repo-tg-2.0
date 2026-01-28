"""Обработчик отчета по проверке домашних заданий"""
import logging
import pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

async def start_homework_check_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [
            InlineKeyboardButton("📅 За месяц", callback_data="hw_check_month"),
            InlineKeyboardButton("📆 За неделю", callback_data="hw_check_week"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(
        "✅ Выберите период для проверки домашних заданий:",
        reply_markup=reply_markup
    )

async def handle_hw_check_period(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """обработка выбора периода (месяц/неделя)"""
    query = update.callback_query
    await query.answer()
    
    period = "month" if query.data == "hw_check_month" else "week"
    period_text = "месяц" if period == "month" else "неделю"
    
    context.user_data['hw_check_period'] = period
    
    await query.edit_message_text(
        f"✅ Вы выбрали проверку за {period_text}.\n\n"
        "Теперь загрузите файл проверки домашних заданий (Excel).\n"
        "Файл должен содержать информацию по преподавателям и проверенным заданиям."
    )

async def process_homework_check_file(update: Update, context: ContextTypes.DEFAULT_TYPE, file_path: str) -> None:
    try:
        df = None
        for header_row in [[0, 1], None, 1]:
            try:
                if header_row is None:
                    df = pd.read_excel(file_path)
                else:
                    df = pd.read_excel(file_path, header=header_row)
                
                columns = df.columns.tolist()
                def col_to_str(c):
                    if isinstance(c, tuple):
                        return " ".join([str(x).strip() for x in c if str(x).strip()])
                    return str(c).strip()
                
                cols_lower = [col_to_str(c).lower() for c in columns]
                if any('получ' in c for c in cols_lower) and any('провер' in c for c in cols_lower):
                    break
            except Exception:
                continue
        
        if df is None:
            df = pd.read_excel(file_path)
            columns = df.columns.tolist()
            cols_lower = [col_to_str(c).lower() for c in columns]

        teacher_idx = next((i for i, c in enumerate(cols_lower) if any(k in c for k in ['преподават', 'учител', 'фио'])), 0)
        issued_idx = next((i for i, c in enumerate(cols_lower) if 'получ' in c), None)
        checked_idx = next((i for i, c in enumerate(cols_lower) if 'провер' in c), None)

        if issued_idx is None or checked_idx is None:
            for i in range(1, len(columns)):
                try:
                    val = pd.to_numeric(df.iloc[0, i], errors='coerce')
                    if pd.notna(val) and val > 0:
                        if issued_idx is None:
                            issued_idx = i
                        elif checked_idx is None:
                            checked_idx = i
                            break
                except Exception:
                    continue

        if issued_idx is None or checked_idx is None:
            sample = cols_lower[:12]
            msg = "❌ не найдены колонки 'получено' или 'проверено'.\nнайденные заголовки:\n"
            msg += "\n".join(f"{i}: {c}" for i, c in enumerate(sample))
            await (update.message.reply_text(msg) if update.message else update.callback_query.edit_message_text(msg))
            return

        selected_period = context.user_data.get('hw_check_period', 'month')
        period_text = 'месяц' if selected_period == 'month' else 'неделю'

        problem_teachers = []
        for idx, row in df.iterrows():
            try:
                name = str(row[columns[teacher_idx]]).strip()
                if not name or pd.isna(row[columns[teacher_idx]]):
                    continue

                issued = pd.to_numeric(str(row[columns[issued_idx]]).strip().replace('\xa0', '').replace(',', '.'), errors='coerce')
                checked = pd.to_numeric(str(row[columns[checked_idx]]).strip().replace('\xa0', '').replace(',', '.'), errors='coerce')
                
                if pd.notna(issued) and issued > 0 and pd.notna(checked):
                    pct = (float(checked) / float(issued)) * 100.0
                    if pct < 70.0:
                        problem_teachers.append((name, int(issued), int(checked), pct))
            except Exception:
                continue

        problem_teachers.sort(key=lambda x: x[3])

        lines = [f"✅ отчет по проверке домашних заданий за {period_text}:"]
        if problem_teachers:
            lines.append(f"⚠️ преподавателей с проверкой < 70%: {len(problem_teachers)}")
            lines.extend(f"• {name}: получено {issued} | проверено {checked} | {pct:.1f}%" for name, issued, checked, pct in problem_teachers)
        else:
            lines.append(f"✅ все преподаватели проверили ≥ 70% заданий за {period_text}.")

        text = "\n".join(lines)
        await (update.message.reply_text(text) if update.message else update.callback_query.edit_message_text(text))

    except Exception:
        logger.exception("ошибка при обработке файла проверки ДЗ")
        msg = "❌ ошибка обработки файла."
        await (update.message.reply_text(msg) if update.message else update.callback_query.edit_message_text(msg))
