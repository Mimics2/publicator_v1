import patch
import os
import logging
import sqlite3
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMINS = [int(x.strip()) for x in os.getenv('ADMINS', '').split(',') if x.strip()]

# Проверка переменных
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не установлен!")
if not ADMINS:
    logger.error("❌ ADMINS не установлены!")

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('channels.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT UNIQUE NOT NULL,
            channel_name TEXT,
            added_by INTEGER,
            is_active BOOLEAN DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()

def add_channel(channel_id, channel_name, user_id):
    conn = sqlite3.connect('channels.db')
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO channels (channel_id, channel_name, added_by, is_active)
            VALUES (?, ?, ?, 1)
        ''', (channel_id, channel_name, user_id))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error adding channel: {e}")
        return False
    finally:
        conn.close()

def get_channels():
    conn = sqlite3.connect('channels.db')
    cursor = conn.cursor()
    cursor.execute('SELECT channel_id, channel_name FROM channels WHERE is_active = 1')
    channels = cursor.fetchall()
    conn.close()
    return channels

def remove_channel(channel_id):
    conn = sqlite3.connect('channels.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM channels WHERE channel_id = ?', (channel_id,))
    conn.commit()
    conn.close()

def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    update.message.reply_text(
        "🤖 Бот-публикатор готов к работе!\n\n"
        "Команды админа:\n"
        "/add_channel <ID_канала> - добавить канал\n"
        "/remove_channel <ID_канала> - удалить канал\n"
        "/list_channels - список каналов\n\n"
        "Для публикации просто перешлите сообщение в этот чат!"
    )

def add_channel_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    if user_id not in ADMINS:
        update.message.reply_text("❌ У вас нет прав для выполнения этой команды!")
        return
    
    if not context.args:
        update.message.reply_text("❌ Используйте: /add_channel <ID_канала>")
        return
    
    channel_id = context.args[0]
    
    try:
        bot = context.bot
        chat = bot.get_chat(channel_id)
        
        admins = bot.get_chat_administrators(channel_id)
        bot_is_admin = any(admin.user.id == bot.id for admin in admins)
        
        if not bot_is_admin:
            update.message.reply_text(
                "❌ Бот не является администратором в этом канале!\n"
                "Добавьте бота как администратора с правами на отправку сообщений."
            )
            return
        
        if add_channel(channel_id, chat.title, user_id):
            update.message.reply_text(f"✅ Канал '{chat.title}' успешно добавлен!")
        else:
            update.message.reply_text("❌ Ошибка при добавлении канала!")
            
    except Exception as e:
        logger.error(f"Error checking channel: {e}")
        update.message.reply_text("❌ Ошибка: неверный ID канала или бот не добавлен в канал!")

def remove_channel_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    if user_id not in ADMINS:
        update.message.reply_text("❌ У вас нет прав для выполнения этой команды!")
        return
    
    if not context.args:
        update.message.reply_text("❌ Используйте: /remove_channel <ID_канала>")
        return
    
    channel_id = context.args[0]
    remove_channel(channel_id)
    update.message.reply_text("✅ Канал удален из списка!")

def list_channels_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    if user_id not in ADMINS:
        update.message.reply_text("❌ У вас нет прав для выполнения этой команды!")
        return
    
    channels = get_channels()
    if not channels:
        update.message.reply_text("📭 Нет подключенных каналов!")
        return
    
    message = "📋 Подключенные каналы:\n\n"
    for channel_id, channel_name in channels:
        message += f"• {channel_name}\nID: `{channel_id}`\n\n"
    
    update.message.reply_text(message, parse_mode='Markdown')

def handle_forwarded_message(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    if user_id not in ADMINS:
        update.message.reply_text("❌ У вас нет прав для публикации!")
        return
    
    if not update.message or not update.message.forward_from_chat:
        update.message.reply_text("❌ Это не пересланное сообщение из канала!")
        return
    
    original_chat = update.message.forward_from_chat
    message_id = update.message.forward_from_message_id
    
    channels = get_channels()
    successful = 0
    failed = 0
    
    for channel_id, channel_name in channels:
        try:
            context.bot.forward_message(
                chat_id=channel_id,
                from_chat_id=original_chat.id,
                message_id=message_id
            )
            successful += 1
            logger.info(f"Message forwarded to {channel_name}")
            
        except Exception as e:
            logger.error(f"Error forwarding to {channel_name}: {e}")
            failed += 1
    
    update.message.reply_text(
        f"📊 Результат публикации:\n"
        f"✅ Успешно: {successful}\n"
        f"❌ Ошибок: {failed}"
    )

def main():
    if not BOT_TOKEN or not ADMINS:
        logger.error("❌ Не установлены обязательные переменные окружения!")
        return
    
    logger.info("🚀 Запуск бота...")
    logger.info(f"👑 Админы: {ADMINS}")
    
    init_db()
    
    # Создаем updater вместо application
    updater = Updater(token=BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    
    # Обработчики команд
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("add_channel", add_channel_command))
    dispatcher.add_handler(CommandHandler("remove_channel", remove_channel_command))
    dispatcher.add_handler(CommandHandler("list_channels", list_channels_command))
    
    # Обработчик пересланных сообщений
    dispatcher.add_handler(MessageHandler(Filters.forwarded & Filters.all, handle_forwarded_message))
    
    # Запуск бота
    updater.start_polling()
    logger.info("✅ Бот запущен и работает...")
    updater.idle()

if __name__ == '__main__':
    main()
