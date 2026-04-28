import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import cloudscraper
import json
from bs4 import BeautifulSoup
import logging
import os
import gzip
import brotli
import sqlite3
import time
from datetime import datetime

# ==========================================
# KONFIGURASI BOT
# ==========================================
BOT_TOKEN = "8612119364:AAH5LeV-b1DRatTJRiqzqdW0XMekuwy47vI"
ADMIN_IDS = [1219849116] 

# Konfigurasi Channel & Grup untuk Force Subscribe
REQUIRED_CHANNELS = [
    {
        "id": -1003823033713, 
        "name": "Channel Utama", 
        "link": "https://t.me/roseotpch"
    },
    {
        "id": "@roseotpgroup", 
        "name": "Grup Diskusi",  
        "link": "https://t.me/roseotpgroup"
    }
]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN)

# ==========================================
# SETUP DATABASE (SQLite) AMAN UNTUK RAILWAY
# ==========================================
def get_db():
    db_dir = '/app/data'
    if not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
        except Exception:
            db_dir = '.'
            
    db_path = os.path.join(db_dir, 'stok_nomor.db')
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS numbers (
            phone_number TEXT PRIMARY KEY,
            country TEXT,
            status TEXT DEFAULT 'available', 
            chat_id INTEGER,
            last_msg TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()
admin_states = {}

# ==========================================
# CLASS SCRAPER (Mengambil OTP & Nama App)
# ==========================================
class IVASSMSClient:
    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        self.base_url = "https://www.ivasms.com"
        self.logged_in = False
        self.csrf_token = None
        self.scraper.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36',
            'Accept-Encoding': 'gzip, deflate, br',
        })

    def decompress_response(self, response):
        encoding = response.headers.get('Content-Encoding', '').lower()
        content = response.content
        try:
            if encoding == 'gzip': content = gzip.decompress(content)
            elif encoding == 'br': content = brotli.decompress(content)
            return content.decode('utf-8', errors='replace')
        except Exception: return response.text

    def load_cookies(self, file_path="cookies.json"):
        try:
            with open(file_path, 'r') as file: return json.load(file)
        except Exception: return None

    def login_with_cookies(self, cookies_file="cookies.json"):
        cookies = self.load_cookies(cookies_file)
        if not cookies: return False
        
        if isinstance(cookies, list):
            for c in cookies:
                if 'name' in c and 'value' in c:
                    self.scraper.cookies.set(c['name'], c['value'], domain="www.ivasms.com")
        elif isinstance(cookies, dict):
            for k, v in cookies.items():
                self.scraper.cookies.set(k, v, domain="www.ivasms.com")
                
        try:
            response = self.scraper.get(f"{self.base_url}/portal/sms/received", timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(self.decompress_response(response), 'html.parser')
                csrf_input = soup.find('input', {'name': '_token'})
                if csrf_input:
                    self.csrf_token = csrf_input.get('value')
                    self.logged_in = True
                    return True
            return False
        except Exception: return False

    def get_otp_message(self, phone_number, phone_range, date_str):
        if not self.logged_in or not self.csrf_token: return None
        try:
            payload = {'_token': self.csrf_token, 'start': date_str, 'end': date_str, 'Number': phone_number, 'Range': phone_range}
            headers = {'X-Requested-With': 'XMLHttpRequest'}
            response = self.scraper.post(f"{self.base_url}/portal/sms/received/getsms/number/sms", data=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(self.decompress_response(response), 'html.parser')
                
                # Menggunakan target HTML baru dari Inspect Element Abang
                msg_elem = soup.find('div', class_='msg-text')
                sender_elem = soup.find('span', class_='cli-tag')
                
                message = msg_elem.text.strip() if msg_elem else None
                sender = sender_elem.text.strip() if sender_elem else "App"
                
                # Mengembalikan 2 nilai sekaligus: Nama App dan Isi Pesan
                if message:
                    return sender, message
            return None
        except Exception: return None

client = IVASSMSClient()

# ==========================================
# HELPER: Pengecekan Join Channel
# ==========================================
def is_user_member(user_id):
    if not REQUIRED_CHANNELS: return True 
    for channel in REQUIRED_CHANNELS:
        try:
            member = bot.get_chat_member(channel["id"], user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False
        except Exception as e:
            print(f"\n❌ ERROR GAGAL CEK MEMBER DI {channel['id']} ❌")
            print(f"Alasan: {e}\n")
            return False 
    return True

# ==========================================
# HANDLER USER (Menu Utama)
# ==========================================
@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    
    # CEK JOIN CHANNEL
    if not is_user_member(user_id):
        markup = InlineKeyboardMarkup()
        for ch in REQUIRED_CHANNELS:
            markup.add(InlineKeyboardButton(f"🔗 Join {ch['name']}", url=ch['link']))
        markup.add(InlineKeyboardButton("✅ Saya Sudah Join", callback_data="cek_join"))
        
        bot.send_message(message.chat.id, 
            "⚠️ *AKSES DITOLAK*\n\nAnda harus bergabung ke channel dan grup resmi kami terlebih dahulu untuk menggunakan bot ini.", 
            reply_markup=markup, parse_mode='Markdown')
        return

    show_main_menu(message.chat.id, message.from_user.first_name)

@bot.callback_query_handler(func=lambda call: call.data == 'cek_join')
def handle_cek_join(call):
    if not is_user_member(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Anda belum bergabung di semua channel/grup!", show_alert=True)
    else:
        bot.delete_message(call.message.chat.id, call.message.message_id)
        show_main_menu(call.message.chat.id, call.from_user.first_name)

def show_main_menu(chat_id, first_name):
    teks = f"👋 *Halo {first_name}!*\n\n🎁 Selamat datang di *Bot Nomor Virtual Gratis*\n\n⚡ Nomor aktif & siap pakai\n⚡ Bisa digunakan untuk berbagai kebutuhan verifikasi\n⚡ OTP langsung masuk ke bot\n\n🔥 *Gratis & praktis — langsung mulai sekarang!*\n\n👇 Pilih menu di bawah\n📖 Butuh panduan? Klik tombol *Panduan*"
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("📱 Get Number", callback_data="menu_get_number"))
    markup.row(
        InlineKeyboardButton("📖 Panduan", callback_data="menu_panduan"),
        InlineKeyboardButton("📜 Histori OTP", callback_data="menu_histori")
    )
    bot.send_message(chat_id, teks, reply_markup=markup, parse_mode='Markdown')

# --- SUB-MENU USER (Anti-Crash Double Click) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('menu_'))
def handle_user_menu(call):
    chat_id = call.message.chat.id
    menu = call.data.split('_')[1]

    try:
        if menu == "panduan":
            teks = "📖 *PANDUAN PENGGUNAAN*\n\n1. Klik *Get Number* lalu pilih negara.\n2. Masukkan nomor yang diberikan ke aplikasi.\n3. Jika kode sudah dikirim, klik tombol *Cek OTP* di bot ini.\n4. OTP akan muncul di layar."
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Kembali", callback_data="menu_main"))
            bot.edit_message_text(teks, chat_id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')

        elif menu == "histori":
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT phone_number, last_msg FROM numbers WHERE chat_id = ? AND last_msg IS NOT NULL", (chat_id,))
            rows = cursor.fetchall()
            conn.close()
            
            if not rows:
                teks = "📜 *HISTORI OTP*\n\nBelum ada histori OTP yang masuk."
            else:
                teks = "📜 *HISTORI OTP TERAKHIR*\n\n"
                for r in rows:
                    teks += f"📱 `{r['phone_number']}`\n💬 {r['last_msg']}\n\n"
                    
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Kembali", callback_data="menu_main"))
            bot.edit_message_text(teks, chat_id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')

        elif menu == "main":
            show_main_menu(chat_id, call.from_user.first_name)
            bot.delete_message(chat_id, call.message.message_id)

        elif menu == "get": # get_number
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT country FROM numbers WHERE status = 'available'")
            countries = [row['country'] for row in cursor.fetchall()]
            conn.close()
            
            if len(countries) == 0:
                markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Kembali", callback_data="menu_main"))
                bot.edit_message_text("❌ Maaf, stok nomor saat ini sedang kosong.", chat_id, call.message.message_id, reply_markup=markup)
            else:
                markup = InlineKeyboardMarkup()
                for country in countries:
                    markup.add(InlineKeyboardButton(text=country, callback_data=f"country_{country}"))
                markup.add(InlineKeyboardButton("🔙 Kembali", callback_data="menu_main"))
                bot.edit_message_text("Pilih negara yang Anda inginkan:", chat_id, call.message.message_id, reply_markup=markup)
                
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" in str(e):
            bot.answer_callback_query(call.id, "Sudah ditampilkan.")
        else:
            logger.error(f"Telegram API Error: {e}")

# ==========================================
# ALUR AMBIL NOMOR & CEK OTP (User)
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('country_'))
def handle_country_selection(call):
    country = call.data.replace('country_', '')
    chat_id = call.message.chat.id
    
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. DAUR ULANG: Kembalikan nomor lama yang belum dapet OTP ke 'available'
    cursor.execute("UPDATE numbers SET status = 'available', chat_id = NULL WHERE status = 'assigned' AND chat_id = ?", (chat_id,))
    
    # 2. AMBIL BARU: Cari 5 nomor baru dari stok available
    cursor.execute("SELECT phone_number FROM numbers WHERE status = 'available' AND country = ? LIMIT 5", (country,))
    rows = cursor.fetchall()
    
    if not rows:
        bot.edit_message_text(f"❌ Maaf, stok nomor untuk {country} baru saja habis.", chat_id, call.message.message_id)
        conn.commit()
        conn.close()
        return
        
    assigned_numbers = [row['phone_number'] for row in rows]
    # 3. KUNCI (LOCK): Set nomor ini menjadi 'assigned'
    for num in assigned_numbers:
        cursor.execute("UPDATE numbers SET status = 'assigned', chat_id = ? WHERE phone_number = ?", (chat_id, num))
    conn.commit()
    conn.close()
    
    teks = f"🚀 *READY! NOMOR SIAP DIPAKAI*\n\n"
    teks += f"🌍 {country}\n"
    teks += "━━━━━━━━━━━━━━━\n\n"

    for num in assigned_numbers:
        teks += f"📱 `{num}`\n"

    teks += "\n━━━━━━━━━━━━━━━\n"
    teks += "⚡ Cepat & langsung bisa digunakan\n"
    teks += "📩 OTP masuk real-time ke bot\n\n"
    teks += "🔥 Klik tombol di bawah untuk ambil OTP"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="🔄 Cek OTP", callback_data="cek_otp_sekarang"))
    markup.add(InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_main"))
    
    bot.edit_message_text(teks, chat_id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data == 'cek_otp_sekarang')
def handle_cek_otp(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    
    temp_markup = InlineKeyboardMarkup().add(InlineKeyboardButton(text="⏳ Loading...", callback_data="ignore"))
    try:
        bot.edit_message_text("⏳ _Sedang mengecek code OTP.._", chat_id, msg_id, reply_markup=temp_markup, parse_mode='Markdown')
    except Exception: pass

    if not client.logged_in: client.login_with_cookies()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT phone_number, country FROM numbers WHERE status = 'assigned' AND chat_id = ?", (chat_id,))
    user_numbers = cursor.fetchall()
    
    if not user_numbers:
        bot.edit_message_text("❌ Anda belum memiliki nomor aktif.", chat_id, msg_id)
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_main"))
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=markup)
        conn.close()
        return

    # FORMAT TANGGAL YANG BENAR (YYYY-MM-DD)
    today_str = datetime.now().strftime("%Y-%m-%d")
    pesan_otp = []

    for row in user_numbers:
        phone, country_range = row['phone_number'], row['country']
        hasil_sms = client.get_otp_message(phone, country_range, today_str)
        
        # JIKA OTP DITEMUKAN
        if hasil_sms:
            sender, msg = hasil_sms
            pesan_otp.append(f"📱 *{phone}*\n🏢 App: *{sender}*\n💬 `{msg}`")
            # 4. BURN (HANGUSKAN): Jika berhasil, ubah status ke 'used'
            cursor.execute("UPDATE numbers SET last_msg = ?, status = 'used' WHERE phone_number = ?", (msg, phone))
        time.sleep(1) 
    
    conn.commit()
    conn.close()
    
    current_time = datetime.now().strftime("%H:%M:%S")

    if pesan_otp:
        balasan = "🔔 *OTP DITERIMA!*\n\n" + "\n\n━━━━━━━━━━━━━━━\n\n".join(pesan_otp) + f"\n\n_Update: {current_time}_"
    else:
        balasan = f"⚠️ *Belum ada kode OTP masuk.*\nPastikan Anda sudah meminta kode dan tunggu beberapa detik.\n\n_Cek Terakhir: {current_time}_"

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="🔄 Cek Ulang OTP", callback_data="cek_otp_sekarang"))
    markup.add(InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_main"))
    
    try:
        bot.edit_message_text(balasan, chat_id, msg_id, reply_markup=markup, parse_mode='Markdown')
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" in str(e):
            bot.answer_callback_query(call.id, "Sudah di-refresh, belum ada perubahan OTP.")

# ==========================================
# HANDLER ADMIN DASHBOARD
# ==========================================
@bot.message_handler(commands=['admin'])
def handle_admin(message):
    if message.chat.id not in ADMIN_IDS: return
    show_admin_menu(message.chat.id)

def show_admin_menu(chat_id):
    teks = "🛠 *DASHBOARD ADMIN*\n\nSilakan pilih menu manajemen stok:"
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("➕ Tambah Stok", callback_data="adm_tambah"),
               InlineKeyboardButton("📊 Cek Stok", callback_data="adm_cek"))
    markup.row(InlineKeyboardButton("🗑 Hapus Terpakai", callback_data="adm_hapus_terpakai"),
               InlineKeyboardButton("🧹 Hapus per Negara", callback_data="adm_hapus_negara"))
    bot.send_message(chat_id, teks, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith('adm_'))
def handle_admin_menu(call):
    chat_id = call.message.chat.id
    action = call.data.split('_')[1]

    if action == "tambah":
        msg = bot.send_message(chat_id, "Masukkan nama **Negara** (Contoh: VENEZUELA 27):", parse_mode='Markdown')
        bot.register_next_step_handler(msg, process_admin_country)
    
    elif action == "cek":
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT country, COUNT(*) as jml FROM numbers WHERE status = 'available' GROUP BY country")
        rows = cursor.fetchall()
        conn.close()
        
        if not rows: teks = "📊 Stok nomor kosong."
        else:
            teks = "📊 *STOK NOMOR TERSEDIA*\n\n"
            for r in rows: teks += f"• {r['country']}: *{r['jml']}* nomor\n"
        bot.send_message(chat_id, teks, parse_mode='Markdown')

    elif action == "hapus":
        if call.data == "adm_hapus_terpakai":
            conn = get_db()
            cursor = conn.cursor()
            # HANYA MENGHAPUS NOMOR YANG BENAR-BENAR SUDAH DAPAT OTP ('used')
            cursor.execute("DELETE FROM numbers WHERE status = 'used'")
            jml = cursor.rowcount
            conn.commit()
            conn.close()
            bot.send_message(chat_id, f"✅ Berhasil menghapus *{jml}* nomor yang sudah berhasil dipakai (dapat OTP).", parse_mode='Markdown')
        
        elif call.data == "adm_hapus_negara":
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT country FROM numbers")
            countries = [row['country'] for row in cursor.fetchall()]
            conn.close()
            
            if not countries:
                bot.send_message(chat_id, "Database kosong.")
                return
                
            markup = InlineKeyboardMarkup()
            for c in countries:
                markup.add(InlineKeyboardButton(f"Hapus {c}", callback_data=f"delcountry_{c}"))
            bot.send_message(chat_id, "Pilih negara yang akan dihapus SELURUH nomornya:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('delcountry_'))
def handle_del_country(call):
    country = call.data.replace('delcountry_', '')
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM numbers WHERE country = ?", (country,))
    jml = cursor.rowcount
    conn.commit()
    conn.close()
    bot.edit_message_text(f"✅ Berhasil menghapus *{jml}* nomor dari negara *{country}*.", call.message.chat.id, call.message.message_id, parse_mode='Markdown')

def process_admin_country(message):
    country = message.text.strip()
    admin_states[message.chat.id] = {'country': country}
    msg = bot.reply_to(message, f"Negara: `{country}`\nKirimkan daftar nomor (pisahkan per baris):", parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_admin_numbers)

def process_admin_numbers(message):
    if message.chat.id not in admin_states: return
    country = admin_states[message.chat.id]['country']
    clean_numbers = [num.strip() for num in message.text.split('\n') if num.strip() != ""]
    
    conn = get_db()
    cursor = conn.cursor()
    success = 0
    for num in clean_numbers:
        try:
            cursor.execute("INSERT OR IGNORE INTO numbers (phone_number, country, status) VALUES (?, ?, 'available')", (num, country))
            if cursor.rowcount > 0: success += 1
        except Exception: pass
    conn.commit()
    conn.close()
    del admin_states[message.chat.id]
    
    bot.reply_to(message, f"✅ Sukses menambahkan *{success}* stok untuk *{country}*.", parse_mode='Markdown')

# ==========================================
# JALANKAN PROGRAM
# ==========================================
if __name__ == '__main__':
    if not os.path.exists("cookies.json"):
        print("⚠️ PERINGATAN: cookies.json tidak ditemukan!")
    else:
        client.login_with_cookies("cookies.json")
    print("🤖 Bot Berjalan...")
    bot.infinity_polling()
