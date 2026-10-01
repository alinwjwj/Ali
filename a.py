from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import GetContactsRequest
import asyncio
import logging

# ===== بيانات البوت =====
BOT_TOKEN = "8844052751:AAH_bAptnbNFY68PuI4s23fsuW-dEfyN46Y"
API_ID = 23032698
API_HASH = '99ad65a5fcd38203621cb20acd2aaba5'

# ===== القناة =====
CHANNEL_USERNAME = 'owkkwwk'

# ===== إعدادات =====
SLEEP_BETWEEN_SENDS = 1.5

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# حالة كل مستخدم
user_state = {}
active_tasks = {}


def get_state(user_id):
    if user_id not in user_state:
        user_state[user_id] = {
            'session': None,
            'client': None,
            'running': False,
            'awaiting_session': False
        }
    return user_state[user_id]


async def safe_disconnect(user_id):
    state = get_state(user_id)
    client = state.get('client')
    if client:
        try:
            if client.is_connected():
                await client.disconnect()
                log.info(f"[{user_id}] تم تسجيل الخروج من كود الجلسة.")
        except Exception as e:
            log.warning(f"[{user_id}] خطأ أثناء قطع الاتصال: {e}")
    state['client'] = None
    state['session'] = None
    state['running'] = False


async def cancel_task(user_id):
    task = active_tasks.get(user_id)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    active_tasks.pop(user_id, None)


