import asyncio
import os
import re
import shutil
import sqlite3
import time
import uuid
import zipfile
from telethon import Button, TelegramClient, events
from telethon.sessions import StringSession

# --- إعدادات بوت البيع ---
BOT_API_ID = 23032698
BOT_API_HASH = "99ad65a5fcd38203621cb20acd2aaba5"
BOT_TOKEN = "8968047291:AAHs7bB2VNfIn2Aa44MrwaWfceQgtbiGhnw"
ADMIN_ID = 1407216610

CHECK_INTERVAL_SECONDS = 30
CONNECT_TIMEOUT = 10

SESSIONS_DIR = "./sessions/"
TEMP_DIR = "./temp_extract/"
os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

buy_lock = asyncio.Lock()
db_lock = asyncio.Lock()
last_otp_request = {}
user_login_state = {}

bot_client = TelegramClient("bot_session", BOT_API_ID, BOT_API_HASH)

COUNTRY_CODES = {
    "964": ("العراق", "🇮🇶"), "966": ("السعودية", "🇸🇦"), "967": ("اليمن", "🇾🇪"),
    "20": ("مصر", "🇪🇬"), "962": ("الأردن", "🇯🇴"), "961": ("لبنان", "🇱🇧"),
    "963": ("سوريا", "🇸🇾"), "970": ("فلسطين", "🇵🇸"), "965": ("الكويت", "🇰🇼"),
    "971": ("الإمارات", "🇦🇪"), "974": ("قطر", "🇶🇦"), "973": ("البحرين", "🇧🇭"),
    "968": ("عُمان", "🇴🇲"), "212": ("المغرب", "🇲🇦"), "213": ("الجزائر", "🇩🇿"),
    "216": ("تونس", "🇹🇳"), "218": ("ليبيا", "🇱🇾"), "249": ("السودان", "🇸🇩"),
    "252": ("الصومال", "🇸🇴"), "253": ("جيبوتي", "🇩🇯"), "222": ("موريتانيا", "🇲🇷"),
    "269": ("جزر القمر", "🇰🇲"), "90": ("تركيا", "🇹🇷"), "98": ("إيران", "🇮🇷"),
    "91": ("الهند", "🇮🇳"), "92": ("باكستان", "🇵🇰"), "880": ("بنغلاديش", "🇧🇩"),
    "86": ("الصين", "🇨🇳"), "81": ("اليابان", "🇯🇵"), "82": ("كوريا الجنوبية", "🇰🇷"),
    "62": ("إندونيسيا", "🇮🇩"), "60": ("ماليزيا", "🇲🇾"), "63": ("الفلبين", "🇵🇭"),
    "66": ("تايلاند", "🇹🇭"), "84": ("فيتنام", "🇻🇳"), "44": ("المملكة المتحدة", "🇬🇧"),
    "49": ("ألمانيا", "🇩🇪"), "33": ("فرنسا", "🇫🇷"), "39": ("إيطاليا", "🇮🇹"),
    "34": ("إسبانيا", "🇪🇸"), "7": ("روسيا / كازاخستان", "🇷🇺"), "380": ("أوكرانيا", "🇺🇦"),
    "48": ("بولندا", "🇵🇱"), "31": ("هولندا", "🇳🇱"), "32": ("بلجيكا", "🇧🇪"),
    "41": ("سويسرا", "🇨🇭"), "46": ("السويد", "🇸🇪"), "47": ("النرويج", "🇳🇴"), "358": ("فنلندا", "🇫🇮"),
    "1": ("أمريكا / كندا", "🇺🇸"), "52": ("المكسيك", "🇲🇽"), "55": ("البرازيل", "🇧🇷"),
    "54": ("الأرجنتين", "🇦🇷"), "57": ("كولومبيا", "🇨🇴")
}

