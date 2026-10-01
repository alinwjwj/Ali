import subprocess
import sys

# تشغيل الملفات الثلاثة معاً في خلفية نفس الحاوية
process1 = subprocess.Popen([sys.executable, "userbot.py"])
process2 = subprocess.Popen([sys.executable, "shop_bot.py"])
process3 = subprocess.Popen([sys.executable, "a.py"])

# الانتظار لضمان بقائها تعمل باستمرار
process1.wait()
process2.wait()
process3.wait()
