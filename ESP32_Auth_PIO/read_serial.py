import serial
import time
s = serial.Serial('/dev/ttyACM0', 115200, timeout=1)
s.dtr = True
s.rts = False
time.sleep(0.1)
s.dtr = False
s.rts = False
print("Reset sent, reading...")
t0 = time.time()
while time.time() - t0 < 15:
    line = s.readline()
    if line:
        print(line.decode(errors='ignore').strip())
