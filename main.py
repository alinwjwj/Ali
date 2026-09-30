import subprocess
import sys

# تشغيل الملفين معاً في خلفية نفس الحاوية
process1 = subprocess.Popen([sys.executable, "userbot.py"])
process2 = subprocess.Popen([sys.executable, "shop_bot.py"])

# الانتظار لضمان بقائهما يعملان باستمرار
process1.wait()
process2.wait()
