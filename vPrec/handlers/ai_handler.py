import os
import asyncio
import logging
import requests
import pandas as pd
import re
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

logger = logging.getLogger(__name__)

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY") 
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-large-latest")
MISTRAL_ENDPOINT = os.getenv(
    "MISTRAL_ENDPOINT",
    "https://api.mistral.ai/v1/chat/completions",
)

async def start_ai_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "🤖 выбран ai-помощник. опишите задачу — кратко или подробно, а я постараюсь помочь."
        )
    else:
        await update.message.reply_text(
            "🤖 выбран ai-помощник. опишите задачу — кратко или подробно, а я постараюсь помочь."
        )
    context.user_data["report_type"] = "ai"

async def _send_ai_result(update: Update, context: ContextTypes.DEFAULT_TYPE, ai_reply: str) -> int:
    max_len = 4000
    if len(ai_reply) > max_len:
        ai_reply = ai_reply[: max_len - 20] + '...'
    await update.message.reply_text(ai_reply)
    await update.message.reply_text(
        "готово — выберите следующую опцию:", reply_markup=context.application.bot_data.get("main_keyboard")
    )
    context.user_data.clear()
    return ConversationHandler.END

async def process_ai_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    user_text = update.message.text.strip() if update.message and update.message.text else ""
    if not user_text:
        await update.message.reply_text("❗ пожалуйста, напишите запрос текстом.")
        return "ai"

    reply_to = update.message.reply_to_message if update.message else None
    prompt = None
    
    if reply_to and (getattr(reply_to, 'text', None) or getattr(reply_to, 'caption', None)):
        replied_text = getattr(reply_to, 'text', None) or getattr(reply_to, 'caption', None)
        problems = []
        
        pattern = re.compile(
            r"^[\u2022\-\*\•]?\s*(?P<name>[^:\n]+):\s*[Пп]олучено\s*(?P<issued>[0-9]+)\s*\|\s*[Пп]роверено\s*(?P<checked>[0-9]+)\s*\|\s*(?P<pct>[0-9.,]+)%",
            re.MULTILINE,
        )
        
        for m in pattern.finditer(replied_text):
            try:
                problems.append({
                    'name': m.group('name').strip(),
                    'issued': int(m.group('issued')),
                    'checked': int(m.group('checked')),
                    'percentage': float(m.group('pct').replace(',', '.'))
                })
            except Exception:
                continue

        if problems:
            q = user_text.lower()
            if any(w in q for w in ['кто меньше', 'кто меньше всех', 'кто наименее', 'least', 'меньше всех провер']):
                worst = min(problems, key=lambda x: x.get('percentage', 100.0))
                await update.message.reply_text(
                    f"👎 наименее проверял: {worst['name']} — {worst['checked']}/{worst['issued']} ({worst['percentage']:.1f}%)"
                )
                return 'ai'
            elif 'топ' in q or 'первые' in q or 'наиб' in q or 'лучше' in q:
                sorted_p = sorted(problems, key=lambda x: x.get('percentage', 0.0), reverse=True)
                lines = ["топ 5 преподавателей по % проверки:"]
                lines.extend(f"• {t['name']}: {t['checked']}/{t['issued']} ({t['percentage']:.1f}%)" for t in sorted_p[:5])
                await update.message.reply_text('\n'.join(lines))
                return 'ai'
            elif 'сколько' in q and ('преподав' in q or 'преподавателей' in q):
                await update.message.reply_text(f"⚠️ преподавателей с проблемой: {len(problems)}")
                return 'ai'
            else:
                sb = ["разобранный отчет (из сообщения):", "преподаватели с проблемами:"]
                sb.extend(f"{t['name']}: issued={t['issued']}, checked={t['checked']}, pct={t['percentage']:.1f}" for t in problems[:50])
                sb.append('\nвопрос пользователя: ' + user_text)
                prompt = '\n'.join(sb)
        else:
            prompt = f"контекст (сообщение):\n{replied_text}\n\nвопрос пользователя: {user_text}"
    else:
        prompt = user_text

    await update.message.reply_text('🔎 отправляю запрос в ai, ожидайте...')
    
    try:
        loop = asyncio.get_event_loop()
        ai_reply = await loop.run_in_executor(None, _call_mistral, prompt)
    except Exception:
        logger.exception('ошибка при обращении к mistral api')
        await update.message.reply_text('❌ ошибка при обращении к ai. попробуйте позже.')
        return 'ai'

    if not ai_reply:
        await update.message.reply_text('❌ ai вернул пустой ответ.')
        return 'ai'

    return await _send_ai_result(update, context, ai_reply)


