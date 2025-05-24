from flask import Flask, jsonify
import os
import json
import subprocess
import psutil
from datetime import datetime
import telebot
from telebot import types
import random
import string
import threading
from waitress import serve

app = Flask(__name__)

# Configuration
TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = telebot.TeleBot(TOKEN)
ADMINS = os.getenv('ADMINS', '').split(',')

# File system setup
os.makedirs("scripts", exist_ok=True)
USER_DATA_FILE = "user_data.json"
if not os.path.exists(USER_DATA_FILE):
    with open(USER_DATA_FILE, "w") as f:
        json.dump({}, f)

# Thread safety
file_lock = threading.Lock()

def load_data():
    with file_lock:
        with open(USER_DATA_FILE, "r") as f:
            return json.load(f)

def save_data(data):
    with file_lock:
        with open(USER_DATA_FILE, "w") as f:
            json.dump(data, f, indent=4)

running_scripts = {}

def generate_script_id():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=8))

def is_admin(user_id):
    return str(user_id) in ADMINS

def cleanup_zombies():
    data = load_data()
    for user_id, scripts in list(data.items()):
        for script_id, script_data in list(scripts.items()):
            if script_data["status"] == "running":
                try:
                    process = psutil.Process(script_data["pid"])
                    if not process.is_running():
                        script_data["status"] = "stopped"
                except psutil.NoSuchProcess:
                    script_data["status"] = "stopped"
    save_data(data)