def init_db():
    conn = sqlite3.connect("shop.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE,
            session_string TEXT,
            country_code TEXT,
            country_name TEXT,
            flag TEXT,
            price INTEGER DEFAULT 1000,
            password_2fa TEXT DEFAULT 'm',
            status TEXT DEFAULT 'active'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('default_price', '1000')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('default_2fa', 'm')")
    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect("shop.db")
    conn.row_factory = sqlite3.Row
    return conn

def get_country_info(phone):
    clean_phone = re.sub(r"\D", "", phone)
    for code in sorted(COUNTRY_CODES.keys(), key=lambda x: len(x), reverse=True):
        if clean_phone.startswith(code):
            cname, flag = COUNTRY_CODES[code]
            return code, cname, flag
    return "other", "دول أخرى", "🌐"

async def check_session_validity(session_string):
    client = TelegramClient(StringSession(session_string), BOT_API_ID, BOT_API_HASH)
    try:
        await asyncio.wait_for(client.connect(), timeout=CONNECT_TIMEOUT)
        if not await client.is_user_authorized():
            await client.disconnect()
            return False, "غير مخول"
        me = await client.get_me()
        await client.disconnect()
        return True, me
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        return False, str(e)

async def check_all_sessions_loop():
    while True:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT id, phone, session_string FROM sessions WHERE status = 'active'")
            active_sessions = cursor.fetchall()
            conn.close()

            for sess in active_sessions:
                s_id, phone, s_str = sess["id"], sess["phone"], sess["session_string"]
                is_valid, _ = await check_session_validity(s_str)
                if not is_valid:
                    async with db_lock:
                        c = get_db()
                        c.execute("UPDATE sessions SET status = 'dead' WHERE id = ?", (s_id,))
                        c.commit()
                        c.close()
                    print(f"⚠️ الرقم {phone} أصبح معطلاً (Dead) وتم حذفه من العرض.")
                await asyncio.sleep(1)
        except Exception as e:
            print(f"خطأ في الفحص الدوري: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

# --- واجهات المستخدم للبوت ---
@bot_client.on(events.NewMessage(pattern=r"/start"))
async def start_handler(event):
    user_id = event.sender_id
    async with db_lock:
        conn = get_db()
        conn.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)", (user_id,))
        conn.commit()
        conn.close()

    buttons = [
        [Button.inline("🛒 شراء حسابات", b"buy_menu"), Button.inline("👤 حسابي", b"my_account")],
        [Button.inline("➕ شحن رصيد", b"recharge_balance")]
    ]
    if user_id == ADMIN_ID:
        buttons.append([Button.inline("⚙️ لوحة التحكم (الأدمن)", b"admin_panel")])

    await event.respond("👋 **أهلاً بك في متجر الحسابات والسيشنات!**\nاختر من القائمة أدناه:", buttons=buttons)

@bot_client.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data
    user_id = event.sender_id

    if data == b"main_menu":
        buttons = [
            [Button.inline("🛒 شراء حسابات", b"buy_menu"), Button.inline("👤 حسابي", b"my_account")],
            [Button.inline("➕ شحن رصيد", b"recharge_balance")]
        ]
        if user_id == ADMIN_ID:
            buttons.append([Button.inline("⚙️ لوحة التحكم (الأدمن)", b"admin_panel")])
        await event.edit("👋 **القائمة الرئيسية:**", buttons=buttons)

    elif data == b"my_account":
        conn = get_db()
        row = conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        conn.close()
        bal = row["balance"] if row else 0
        text = f"👤 **معلومات حسابك:**\n\n🆔 الآيدي: `{user_id}`\n💰 الرصيد الحالي: `{bal}` نقطة/دينار"
        buttons = [[Button.inline("🔙 رجوع", b"main_menu")]]
        await event.edit(text, buttons=buttons)

    elif data == b"recharge_balance":
        await event.edit(f"➕ **لشحن رصيدك، يرجى التواصل مع الدعم أو الأدمن:**\n🆔 الأدمن: [{ADMIN_ID}](tg://user?id={ADMIN_ID})", buttons=[[Button.inline("🔙 رجوع", b"main_menu")]])

    elif data == b"buy_menu":
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT country_code, country_name, flag, price, COUNT(*) as count FROM sessions WHERE status = 'active' GROUP BY country_code")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await event.edit("❌ **لا توجد حسابات متاحة للبيع حالياً.**", buttons=[[Button.inline("🔙 رجوع", b"main_menu")]])
            return

        buttons = []
        for r in rows:
            btn_text = f"{r['flag']} {r['country_name']} (+{r['country_code']}) - {r['price']} ن (المتوفر: {r['count']})"
            buttons.append([Button.inline(btn_text, f"cat_{r['country_code']}".encode())])
        buttons.append([Button.inline("🔙 رجوع", b"main_menu")])
        await event.edit("🛒 **اختر الدولة لشراء الحساب:**", buttons=buttons)

    elif data.startswith(b"cat_"):
        code = data.decode().split("_")[1]
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT country_name, flag, price, COUNT(*) as count FROM sessions WHERE country_code = ? AND status = 'active'", (code,))
        row = cursor.fetchone()
        conn.close()

        if not row or row["count"] == 0:
            await event.edit("❌ **عذراً، نفذت الحسابات لهذه الدولة.**", buttons=[[Button.inline("🔙 رجوع", b"buy_menu")]])
            return

        text = f"تفاصيل الفئة:\nالدولة: {row['flag']} {row['country_name']}\nالسعر: {row['price']} نقطة\nالمتوفر: {row['count']} حساب"
        buttons = [
            [Button.inline("✅ تأكيد الشراء", f"confirm_buy_{code}".encode())],
            [Button.inline("🔙 رجوع", b"buy_menu")]
        ]
        await event.edit(text, buttons=buttons)

    elif data.startswith(b"confirm_buy_"):
        code = data.decode().split("_")[2]
        async with buy_lock:
            conn = get_db()
            cursor = conn.cursor()
            user_row = cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
            user_bal = user_row["balance"] if user_row else 0

            sess_row = cursor.execute("SELECT * FROM sessions WHERE country_code = ? AND status = 'active' LIMIT 1", (code,)).fetchone()

            if not sess_row:
                conn.close()
                await event.edit("❌ **عذراً، نفذت الحسابات لهذه الدولة لحظة الشراء.**", buttons=[[Button.inline("🔙 رجوع", b"buy_menu")]])
                return

            price = sess_row["price"]
            if user_bal < price:
                conn.close()
                await event.edit(f"❌ **رصيدك غير كافٍ!**\nرصيدك: {user_bal} | المطلوب: {price}", buttons=[[Button.inline("➕ شحن رصيد", b"recharge_balance"), Button.inline("🔙 رجوع", b"buy_menu")]])
                return

            sess_id = sess_row["id"]
            phone = sess_row["phone"]
            sess_str = sess_row["session_string"]
            pwd_2fa = sess_row["password_2fa"]

            is_valid, _ = await check_session_validity(sess_str)
            if not is_valid:
                cursor.execute("UPDATE sessions SET status = 'dead' WHERE id = ?", (sess_id,))
                conn.commit()
                conn.close()
                await event.edit("⚠️ **الحساب المختار كان معطلاً. تم استبعاده، يرجى المحاولة مرة أخرى.**", buttons=[[Button.inline("🔄 محاولة مجدداً", f"cat_{code}".encode())]])
                return

            new_bal = user_bal - price
            cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_bal, user_id))
            cursor.execute("UPDATE sessions SET status = 'sold' WHERE id = ?", (sess_id,))
            conn.commit()
            conn.close()

            login_key = str(uuid.uuid4())[:8]
            user_login_state[login_key] = {"session_string": sess_str, "phone": phone, "password": pwd_2fa}

            success_msg = f"""
🎉 **تم الشراء بنجاح!**

📱 **رقم الهاتف:** `{phone}`
🔑 **كلمة سر التحقق بخطوتين (2FA):** `{pwd_2fa}`
💰 **الرصيد المتبقي:** `{new_bal}`

اضغط على الزر أدناه عند طلب الكود لجلبه مباشرة!
"""
            buttons = [
                [Button.inline("📩 طلب كود تسجيل الدخول (OTP)", f"get_otp_{login_key}".encode())],
                [Button.inline("🏠 القائمة الرئيسية", b"main_menu")]
            ]
            await event.edit(success_msg, buttons=buttons)

    elif data.startswith(b"get_otp_"):
        key = data.decode().split("_")[2]
        if key not in user_login_state:
            await event.answer("⚠️️ انتهت جلسة طلب الكود هذه أو غير صالحة.", alert=True)
            return

        now = time.time()
        if user_id in last_otp_request and (now - last_otp_request[user_id]) < 5:
            await event.answer("⏳ يرجى الانتظار بضع ثوانٍ قبل طلب الكود مجدداً.", alert=True)
            return
        last_otp_request[user_id] = now

        info = user_login_state[key]
        sess_str = info["session_string"]

        await event.answer("🔍 جاري البحث عن كود التحقق...", alert=False)
        client = TelegramClient(StringSession(sess_str), BOT_API_ID, BOT_API_HASH)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                await event.respond("❌ **تعذر الدخول للحساب (قد يكون تم تسجيل الخروج من الجهاز الآخر).**")
                await client.disconnect()
                return

            messages = await client.get_messages(777000, limit=3)
            otp_code = None
            for m in messages:
                if m.text:
                    match = re.search(r"\b\d{5,6}\b", m.text)
                    if match:
                        otp_code = match.group(0)
                        break

            await client.disconnect()

            if otp_code:
                await event.respond(f"🔑 **كود التحقق الخاص بك هو:** `{otp_code}`\n🔒 **كلمة سر 2FA:** `{info['password']}`")
            else:
                await event.respond("⏳ **لم يصل كود تحقق جديد بعد. أعد الطلب بعد لحظات من إرسال Telegram للكود.**")
        except Exception as e:
            try:
                await client.disconnect()
            except Exception:
                pass
            await event.respond(f"❌ **حدث خطأ أثناء جلب الكود:** {e}")

    # --- لوحة الأدمن ---
    elif data == b"admin_panel" and user_id == ADMIN_ID:
        conn = get_db()
        c = conn.cursor()
        total_users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active_sess = c.execute("SELECT COUNT(*) FROM sessions WHERE status = 'active'").fetchone()[0]
        sold_sess = c.execute("SELECT COUNT(*) FROM sessions WHERE status = 'sold'").fetchone()[0]
        dead_sess = c.execute("SELECT COUNT(*) FROM sessions WHERE status = 'dead'").fetchone()[0]
        conn.close()

        text = f"""
⚙️️ **لوحة تحكم الأدمن:**

👥 عدد المستخدمين: `{total_users}`
🟢 السيشنات الشغالة: `{active_sess}`
🛍️ السيشنات المباعة: `{sold_sess}`
🔴 السيشنات المعطلة: `{dead_sess}`
"""
        buttons = [
            [Button.inline("➕ إضافة رصيد لمستخدم", b"admin_add_bal"), Button.inline("📂 رفع ملفات (.session/.zip)", b"admin_upload_sessions")],
            [Button.inline("⚙ ضبط السعر و password الأفتراضي", b"admin_settings")],
            [Button.inline("🔙 رجوع", b"main_menu")]
        ]
        await event.edit(text, buttons=buttons)

    elif data == b"admin_add_bal" and user_id == ADMIN_ID:
        await event.edit("إضافة رصيد:\nأرسل الأمر بالتنسيق التالي:\n`/add_balance [id] [points]`\nمثال:\n`/add_balance 1407216610 5000`", buttons=[[Button.inline("🔙 رجوع", b"admin_panel")]])

    elif data == b"admin_upload_sessions" and user_id == ADMIN_ID:
        await event.edit("📂 **رفع الحسابات:**\nأرسل الآن ملف `.session` أو `.zip` يحتوي على جلسات.\nالبوت سيقوم بفحص الجلسات وإضافتها للمتجر تلقائياً.", buttons=[[Button.inline("🔙 رجوع", b"admin_panel")]])

    elif data == b"admin_settings" and user_id == ADMIN_ID:
        conn = get_db()
        c = conn.cursor()
        dp = c.execute("SELECT value FROM settings WHERE key='default_price'").fetchone()["value"]
        d2fa = c.execute("SELECT value FROM settings WHERE key='default_2fa'").fetchone()["value"]
        conn.close()
        text = f"⚙️ ** الإعدادات الافتراضية:**\n\n💵 السعر الافتراضي: `{dp}`\n🔒 كلمة السر (2FA) الافتراضية: `{d2fa}`\n\nلتعديلهم أرسل:\n`/set_price [السعر]`\n`/set_2fa [كلمة_السر]`"
        await event.edit(text, buttons=[[Button.inline("🔙 رجوع", b"admin_panel")]])

