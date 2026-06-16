import os          # <-- добавлен для чтения переменных окружения
import telebot
import sqlite3
from telebot import types
from datetime import datetime, timedelta
import threading   # <-- для фонового веб-сервера
from http.server import HTTPServer, BaseHTTPRequestHandler   # <-- веб-сервер

# ========== ТОКЕН БЕРЁМ ИЗ ПЕРЕМЕННОЙ ОКРУЖЕНИЯ ==========
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("❌ Не задана переменная окружения TELEGRAM_TOKEN")

bot = telebot.TeleBot(TOKEN)

# ========== БАЗА ДАННЫХ ==========
db = sqlite3.connect("database.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS warnings (
    user_id INTEGER,
    chat_id INTEGER,
    warns INTEGER,
    PRIMARY KEY (user_id, chat_id)
)
""")
db.commit()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def is_admin(chat_id, user_id):
    """Проверяет, является ли пользователь администратором."""
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except:
        return False

def get_warns(user_id, chat_id):
    """Возвращает количество предупреждений."""
    cursor.execute(
        "SELECT warns FROM warnings WHERE user_id=? AND chat_id=?",
        (user_id, chat_id)
    )
    row = cursor.fetchone()
    return row[0] if row else 0

def add_warn(user_id, chat_id):
    """Увеличивает счётчик предупреждений на 1."""
    current = get_warns(user_id, chat_id)
    new = current + 1
    if current == 0:
        cursor.execute(
            "INSERT INTO warnings (user_id, chat_id, warns) VALUES (?, ?, ?)",
            (user_id, chat_id, new)
        )
    else:
        cursor.execute(
            "UPDATE warnings SET warns=? WHERE user_id=? AND chat_id=?",
            (new, user_id, chat_id)
        )
    db.commit()
    return new

def remove_warn(user_id, chat_id):
    """Уменьшает счётчик предупреждений на 1 (удаляет запись, если стало 0)."""
    current = get_warns(user_id, chat_id)
    if current <= 0:
        return 0
    new = current - 1
    if new == 0:
        cursor.execute(
            "DELETE FROM warnings WHERE user_id=? AND chat_id=?",
            (user_id, chat_id)
        )
    else:
        cursor.execute(
            "UPDATE warnings SET warns=? WHERE user_id=? AND chat_id=?",
            (new, user_id, chat_id)
        )
    db.commit()
    return new

def send_help(chat_id):
    """Отправляет справку."""
    text = (
        "📖 *Команды бота*\n\n"
        "`/start` – приветствие\n"
        "`/help` – эта справка\n\n"
        "*Модерация (только для админов, ответом на сообщение):*\n"
        "▪ `/ban` – забанить\n"
        "▪ `/unban` – разбанить\n"
        "▪ `/mute <минут>` – замутить\n"
        "▪ `/unmute` – размутить\n"
        "▪ `/warn` – выдать предупреждение\n"
        "▪ `/unwarn` – снять одно предупреждение\n"
        "▪ `/warnings` – показать кол-во предупреждений\n\n"
        "⚠️ При 3-х предупреждениях – автоматический бан."
    )
    bot.send_message(chat_id, text, parse_mode="Markdown")

# ========== ОБРАБОТЧИКИ КОМАНД ==========

@bot.message_handler(commands=["start"])
def start(message):
    if message.chat.type != "private":
        return
    text = (
        f"👋 *Привет, {message.from_user.first_name}!*\n\n"
        "🤖 Я – *Chat Moder Bot*\n"
        "Помогаю админам управлять группой.\n"
        "Для работы дай мне права администратора.\n"
        "Напиши /help, чтобы увидеть команды."
    )
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=["help"])
def help_command(message):
    send_help(message.chat.id)

# ---------- БАН / РАЗБАН ----------

@bot.message_handler(commands=["ban"])
def ban_user(message):
    if message.chat.type == "private":
        return
    if not is_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "⛔ Только для администраторов.")
        return
    if not message.reply_to_message:
        bot.reply_to(message, "⚠️ Ответь на сообщение пользователя.")
        return
    user = message.reply_to_message.from_user
    try:
        bot.ban_chat_member(message.chat.id, user.id)
        bot.send_message(message.chat.id, f"🔨 *{user.first_name}* забанен.", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, "❌ Ошибка: проверь права бота.")

@bot.message_handler(commands=["unban"])
def unban_user(message):
    if message.chat.type == "private":
        return
    if not is_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "⛔ Только для администраторов.")
        return
    if not message.reply_to_message:
        bot.reply_to(message, "⚠️ Ответь на сообщение пользователя.")
        return
    user = message.reply_to_message.from_user
    try:
        bot.unban_chat_member(message.chat.id, user.id)
        bot.send_message(message.chat.id, f"✅ *{user.first_name}* разбанен.", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, "❌ Ошибка: проверь права бота.")

# ---------- МУТ / РАЗМУТ ----------

@bot.message_handler(commands=["mute"])
def mute_user(message):
    if message.chat.type == "private":
        return
    if not is_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "⛔ Только для администраторов.")
        return
    if not message.reply_to_message:
        bot.reply_to(message, "⚠️ Ответь на сообщение пользователя.")
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "📝 Пример: `/mute 10` (минут)", parse_mode="Markdown")
        return
    try:
        minutes = int(args[1])
        if minutes <= 0:
            raise ValueError
    except:
        bot.reply_to(message, "❌ Укажи корректное число минут.")
        return
    user = message.reply_to_message.from_user
    until_date = datetime.now() + timedelta(minutes=minutes)
    try:
        bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=user.id,
            until_date=until_date,
            permissions=types.ChatPermissions(can_send_messages=False)
        )
        bot.send_message(message.chat.id, f"🔇 *{user.first_name}* замучен на {minutes} мин.", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, "❌ Ошибка: проверь права бота.")

@bot.message_handler(commands=["unmute"])
def unmute_user(message):
    if message.chat.type == "private":
        return
    if not is_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "⛔ Только для администраторов.")
        return
    if not message.reply_to_message:
        bot.reply_to(message, "⚠️ Ответь на сообщение пользователя.")
        return
    user = message.reply_to_message.from_user
    try:
        bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=user.id,
            permissions=types.ChatPermissions(
                can_send_messages=True,
                can_send_media=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=True,
                can_invite_users=True,
                can_pin_messages=True
            )
        )
        bot.send_message(message.chat.id, f"✅ *{user.first_name}* размучен.", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, "❌ Ошибка: проверь права бота.")

# ---------- ПРЕДУПРЕЖДЕНИЯ ----------

@bot.message_handler(commands=["warn"])
def warn_user(message):
    if message.chat.type == "private":
        return
    if not is_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "⛔ Только для администраторов.")
        return
    if not message.reply_to_message:
        bot.reply_to(message, "⚠️ Ответь на сообщение пользователя.")
        return
    user = message.reply_to_message.from_user
    if user.id == bot.get_me().id:
        bot.reply_to(message, "😅 Нельзя выдать предупреждение боту.")
        return

    warns = add_warn(user.id, message.chat.id)
    bot.reply_to(
        message,
        f"⚠️ *Предупреждение выдано*\n\n👤 {user.first_name}\n📊 Всего: *{warns}*",
        parse_mode="Markdown"
    )

    if warns >= 3:
        try:
            bot.ban_chat_member(message.chat.id, user.id)
            bot.send_message(
                message.chat.id,
                f"🔨 *{user.first_name}* забанен (3 предупреждения).",
                parse_mode="Markdown"
            )
        except:
            bot.send_message(message.chat.id, "❌ Не удалось забанить – проверь права.")

@bot.message_handler(commands=["unwarn"])
def unwarn_user(message):
    if message.chat.type == "private":
        return
    if not is_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "⛔ Только для администраторов.")
        return
    if not message.reply_to_message:
        bot.reply_to(message, "⚠️ Ответь на сообщение пользователя.")
        return
    user = message.reply_to_message.from_user
    new_warns = remove_warn(user.id, message.chat.id)
    if new_warns == 0:
        bot.reply_to(message, f"✅ У *{user.first_name}* больше нет предупреждений.", parse_mode="Markdown")
    else:
        bot.reply_to(message, f"✅ Снято одно предупреждение. Осталось: *{new_warns}*.", parse_mode="Markdown")

@bot.message_handler(commands=["warnings"])
def warnings_command(message):
    if not message.reply_to_message:
        bot.reply_to(message, "⚠️ Ответь на сообщение пользователя.")
        return
    user = message.reply_to_message.from_user
    warns = get_warns(user.id, message.chat.id)
    bot.reply_to(
        message,
        f"👤 *{user.first_name}*\n⚠️ Предупреждений: *{warns}*",
        parse_mode="Markdown"
    )

# ========== ВСТАВКА: ФОНОВЫЙ ВЕБ-СЕРВЕР ДЛЯ RAILWAY ==========
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_http_server, daemon=True).start()
# =================================================================

# ========== ЗАПУСК ==========
print("Bot started")
try:
    bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
except Exception as e:
    print("Ошибка подключения:", e)