def run_script(user_id, script_id, script_path):
    data = load_data()
    if user_id not in data or script_id not in data[user_id]:
        return
    
    process = subprocess.Popen(["python", script_path])
    running_scripts[script_id] = process
    data[user_id][script_id]["pid"] = process.pid
    data[user_id][script_id]["status"] = "running"
    data[user_id][script_id]["start_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_data(data)

@bot.message_handler(commands=['start'])
def start(message):
    if is_admin(message.chat.id):
        bot.send_message(message.chat.id, "👑 *Admin Panel* 👑\n\n"
                         "You have full control over all scripts.\n\n"
                         "📋 *Admin Commands:*\n"
                         "/host - Upload script\n"
                         "/status - All running scripts\n"
                         "/stop <script_id> - Stop any script\n"
                         "/restart <script_id> - Restart any script\n"
                         "/list - List all scripts\n"
                         "/users - List all users\n"
                         "/killall - Stop all scripts", parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "🌟 *Welcome to Python Script Hosting Bot!* 🌟\n\n"
                         "Upload `.py` files to host and execute them.\n\n"
                         "📋 *Commands:*\n"
                         "/host - Upload script\n"
                         "/status - Your running scripts\n"
                         "/stop <script_id> - Stop your script\n"
                         "/restart <script_id> - Restart your script", parse_mode="Markdown")

@bot.message_handler(commands=['host'])
def host(message):
    bot.send_message(message.chat.id, "📤 Please upload a `.py` file:")

@bot.message_handler(commands=['status'])
def status(message):
    user_id = str(message.chat.id)
    data = load_data()
    
    if is_admin(message.chat.id):
        response = "👑 *All Running Scripts:* 👑\n\n"
        for uid, scripts in data.items():
            for script_id, script_data in scripts.items():
                if script_data["status"] == "running":
                    duration = datetime.now() - datetime.strptime(script_data["start_time"], "%Y-%m-%d %H:%M:%S")
                    response += f"👤 *User:* {uid}\n"
                    response += f"🆔 *ID:* `{script_id}`\n"
                    response += f"📂 *File:* `{script_data['file_name']}`\n"
                    response += f"⏱ *Uptime:* {str(duration).split('.')[0]}\n\n"
    else:
        response = "📊 *Your Running Scripts:*\n\n"
        if user_id in data:
            for script_id, script_data in data[user_id].items():
                if script_data["status"] == "running":
                    duration = datetime.now() - datetime.strptime(script_data["start_time"], "%Y-%m-%d %H:%M:%S")
                    response += f"🆔 *ID:* `{script_id}`\n"
                    response += f"📂 *File:* `{script_data['file_name']}`\n"
                    response += f"⏱ *Uptime:* {str(duration).split('.')[0]}\n\n"
    
    if response.count("\n") < 3:
        response = "💤 No running scripts found."
    
    bot.send_message(message.chat.id, response, parse_mode="Markdown")

@bot.message_handler(commands=['list'])
def list_scripts(message):
    if not is_admin(message.chat.id):
        bot.send_message(message.chat.id, "❌ Admin only command")
        return
    
    data = load_data()
    response = "📜 *All Scripts:* 📜\n\n"
    for uid, scripts in data.items():
        response += f"👤 *User:* {uid}\n"
        for script_id, script_data in scripts.items():
            status_emoji = "🟢" if script_data["status"] == "running" else "🔴"
            response += f"🆔 *ID:* `{script_id}`\n"
            response += f"📂 *File:* `{script_data['file_name']}`\n"
            response += f"🔄 *Status:* {status_emoji} {script_data['status'].capitalize()}\n"
            if "start_time" in script_data:
                response += f"⏱ *Started:* {script_data['start_time']}\n"
            response += "\n"
    
    bot.send_message(message.chat.id, response, parse_mode="Markdown")

@bot.message_handler(commands=['users'])
def list_users(message):
    if not is_admin(message.chat.id):
        bot.send_message(message.chat.id, "❌ Admin only command")
        return
    
    data = load_data()
    response = "👥 *Registered Users:* 👥\n\n"
    for uid in data.keys():
        response += f"👤 *User ID:* {uid}\n"
        running = sum(1 for s in data[uid].values() if s["status"] == "running")
        total = len(data[uid])
        response += f"📊 Scripts: {running} running / {total} total\n\n"
    
    bot.send_message(message.chat.id, response, parse_mode="Markdown")

@bot.message_handler(commands=['killall'])
def kill_all(message):
    if not is_admin(message.chat.id):
        bot.send_message(message.chat.id, "❌ Admin only command")
        return
    
    data = load_data()
    count = 0
    for uid, scripts in data.items():
        for script_id, script_data in list(scripts.items()):
            if script_data["status"] == "running":
                if script_id in running_scripts:
                    process = running_scripts[script_id]
                    try:
                        parent = psutil.Process(process.pid)
                        for child in parent.children(recursive=True):
                            child.kill()
                        parent.kill()
                    except psutil.NoSuchProcess:
                        pass
                    del running_scripts[script_id]
                script_data["status"] = "stopped"
                script_data["end_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                count += 1
    
    save_data(data)
    bot.send_message(message.chat.id, f"🛑 Stopped all {count} running scripts")

@bot.message_handler(commands=['stop'])
def stop(message):
    try:
        script_id = message.text.split()[1]
        user_id = str(message.chat.id)
        data = load_data()
        
        found = False
        if is_admin(message.chat.id):
            for uid, scripts in data.items():
                if script_id in scripts:
                    found = True
                    if script_id in running_scripts:
                        process = running_scripts[script_id]
                        try:
                            parent = psutil.Process(process.pid)
                            for child in parent.children(recursive=True):
                                child.kill()
                            parent.kill()
                        except psutil.NoSuchProcess:
                            pass
                        del running_scripts[script_id]
                    scripts[script_id]["status"] = "stopped"
                    scripts[script_id]["end_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    bot.send_message(message.chat.id, f"👑 Admin stopped script `{script_id}`", parse_mode="Markdown")
        elif user_id in data and script_id in data[user_id]:
            found = True
            if script_id in running_scripts:
                process = running_scripts[script_id]
                try:
                    parent = psutil.Process(process.pid)
                    for child in parent.children(recursive=True):
                        child.kill()
                    parent.kill()
                except psutil.NoSuchProcess:
                    pass
                del running_scripts[script_id]
            data[user_id][script_id]["status"] = "stopped"
            data[user_id][script_id]["end_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            bot.send_message(message.chat.id, f"🛑 Stopped your script `{script_id}`", parse_mode="Markdown")
        
        if not found:
            bot.send_message(message.chat.id, "❌ Script not found")
        else:
            save_data(data)
    except IndexError:
        bot.send_message(message.chat.id, "ℹ️ Usage: /stop <script_id>")

@bot.message_handler(commands=['restart'])
def restart(message):
    try:
        script_id = message.text.split()[1]
        user_id = str(message.chat.id)
        data = load_data()
        
        found = False
        if is_admin(message.chat.id):
            for uid, scripts in data.items():
                if script_id in scripts:
                    found = True
                    script_data = scripts[script_id]
                    if script_id in running_scripts:
                        process = running_scripts[script_id]
                        try:
                            parent = psutil.Process(process.pid)
                            for child in parent.children(recursive=True):
                                child.kill()
                            parent.kill()
                        except psutil.NoSuchProcess:
                            pass
                        del running_scripts[script_id]
                    
                    script_path = script_data["script_path"]
                    run_script(uid, script_id, script_path)
                    bot.send_message(message.chat.id, f"👑 Admin restarted script `{script_id}`", parse_mode="Markdown")
        elif user_id in data and script_id in data[user_id]:
            found = True
            script_data = data[user_id][script_id]
            if script_id in running_scripts:
                process = running_scripts[script_id]
                try:
                    parent = psutil.Process(process.pid)
                    for child in parent.children(recursive=True):
                        child.kill()
                    parent.kill()
                except psutil.NoSuchProcess:
                    pass
                del running_scripts[script_id]
            
            script_path = script_data["script_path"]
            run_script(user_id, script_id, script_path)
            bot.send_message(message.chat.id, f"🔄 Restarted your script `{script_id}`", parse_mode="Markdown")
        
        if not found:
            bot.send_message(message.chat.id, "❌ Script not found")
        else:
            save_data(data)
    except IndexError:
        bot.send_message(message.chat.id, "ℹ️ Usage: /restart <script_id>")

@bot.message_handler(content_types=['document'])
def handle_file(message):
    if not message.document.file_name.endswith('.py'):
        bot.send_message(message.chat.id, "❌ Only `.py` files accepted")
        return
    
    user_id = str(message.chat.id)
    file_id = message.document.file_id
    file_name = message.document.file_name
    script_id = generate_script_id()
    script_dir = os.path.join("scripts", user_id)
    os.makedirs(script_dir, exist_ok=True)
    script_path = os.path.join(script_dir, file_name)
    
    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    with open(script_path, 'wb') as f:
        f.write(downloaded_file)
    
    data = load_data()
    if user_id not in data:
        data[user_id] = {}
    
    data[user_id][script_id] = {
        "file_name": file_name,
        "script_path": script_path,
        "status": "pending",
        "upload_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_data(data)
    
    run_script(user_id, script_id, script_path)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    stop_btn = types.InlineKeyboardButton("🛑 Stop", callback_data=f"stop_{script_id}")
    restart_btn = types.InlineKeyboardButton("🔄 Restart", callback_data=f"restart_{script_id}")
    markup.add(stop_btn, restart_btn)
    
    bot.send_message(message.chat.id, f"✨ *Script Hosted Successfully!* ✨\n\n"
                    f"🆔 *ID:* `{script_id}`\n"
                    f"📂 *File:* `{file_name}`\n"
                    f"🔄 *Status:* 🟢 Running",
                    reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = str(call.message.chat.id)
    data = load_data()
    
    if call.data.startswith("stop_"):
        script_id = call.data.split("_")[1]
        
        if is_admin(call.message.chat.id):
            for uid, scripts in data.items():
                if script_id in scripts:
                    if script_id in running_scripts:
                        process = running_scripts[script_id]
                        try:
                            parent = psutil.Process(process.pid)
                            for child in parent.children(recursive=True):
                                child.kill()
                            parent.kill()
                        except psutil.NoSuchProcess:
                            pass
                        del running_scripts[script_id]
                    scripts[script_id]["status"] = "stopped"
                    scripts[script_id]["end_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    save_data(data)
                    
                    markup = types.InlineKeyboardMarkup()
                    restart_btn = types.InlineKeyboardButton("🔄 Restart", callback_data=f"restart_{script_id}")
                    markup.add(restart_btn)
                    
                    bot.edit_message_text(chat_id=call.message.chat.id,
                                        message_id=call.message.message_id,
                                        text=f"👑 *Admin Stopped Script*\n\n"
                                             f"🆔 *ID:* `{script_id}`\n"
                                             f"📂 *File:* `{scripts[script_id]['file_name']}`",
                                        reply_markup=markup,
                                        parse_mode="Markdown")
                    bot.answer_callback_query(call.id, "Script stopped")
                    return
        elif user_id in data and script_id in data[user_id]:
            if script_id in running_scripts:
                process = running_scripts[script_id]
                try:
                    parent = psutil.Process(process.pid)
                    for child in parent.children(recursive=True):
                        child.kill()
                    parent.kill()
                except psutil.NoSuchProcess:
                    pass
                del running_scripts[script_id]
            data[user_id][script_id]["status"] = "stopped"
            data[user_id][script_id]["end_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_data(data)
            
            markup = types.InlineKeyboardMarkup()
            restart_btn = types.InlineKeyboardButton("🔄 Restart", callback_data=f"restart_{script_id}")
            markup.add(restart_btn)
            
            bot.edit_message_text(chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                text=f"🛑 *Script Stopped*\n\n"
                                     f"🆔 *ID:* `{script_id}`\n"
                                     f"📂 *File:* `{data[user_id][script_id]['file_name']}`",
                                reply_markup=markup,
                                parse_mode="Markdown")
            bot.answer_callback_query(call.id, "Script stopped")
        else:
            bot.answer_callback_query(call.id, "Script not found")
    
    elif call.data.startswith("restart_"):
        script_id = call.data.split("_")[1]
        
        if is_admin(call.message.chat.id):
            for uid, scripts in data.items():
                if script_id in scripts:
                    script_data = scripts[script_id]
                    if script_id in running_scripts:
                        process = running_scripts[script_id]
                        try:
                            parent = psutil.Process(process.pid)
                            for child in parent.children(recursive=True):
                                child.kill()
                            parent.kill()
                        except psutil.NoSuchProcess:
                            pass
                        del running_scripts[script_id]
                    
                    script_path = script_data["script_path"]
                    run_script(uid, script_id, script_path)
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    stop_btn = types.InlineKeyboardButton("🛑 Stop", callback_data=f"stop_{script_id}")
                    restart_btn = types.InlineKeyboardButton("🔄 Restart", callback_data=f"restart_{script_id}")
                    markup.add(stop_btn, restart_btn)
                    
                    bot.edit_message_text(chat_id=call.message.chat.id,
                                        message_id=call.message.message_id,
                                        text=f"👑 *Admin Restarted Script*\n\n"
                                             f"🆔 *ID:* `{script_id}`\n"
                                             f"📂 *File:* `{script_data['file_name']}`\n"
                                             f"🔄 *Status:* 🟢 Running",
                                        reply_markup=markup,
                                        parse_mode="Markdown")
                    bot.answer_callback_query(call.id, "Script restarted")
                    return
        elif user_id in data and script_id in data[user_id]:
            script_data = data[user_id][script_id]
            if script_id in running_scripts:
                process = running_scripts[script_id]
                try:
                    parent = psutil.Process(process.pid)
                    for child in parent.children(recursive=True):
                        child.kill()
                    parent.kill()
                except psutil.NoSuchProcess:
                    pass
                del running_scripts[script_id]
            
            script_path = script_data["script_path"]
            run_script(user_id, script_id, script_path)
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            stop_btn = types.InlineKeyboardButton("🛑 Stop", callback_data=f"stop_{script_id}")
            restart_btn = types.InlineKeyboardButton("🔄 Restart", callback_data=f"restart_{script_id}")
            markup.add(stop_btn, restart_btn)
            
            bot.edit_message_text(chat_id=call.message.chat.id,
                                message_id=call.message.message_id,
                                text=f"🔄 *Script Restarted*\n\n"
                                     f"🆔 *ID:* `{script_id}`\n"
                                     f"📂 *File:* `{script_data['file_name']}`\n"
                                     f"🔄 *Status:* 🟢 Running",
                                reply_markup=markup,
                                parse_mode="Markdown")
            bot.answer_callback_query(call.id, "Script restarted")
        else:
            bot.answer_callback_query(call.id, "Script not found")

# Health check endpoint
@app.route('/')
def health_check():
    return jsonify({
        "status": "running",
        "bot": "active",
        "timestamp": datetime.now().isoformat()
    })

# Start bot polling in background
def run_bot():
    cleanup_zombies()
    print("🤖 Bot started polling...")
    bot.infinity_polling(none_stop=True, restart_on_change=True)

if __name__ == '__main__':
    # For local development
    from waitress import serve
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    serve(app, host="0.0.0.0", port=5000)