# --- أوامر الأدمن المباشرة ---
@bot_client.on(events.NewMessage(from_users=ADMIN_ID, pattern=r"/add_balance (\d+) (\d+)"))
async def add_balance_cmd(event):
    target_id = int(event.pattern_match.group(1))
    amount = int(event.pattern_match.group(2))
    async with db_lock:
        conn = get_db()
        conn.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)", (target_id,))
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
        conn.commit()
        conn.close()
    await event.respond(f"✅ تم إضافة `{amount}` نقطة إلى المستخدم `{target_id}` بنجاح.")

@bot_client.on(events.NewMessage(from_users=ADMIN_ID, pattern=r"/set_price (\d+)"))
async def set_price_cmd(event):
    price = event.pattern_match.group(1)
    async with db_lock:
        conn = get_db()
        conn.execute("UPDATE settings SET value = ? WHERE key = 'default_price'", (price,))
        conn.commit()
        conn.close()
    await event.respond(f"✅ تم تعديل السعر الافتراضي إلى `{price}`.")

@bot_client.on(events.NewMessage(from_users=ADMIN_ID, pattern=r"/set_2fa (.+)"))
async def set_2fa_cmd(event):
    pwd = event.pattern_match.group(1).strip()
    async with db_lock:
        conn = get_db()
        conn.execute("UPDATE settings SET value = ? WHERE key = 'default_2fa'", (pwd,))
        conn.commit()
        conn.close()
    await event.respond(f"✅ تم تعديل كلمة سر 2FA الافتراضية إلى `{pwd}`.")

