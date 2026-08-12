from flask import Flask, request, jsonify
import sys
import os

# Menambahkan parent directory agar bisa mengimpor bot.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bot

app = Flask(__name__)

@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "Bot is running on Vercel!"})

@app.route('/api/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    if update:
        try:
            bot.handle_update(update)
        except Exception as e:
            print(f"Error handling update: {e}")
    return jsonify({"status": "ok"}), 200

# Vercel akan membaca variabel `app` ini secara otomatis