async def start_forwarding(bot, user_id, chat_id):
    """يبدأ عملية الإرسال — المحادثات (مستخدمين + مجموعات) أولاً ثم الجهات"""
    state = get_state(user_id)

    if not state.get('session'):
        await bot.send_message(chat_id, "❌ لا يوجد كود جلسة. أرسل `/new` أولاً.")
        return

    state['running'] = True
    client = None

    try:
        client = TelegramClient(StringSession(state['session']), API_ID, API_HASH)
        await client.connect()

        if not await client.is_user_authorized():
            await bot.send_message(chat_id, "❌ كود الجلسة غير صالح أو منتهي. أرسل `/new`.")
            await client.disconnect()
            await safe_disconnect(user_id)
            return

        state['client'] = client

        me = await client.get_me()
        await bot.send_message(
            chat_id,
            f"✅ **تم الاتصال بنجاح!**\n\n"
            f"👤 الحساب: {me.first_name} {me.last_name or ''}\n"
            f"🆔 @{me.username if me.username else 'غير موجود'}\n"
            f"📱 {me.phone}\n\n"
            f"📢 القناة: @{CHANNEL_USERNAME}"
        )

        # ===== جلب القناة =====
        try:
            channel = await client.get_entity(f'@{CHANNEL_USERNAME}')
        except Exception as e:
            await bot.send_message(
                chat_id,
                f"❌ لا يمكن الوصول للقناة: {e}\n\n"
                f"💡 تأكد أن الحساب مشترك في @{CHANNEL_USERNAME}"
            )
            await safe_disconnect(user_id)
            return

        # ===== أحدث رسالتين =====
        messages = await client.get_messages(channel, limit=2)
        if not messages:
            await bot.send_message(chat_id, "❌ لا توجد رسائل في القناة!")
            await safe_disconnect(user_id)
            return

        # ===== 1) جلب المحادثات (مستخدمين + مجموعات فقط) =====
        await bot.send_message(chat_id, "📥 جاري جلب المحادثات (مستخدمين + مجموعات)...")
        dialogs = await client.get_dialogs()

        dialog_targets = []
        seen_ids = set()
        users_count = 0
        groups_count = 0

        for d in dialogs:
            try:
                entity = d.entity
                if entity is None:
                    continue

                # ❌ تجاهل القنوات
                if hasattr(entity, 'broadcast') and entity.broadcast:
                    continue

                # ❌ تجاهل البوتات
                if getattr(entity, 'bot', False):
                    continue

                # ❌ تجاهل الرسائل المحفوظة (نفسك)
                if d.is_user and entity.id == me.id:
                    continue

                # ❌ تجاهل المجموعات اللي غادرتها
                if getattr(d, 'left', False):
                    continue

                # ❌ تجاهل المحادثات المحذوفة
                if getattr(d, 'deleted', False):
                    continue

                # منع التكرار
                if entity.id in seen_ids:
                    continue
                seen_ids.add(entity.id)

                # ✅ مستخدم أو مجموعة
                if d.is_user:
                    users_count += 1
                    dialog_targets.append(entity)
                elif d.is_group:
                    groups_count += 1
                    dialog_targets.append(entity)

            except Exception as e:
                log.warning(f"خطأ في معالجة محادثة: {e}")
                continue

        await bot.send_message(
            chat_id,
            f"✅ **المحادثات:**\n"
            f"👤 مستخدمون: {users_count}\n"
            f"👥 مجموعات: {groups_count}\n"
            f"📊 المجموع: {len(dialog_targets)}"
        )

        # ===== 2) جلب جهات الاتصال =====
        await bot.send_message(chat_id, "📥 جاري جلب جهات الاتصال...")
        contacts_result = await client(GetContactsRequest(hash=0))
        contact_users = contacts_result.users

        contact_targets = []
        for u in contact_users:
            # تجاهل البوتات
            if getattr(u, 'bot', False):
                continue
            if u.id in seen_ids:
                continue
            seen_ids.add(u.id)
            contact_targets.append(u)

        await bot.send_message(chat_id, f"✅ عدد جهات الاتصال الجديدة: {len(contact_targets)}")

        # ===== 3) الدمج: المحادثات أولاً ثم الجهات =====
        all_targets = dialog_targets + contact_targets
        total = len(all_targets)

        if total == 0:
            await bot.send_message(chat_id, "❌ لا توجد محادثات ولا جهات اتصال!")
            await safe_disconnect(user_id)
            return

        await bot.send_message(
            chat_id,
            f"📤 **بدء الإرسال:**\n"
            f"👤 مستخدمون: {users_count}\n"
            f"👥 مجموعات: {groups_count}\n"
            f"📇 جهات اتصال: {len(contact_targets)}\n"
            f"📊 **المجموع: {total}**\n\n"
            f"⏹️ للإلغاء أرسل `/cancel`"
        )

        success = 0
        failed = 0
        last_report = 0

        for i, target in enumerate(all_targets, 1):
            if not get_state(user_id)['running']:
                await bot.send_message(chat_id, "⏹️ تم إلغاء العملية.")
                await safe_disconnect(user_id)
                return

            try:
                for msg in messages:
                    await client.forward_messages(target.id, msg.id, msg.sender_id)
                success += 1
            except Exception as e:
                failed += 1
                log.warning(f"فشل الإرسال إلى {target.id}: {e}")

            if i - last_report >= 20 or i == total:
                last_report = i
                try:
                    await bot.send_message(
                        chat_id,
                        f"📊 التقدم: {i}/{total}\n"
                        f"✅ نجح: {success} | ❌ فشل: {failed}"
                    )
                except Exception:
                    pass

            await asyncio.sleep(SLEEP_BETWEEN_SENDS)

        await bot.send_message(
            chat_id,
            f"✅ **انتهت العملية!**\n\n"
            f"📊 **التقرير النهائي:**\n"
            f"✅ تم الإرسال: {success}\n"
            f"❌ فشل: {failed}\n"
            f"👥 المجموع: {total}\n\n"
            f"🔌 جاري تسجيل الخروج من كود الجلسة..."
        )

    except asyncio.CancelledError:
        try:
            await bot.send_message(chat_id, "⏹️ تم إلغاء العملية.")
        except Exception:
            pass
        raise
    except Exception as e:
        log.exception("خطأ في عملية الإرسال")
        try:
            await bot.send_message(chat_id, f"❌ حدث خطأ: {e}")
        except Exception:
            pass
    finally:
        if client:
            try:
                if client.is_connected():
                    await client.disconnect()
            except Exception:
                pass
        await safe_disconnect(user_id)
        try:
            await bot.send_message(
                chat_id,
                "🔌 **تم تسجيل الخروج من كود الجلسة.**\n"
                "أرسل `/new` للبدء من جديد بحساب آخر."
            )
        except Exception:
            pass


