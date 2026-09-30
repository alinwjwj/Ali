import asyncio
import io
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# --- الإعدادات وكود السيشن الخاص بك ---
API_ID = 23032698
API_HASH = '99ad65a5fcd38203621cb20acd2aaba5'
USER_SESSION_STRING = "1BJWap1wBuxeoy53BlG26uKO-fFkJkoK906gSzFszPu7Fdndc6MaIKXvvSQfo480-PEyxdGN6Lmh2PJ_p--FVnn5w2g3gU2sNOUT1PA6PPDuZ8ffLS_JSIZc455L1Ct4ai00m3YEeb-2zerK5yMwhodykmWGpwN1Q289ast20fgvz7y4KtQJ6A88zTqk0eYr_DUOIE6wQmMmeXoLX0bSo1232HjFdjzvfI7pQMuqZe1RIuw45vMMF_3lgIRdr6OKheCNg-27TMq3dCxzGjx3gRkRI1XnW8PyGilyj9FTSkaIr6levwzO4CAbymO57coKsI3LcIEWNDA9E8SW0dqkLXdg-Isk-e0s="

client = TelegramClient(StringSession(USER_SESSION_STRING), API_ID, API_HASH)
SAVE_STATUS = False

# --- ميزة الدز المطور (سريعة وبدون حفظ على القرص) ---
@client.on(events.NewMessage(pattern=r'\.دزه (.*)', outgoing=True))
async def send_clean_media(event):
    input_target = event.pattern_match.group(1).strip()
    if not event.is_reply:
        await event.delete()
        return 
    try:
        target = int(input_target) if input_target.isdigit() else input_target
        reply_msg = await event.get_reply_message()
        if reply_msg and reply_msg.media:
            buffer = io.BytesIO()
            await reply_msg.download_media(file=buffer)
            buffer.name = "media.jpg"
            buffer.seek(0)
            
            await client.send_file(target, buffer, ttl=15, force_document=False)
            await event.delete()
            buffer.close()
        else:
            await event.delete()
    except Exception as e:
        print(f"خطأ في دزه: {e}")
        await event.delete()

# --- ميزة دزه جاهز (سريعة جداً للمجموعات والمستلمين) ---
@client.on(events.NewMessage(pattern=r'\.دزه_جاهز (.*)', outgoing=True))
async def send_ready_media(event):
    targets_input = event.pattern_match.group(1).strip()
    if not event.is_reply:
        await event.edit("⚠️️ **يجب الرد على الوسائط**")
        await asyncio.sleep(1.5)
        await event.delete()
        return
    
    targets_list = [t.strip() for t in targets_input.replace('،', ',').split(',')]
    reply_msg = await event.get_reply_message()
    if not reply_msg or not reply_msg.media:
        await event.edit("⚠️ **الرسالة المدعومة يجب أن تحتوي على وسائط**")
        await asyncio.sleep(1.5)
        await event.delete()
        return
    
    parsed_targets = []
    for target in targets_list:
        try:
            parsed_targets.append(int(target) if target.isdigit() else target)
        except Exception:
            continue
    
    if not parsed_targets:
        await event.edit("⚠️ **لم يتم التعرف على أي أهداف صحيحة**")
        await asyncio.sleep(1.5)
        await event.delete()
        return
    
    buffer = io.BytesIO()
    await reply_msg.download_media(file=buffer)
    buffer.name = "media.jpg"
    
    success_count = 0
    for target in parsed_targets:
        try:
            buffer.seek(0)
            await client.send_file(target, buffer, ttl=15, force_document=False)
            success_count += 1
        except Exception as e:
            print(f"خطأ في الإرسال إلى {target}: {e}")
            
    buffer.close()
    await event.edit(f"✅ **تم الإرسال السريع إلى {success_count} من {len(parsed_targets)} جهة**")
    await asyncio.sleep(2)
    await event.delete()

# --- ميزة حفظ الذاتيات ---
@client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def auto_save(event):
    global SAVE_STATUS
    if SAVE_STATUS and event.media:
        has_ttl = getattr(event.media, 'ttl_seconds', None)
        if has_ttl:
            try:
                buffer = io.BytesIO()
                await event.download_media(file=buffer)
                buffer.name = "self_destruct.jpg"
                buffer.seek(0)
                
                await client.send_file(
                    "me", 
                    buffer, 
                    caption=f"📥 **تم سحب ذاتية بنجاح!**\n👤 **المُرسل:** `{event.sender_id}`"
                )
                buffer.close()
            except Exception as e:
                print(f"خطأ أثناء حفظ الذاتية: {e}")

# --- أوامر التحكم ---
@client.on(events.NewMessage(pattern=r'\.الذاتية (تشغيل|تعطيل)', outgoing=True))
async def toggle_save(event):
    global SAVE_STATUS
    cmd = event.pattern_match.group(1)
    SAVE_STATUS = (cmd == "تشغيل")
    await event.edit(f"✅ تم **{cmd}** حفظ الذاتيات الفوري.")
    await asyncio.sleep(1.5)
    await event.delete()

@client.on(events.NewMessage(pattern=r'\.فحص', outgoing=True))
async def ping(event):
    await event.edit("**🚀 السكربت شغال بأقصى سرعة!**")
    await asyncio.sleep(1.5)
    await event.delete()

@client.on(events.NewMessage(pattern=r'\.مساعدة', outgoing=True))
async def help_command(event):
    help_text = """
**⚡ قائمة الأوامر (النسخة السريعة):**

1. `.دزه [آيدي/يوزر]` - إرسال الوسائط في RAM مباشرة دون الحفظ للسيرفر مع TTL 15s.
2. `.دزه_جاهز [آيدي1, آيدي2, ...]` - إرسال سريع ومتعدد للوسائط.
3. `.الذاتية تشغيل` - تفعيل الحفظ الفوري المباشر للرسائل المحفوظة.
4. `.الذاتية تعطيل` - تعطيل حفظ الذاتيات.
5. `.فحص` - التأكد من استجابة السكربت.
6. `.مساعدة` - عرض هذه القائمة.
"""
    await event.edit(help_text)
    await asyncio.sleep(8)
    await event.delete()

async def main():
    print("🔍 جاري الاتصال بالحساب عبر الـ StringSession...")
    await client.start()
    print("✅ السكربت الشخصي يعمل الآن بنجاح!")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
