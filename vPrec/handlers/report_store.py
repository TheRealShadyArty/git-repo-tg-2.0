import logging
from telegram import Update, Message

logger = logging.getLogger(__name__)

async def send_and_store(update: Update, context, text: str, parse_mode: str = None, metadata: dict = None) -> Message:
    try:
        if update.callback_query:
            try:
                return await update.callback_query.edit_message_text(text, parse_mode=parse_mode)
            except Exception:
                if update.callback_query.message:
                    return await update.callback_query.message.reply_text(text, parse_mode=parse_mode)
        elif update.message:
            return await update.message.reply_text(text, parse_mode=parse_mode)
    except Exception:
        logger.exception('ошибка при отправке сообщения')