# --- استقبال الملفات (.session / .zip) من الأدمن ---
@bot_client.on(events.NewMessage(from_users=ADMIN_ID, func=lambda e: e.file))
async def process_uploaded_files(event):
    conn = get_db()
    c = conn.cursor()
    dp = int(c.execute("SELECT value FROM settings WHERE key='default_price'").fetchone()["value"])
    d2fa = c.execute("SELECT value FROM settings WHERE key='default_2fa'").fetchone()["value"]
    conn.close()

    status_msg = await event.respond("⏳ **جاري معالجة الملفات المرفوعة...**")
    file_name = event.file.name or "file"

    added_count = 0
    failed_count = 0

    if file_name.endswith(".session"):
        file_path = await event.download_media(file=SESSIONS_DIR)
        success = await process_single_session_file(file_path, dp, d2fa)
        if success:
            added_count += 1
        else:
            failed_count += 1

    elif file_name.endswith(".zip"):
        zip_path = await event.download_media(file=TEMP_DIR)
        extract_folder = os.path.join(TEMP_DIR, str(uuid.uuid4()))
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_folder)

        for root, dirs, files in os.walk(extract_folder):
            for f in files:
                if f.endswith(".session"):
                    full_p = os.path.join(root, f)
                    dest_p = os.path.join(SESSIONS_DIR, f)
                    shutil.move(full_p, dest_p)
                    success = await process_single_session_file(dest_p, dp, d2fa)
                    if success:
                        added_count += 1
                    else:
                        failed_count += 1
        shutil.rmtree(extract_folder, ignore_errors=True)
        if os.path.exists(zip_path):
            os.remove(zip_path)

    await status_msg.edit(f"✅ **اكتملت المعالجة!**\n\n🟢 تم إضافة: `{added_count}` سيشن شغالة\n🔴 الفاشلة / المكررة: `{failed_count}`")

async def process_single_session_file(file_path, price, pwd_2fa):
    try:
        temp_client = TelegramClient(file_path, BOT_API_ID, BOT_API_HASH)
        await temp_client.connect()
        if not await temp_client.is_user_authorized():
            await temp_client.disconnect()
            os.remove(file_path)
            return False

        me = await temp_client.get_me()
        phone = me.phone
        if not phone:
            await temp_client.disconnect()
            os.remove(file_path)
            return False

        str_sess = StringSession.save(temp_client.session)
        await temp_client.disconnect()
        os.remove(file_path)

        code, cname, flag = get_country_info(phone)

        async with db_lock:
            conn = get_db()
            c = conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO sessions 
                (phone, session_string, country_code, country_name, flag, price, password_2fa, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
            """, (phone, str_sess, code, cname, flag, price, pwd_2fa))
            conn.commit()
            conn.close()
        return True
    except Exception as e:
        print(f"خطأ تحويل السيشن: {e}")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        return False

async def main():
    print("🔍 جاري بدء تشغيل بوت البيع...")
    await bot_client.start(bot_token=BOT_TOKEN)
    asyncio.create_task(check_all_sessions_loop())
    print("✅ بوت بيع الحسابات شغال بكفاءة عالية!")
    await bot_client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
