import os
import logging
import sqlite3
from datetime import datetime, timedelta
import pytz
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMINS = [int(x.strip()) for x in os.getenv('ADMINS', '').split(',') if x.strip()]
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL,
            message_data TEXT,
            scheduled_time DATETIME,
            status TEXT DEFAULT 'scheduled',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
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

def add_scheduled_post(channel_id, message_data, scheduled_time):
    conn = sqlite3.connect('channels.db')
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO scheduled_posts (channel_id, message_data, scheduled_time)
            VALUES (?, ?, ?)
        ''', (channel_id, message_data, scheduled_time))
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        logger.error(f"Error adding scheduled post: {e}")
        return None
    finally:
        conn.close()

def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    update.message.reply_text(
        "🤖 Бот-публикатор с отложенным постингом!\n\n"
        "Команды админа:\n"
        "/add_channel <ID_канала> - добавить канал\n"
        "/remove_channel <ID_канала> - удалить канал\n"
        "/list_channels - список каналов\n"
        "/post_now - опубликовать пересланное сообщение сразу\n"
        "/schedule <часы:минуты> - отложить публикацию на сегодня\n"
        "/schedule <дд.мм.гггг чч:мм> - отложить на конкретную дату\n\n"
        "Примеры:\n"
        "/schedule 14:30 - сегодня в 14:30\n"
        "/schedule 25.12.2024 10:00 - 25 декабря в 10:00"
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

def post_now(update: Update, context: CallbackContext):
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

def schedule_post(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    if user_id not in ADMINS:
        update.message.reply_text("❌ У вас нет прав для планирования!")
        return
    
    if not update.message or not update.message.forward_from_chat:
        update.message.reply_text("❌ Это не пересланное сообщение из канала!")
        return
    
    if not context.args:
        update.message.reply_text(
            "❌ Укажите время для публикации!\n\n"
            "Примеры:\n"
            "/schedule 14:30 - сегодня в 14:30\n"
            "/schedule 25.12.2024 10:00 - 25 декабря в 10:00"
        )
        return
    
    # Парсим время
    time_input = ' '.join(context.args)
    try:
        if ':' in time_input and len(time_input.split()) == 1:
            # Формат: HH:MM (сегодня)
            hours, minutes = map(int, time_input.split(':'))
            now = datetime.now(MOSCOW_TZ)
            scheduled_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
            
            # Если время уже прошло сегодня, планируем на завтра
            if scheduled_time < now:
                scheduled_time += timedelta(days=1)
                
        else:
            # Формат: DD.MM.YYYY HH:MM
            date_str, time_str = time_input.split()
            day, month, year = map(int, date_str.split('.'))
            hours, minutes = map(int, time_str.split(':'))
            scheduled_time = MOSCOW_TZ.localize(
                datetime(year, month, day, hours, minutes, 0)
            )
        
        # Проверяем что время в будущем
        if scheduled_time < datetime.now(MOSCOW_TZ):
            update.message.reply_text("❌ Нельзя планировать публикацию в прошлом!")
            return
        
        original_chat = update.message.forward_from_chat
        message_id = update.message.forward_from_message_id
        
        channels = get_channels()
        scheduled_count = 0
        
        for channel_id, channel_name in channels:
            message_data = f"{original_chat.id}:{message_id}"
            post_id = add_scheduled_post(channel_id, message_data, scheduled_time)
            
            if post_id:
                # Планируем задачу
                context.job_queue.run_once(
                    publish_scheduled_message,
                    scheduled_time,
                    context={
                        'channel_id': channel_id,
                        'message_data': message_data,
                        'post_id': post_id
                    },
                    name=f"post_{post_id}"
                )
                scheduled_count += 1
        
        update.message.reply_text(
            f"✅ Публикация запланирована на {scheduled_time.strftime('%d.%m.%Y %H:%M')} по Москве\n"
            f"📋 Каналов: {scheduled_count}"
        )
        
    except Exception as e:
        logger.error(f"Error scheduling post: {e}")
        update.message.reply_text(
            "❌ Ошибка формата времени!\n\n"
            "Примеры:\n"
            "/schedule 14:30 - сегодня в 14:30\n"
            "/schedule 25.12.2024 10:00 - 25 декабря в 10:00"
        )

def publish_scheduled_message(context: CallbackContext):
    job = context.job
    channel_id = job.context['channel_id']
    chat_id, message_id = job.context['message_data'].split(':')
    
    try:
        context.bot.forward_message(
            chat_id=channel_id,
            from_chat_id=chat_id,
            message_id=int(message_id)
        )
        logger.info(f"Scheduled message published to {channel_id}")
        
        # Обновляем статус в БД
        conn = sqlite3.connect('channels.db')
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE scheduled_posts SET status = ? WHERE id = ?',
            ('published', job.context['post_id'])
        )
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.error(f"Error publishing scheduled message: {e}")

def handle_forwarded_message(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    if user_id not in ADMINS:
        update.message.reply_text("❌ У вас нет прав для публикации!")
        return
    
    if not update.message or not update.message.forward_from_chat:
        update.message.reply_text("❌ Это не пересланное сообщение из канала!")
        return
    
    # Спрашиваем как публиковать
    update.message.reply_text(
        "📝 Выберите тип публикации:\n"
        "/post_now - опубликовать сразу\n"
        "/schedule <время> - отложить публикацию\n\n"
        "Пример времени:\n"
        "/schedule 14:30 - сегодня в 14:30\n"
        "/schedule 25.12.2024 10:00 - 25 декабря"
    )

def main():
    if not BOT_TOKEN or not ADMINS:
        logger.error("❌ Не установлены обязательные переменные окружения!")
        return
    
    logger.info("🚀 Запуск бота...")
    logger.info(f"👑 Админы: {ADMINS}")
    
    init_db()
    
    updater = Updater(token=BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    
    # Обработчики команд
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("add_channel", add_channel_command))
    dispatcher.add_handler(CommandHandler("remove_channel", remove_channel_command))
    dispatcher.add_handler(CommandHandler("list_channels", list_channels_command))
    dispatcher.add_handler(CommandHandler("post_now", post_now))
    dispatcher.add_handler(CommandHandler("schedule", schedule_post))
    
    # Обработчик пересланных сообщений
    dispatcher.add_handler(MessageHandler(Filters.forwarded & Filters.all, handle_forwarded_message))
    
    # Запуск бота
    updater.start_polling()
    logger.info("✅ Бот запущен и работает...")
    updater.idle()

if __name__ == '__main__':
    main()