async def process_ai_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    document = update.message.document if update.message else None
    if not document:
        await update.message.reply_text("❗ пожалуйста, загрузите файл excel (.xls или .xlsx).")
        return "ai"

    filename = document.file_name or "file"
    if not filename.lower().endswith((".xls", ".xlsx")):
        await update.message.reply_text("❗ поддерживаются только файлы .xls или .xlsx для анализа.")
        return "ai"

    await update.message.reply_text("📥 файл получен, скачиваю и анализирую...")
    user_caption = update.message.caption.strip() if update.message and update.message.caption else ""

    temp_path = f"temp_{document.file_id}_{filename}"
    try:
        file_obj = await document.get_file()
        await file_obj.download_to_drive(temp_path)

        try:
            xls = pd.read_excel(temp_path, sheet_name=None)
        except Exception as e:
            raise RuntimeError(f"не удалось прочитать excel: {e}")

        parts = []
        for sheet_name, df in xls.items():
            parts.append(f"--- sheet: {sheet_name} ---")
            try:
                csv = df.to_csv(index=False)
            except Exception:
                csv = df.astype(str).to_csv(index=False)
            parts.append(csv)

        content = "\n".join(parts)
        instruction = "пользователь загрузил excel-файл. проанализируй таблицы и дай краткое резюме, выдели ключевые столбцы/строки, возможные аномалии, агрегаты и рекомендации.\n\n"
        
        max_content = 15000
        content_snippet = content[: max_content - 200] + "\n... (сокращено)" if len(content) > max_content else content
        
        if user_caption:
            prompt = f"задача от пользователя: {user_caption}\n\n{instruction}excel start:\n{content_snippet}\nexcel end:\nотвечай подробно, но лаконично."
        else:
            prompt = f"{instruction}excel start:\n{content_snippet}\nexcel end:\nотвечай подробно, но лаконично."

        loop = asyncio.get_event_loop()
        ai_reply = await loop.run_in_executor(None, _call_mistral, prompt)

        if not ai_reply:
            await update.message.reply_text("❌ ai вернул пустой ответ.")
            return "ai"

        result = await _send_ai_result(update, context, ai_reply)
        
    except Exception as e:
        logger.exception("ошибка при обращении к mistral api для файла")
        await update.message.reply_text(f"❌ ошибка при анализе файла: {e}")
        return "ai"
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass

    return result

def _call_mistral(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json",
    }

    data = {
        "model": MISTRAL_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.6,
        "max_tokens": 512,
    }

    try:
        resp = requests.post(MISTRAL_ENDPOINT, json=data, headers=headers, timeout=30)
    except requests.RequestException as e:
        raise RuntimeError(f"ошибка сети при обращении к mistral api: {e}")

    if resp.status_code == 404:
        body = resp.text.strip()
        raise RuntimeError(
            f"mistral api вернул 404 not found для url {MISTRAL_ENDPOINT}. "
            "проверьте переменные окружения mistral_model или mistral_endpoint." +
            (f" ответ: {body}" if body else "")
        )

    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        body = resp.text.strip()
        raise RuntimeError(f"ошибка mistral api {resp.status_code}: {body or str(e)}")

    try:
        j = resp.json()
    except Exception:
        return resp.text or ""

    if isinstance(j, dict) and "choices" in j and isinstance(j["choices"], list) and j["choices"]:
        choice = j["choices"][0]
        if isinstance(choice, dict) and "message" in choice and isinstance(choice["message"], dict):
            return choice["message"].get("content", "")

    return j.get("message") if isinstance(j, dict) and "message" in j else ""