import subprocess
import sys

p1 = subprocess.Popen([sys.executable, "userbot.py"])
p2 = subprocess.Popen([sys.executable, "shop_bot.py"])

p1.wait()
p2.wait()
