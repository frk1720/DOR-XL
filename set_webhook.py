import os
import requests
from dotenv import load_dotenv
import sys

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")

if not BOT_TOKEN:
    print("BOT_TOKEN tidak ditemukan di .env")
    sys.exit(1)

if len(sys.argv) < 2:
    print("Gunakan: python set_webhook.py <URL_VERCEL_ANDA>")
    print("Contoh: python set_webhook.py https://my-bot.vercel.app")
    sys.exit(1)

url = sys.argv[1].rstrip("/")
webhook_url = f"{url}/api/webhook"

api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
print(f"Mengatur webhook ke: {webhook_url}")

try:
    res = requests.post(api_url, json={"url": webhook_url})
    print(res.json())
except Exception as e:
    print(f"Error: {e}")
