import os
import logging
import sqlite3
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMINS = list(map(int, os.getenv('ADMINS', '').split(','))) if os.getenv('ADMINS') else []
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///channels.db')

# Для Railway - используем PostgreSQL если доступно
def get_db_connection():
    if DATABASE_URL.startswith('postgresql'):
        import psycopg2
        return psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        return sqlite3.connect('channels.db')

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if DATABASE_URL.startswith('postgresql'):
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id SERIAL PRIMARY KEY,
                channel_id TEXT UNIQUE NOT NULL,
                channel_name TEXT,
                added_by BIGINT,
                is_active BOOLEAN DEFAULT TRUE
            )
        ''')
    else:
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
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if DATABASE_URL.startswith('postgresql'):
            cursor.execute('''
                INSERT INTO channels (channel_id, channel_name, added_by, is_active)
                VALUES (%s, %s, %s, TRUE)
                ON CONFLICT (channel_id) DO UPDATE SET
                channel_name = EXCLUDED.channel_name,
                is_active = TRUE
            ''', (channel_id, channel_name, user_id))
        else:
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
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if DATABASE_URL.startswith('postgresql'):
        cursor.execute('SELECT channel_id, channel_name FROM channels WHERE is_active = TRUE')
    else:
        cursor.execute('SELECT channel_id, channel_name FROM channels WHERE is_active = 1')
    
    channels = cursor.fetchall()
    conn.close()
    return channels

def remove_channel(channel_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if DATABASE_URL.startswith('postgresql'):
        cursor.execute('DELETE FROM channels WHERE channel_id = %s', (channel_id,))
    else:
        cursor.execute('DELETE FROM channels WHERE channel_id = ?', (channel_id,))
    
    conn.commit()
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        "🤖 Бот-публикатор готов к работе!\n\n"
        "Команды админа:\n"
        "/add_channel <ID_канала> - добавить канал\n"
        "/remove_channel <ID_канала> - удалить канал\n"
        "/list_channels - список каналов\n\n"
        "Для публикации просто перешлите сообщение в этот чат!"
    )

async def add_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in ADMINS:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Используйте: /add_channel <ID_канала>")
        return
    
    channel_id = context.args[0]
    
    try:
        bot = context.bot
        chat = await bot.get_chat(channel_id)
        
        admins = await bot.get_chat_administrators(channel_id)
        bot_is_admin = any(admin.user.id == bot.id for admin in admins)
        
        if not bot_is_admin:
            await update.message.reply_text(
                "❌ Бот не является администратором в этом канале!\n"
                "Добавьте бота как администратора с правами на отправку сообщений."
            )
            return
        
        if add_channel(channel_id, chat.title, user_id):
            await update.message.reply_text(f"✅ Канал '{chat.title}' успешно добавлен!")
        else:
            await update.message.reply_text("❌ Ошибка при добавлении канала!")
            
    except Exception as e:
        logger.error(f"Error checking channel: {e}")
        await update.message.reply_text("❌ Ошибка: неверный ID канала или бот не добавлен в канал!")

async def remove_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in ADMINS:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Используйте: /remove_channel <ID_канала>")
        return
    
    channel_id = context.args[0]
    remove_channel(channel_id)
    await update.message.reply_text("✅ Канал удален из списка!")

async def list_channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in ADMINS:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды!")
        return
    
    channels = get_channels()
    if not channels:
        await update.message.reply_text("📭 Нет подключенных каналов!")
        return
    
    message = "📋 Подключенные каналы:\n\n"
    for channel_id, channel_name in channels:
        message += f"• {channel_name}\nID: `{channel_id}`\n\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def handle_forwarded_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in ADMINS:
        await update.message.reply_text("❌ У вас нет прав для публикации!")
        return
    
    if not update.message or not update.message.forward_from_chat:
        await update.message.reply_text("❌ Это не пересланное сообщение из канала!")
        return
    
    original_chat = update.message.forward_from_chat
    message_id = update.message.forward_from_message_id
    
    channels = get_channels()
    successful = 0
    failed = 0
    
    for channel_id, channel_name in channels:
        try:
            await context.bot.forward_message(
                chat_id=channel_id,
                from_chat_id=original_chat.id,
                message_id=message_id
            )
            successful += 1
            logger.info(f"Message forwarded to {channel_name}")
            
        except Exception as e:
            logger.error(f"Error forwarding to {channel_name}: {e}")
            failed += 1
    
    await update.message.reply_text(
        f"📊 Результат публикации:\n"
        f"✅ Успешно: {successful}\n"
        f"❌ Ошибок: {failed}"
    )

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    
    if not ADMINS:
        logger.error("ADMINS not set!")
        return
    
    init_db()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add_channel", add_channel_command))
    application.add_handler(CommandHandler("remove_channel", remove_channel_command))
    application.add_handler(CommandHandler("list_channels", list_channels_command))
    application.add_handler(MessageHandler(filters.FORWARDED & filters.ALL, handle_forwarded_message))
    
    # Для Railway используем webhook или polling
    if os.getenv('RAILWAY_STATIC_URL'):
        # Webhook для продакшена
        PORT = int(os.getenv('PORT', 8000))
        WEBHOOK_URL = f"https://{os.getenv('RAILWAY_STATIC_URL')}/{BOT_TOKEN}"
        
        async def set_webhook(app):
            await app.bot.set_webhook(WEBHOOK_URL)
        
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL,
            secret_token=os.getenv('WEBHOOK_SECRET', ''),
        )
    else:
        # Polling для разработки
        application.run_polling()

if __name__ == '__main__':
    main()