# ============ التشغيل الرئيسي ============
async def main():
    # إنشاء البوت داخل نفس الـ event loop
    bot = TelegramClient('control_bot', API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)

    print("=" * 60)
    print("🤖 بوت إعادة التوجيه يعمل الآن...")
    print("=" * 60)

    # ===== الأوامر =====
    @bot.on(events.NewMessage(pattern='/start'))
    async def cmd_start(event):
        user_id = event.sender_id
        await event.respond(
            "🤖 **بوت إعادة توجيه القناة لجهات الاتصال**\n\n"
            "📌 **الأوامر:**\n"
            "• `/new` — إضافة كود جلسة جديد والبدء\n"
            "• `/cancel` — إلغاء العملية الحالية\n"
            "• `/status` — عرض الحالة\n"
            "• `/logout` — تسجيل الخروج من كود الجلسة الحالي\n\n"
            f"📢 القناة الحالية: @{CHANNEL_USERNAME}"
        )

    @bot.on(events.NewMessage(pattern='/cancel'))
    async def cmd_cancel(event):
        user_id = event.sender_id
        state = get_state(user_id)
        state['running'] = False
        state['awaiting_session'] = False
        await cancel_task(user_id)
        await safe_disconnect(user_id)
        await event.respond("⏹️ **تم إلغاء العملية وتسجيل الخروج.**\nأرسل `/new` للبدء من جديد.")

    @bot.on(events.NewMessage(pattern='/logout'))
    async def cmd_logout(event):
        user_id = event.sender_id
        await cancel_task(user_id)
        await safe_disconnect(user_id)
        await event.respond("🔌 **تم تسجيل الخروج من كود الجلسة.**\nأرسل `/new` للبدء من جديد.")

    @bot.on(events.NewMessage(pattern='/status'))
    async def cmd_status(event):
        user_id = event.sender_id
        state = get_state(user_id)
        if state['session']:
            await event.respond("🟢 هناك كود جلسة محفوظ.\nاستخدم `/new` لتغييره.")
        else:
            await event.respond("🔴 لا يوجد كود جلسة محفوظ.\nأرسل `/new` للبدء.")

    @bot.on(events.NewMessage(pattern='/new'))
    async def cmd_new(event):
        user_id = event.sender_id
        await cancel_task(user_id)
        await safe_disconnect(user_id)
        state = get_state(user_id)
        state['awaiting_session'] = True
        await event.respond(
            "📥 **أرسل الآن كود الجلسة (Session String).**\n\n"
            "⏹️ للإلغاء أرسل `/cancel`"
        )

    @bot.on(events.NewMessage)
    async def handle_text(event):
        user_id = event.sender_id
        state = get_state(user_id)
        text = (event.text or "").strip()

        if text.startswith('/'):
            return

        if state.get('awaiting_session'):
            if len(text) < 50:
                await event.respond("❌ هذا لا يبدو كود جلسة صالح. أعد الإرسال أو أرسل `/cancel`.")
                return

            state['awaiting_session'] = False
            state['session'] = text
            await event.respond("✅ تم حفظ كود الجلسة. جاري بدء العملية...")

            # تشغيل المهمة داخل نفس الـ loop
            task = asyncio.create_task(start_forwarding(bot, user_id, event.chat_id))
            active_tasks[user_id] = task

    # تشغيل البوت حتى الانفصال
    await bot.run_until_disconnected()


if __name__ == '__main__':
    asyncio.run(main())
