# Automation and Integration Guide

> **SUPERSEDED.** This document describes wiring an INA219 power sensor over I2C and
> reading it from a Python script. That approach was **not adopted**. It is kept for
> the record because the reasoning against it is part of the project's methodology
> argument, not because it should be followed.
>
> **What replaced it:** on-chip `micros()` instrumentation with an automated harness —
> `make benchmark` and `make analyze`. See `docs/Measurement_Strategy_and_Hardware.md`
> for the decision and `docs/Architecture and Endpoints.md` for the endpoints.
>
> **Why:** an INA219 samples faster than a USB meter but still not at microsecond
> resolution, and to avoid perturbing the measurement it would have to monitor a second
> board — added hardware, added wiring, added failure modes, and still short of the
> resolution the software timer already reaches. Note also that the sampling loop in the
> snippet below runs at 100 Hz, which cannot resolve an operation that completes in
> single-digit microseconds.


This document outlines the technical steps to automate data collection using an INA219 power sensor and generate analysis graphs, replacing the manual video syncing process.

## 1. Hardware Setup (INA219 to ESP32-C3)

The INA219 measures high-side voltage and DC current draw over I2C. 

### Wiring Diagram
| ESP32-C3 SuperMini | INA219 Module |
| :--- | :--- |
| 3.3V | VCC |
| GND | GND |
| GPIO 8 (SDA) | SDA |
| GPIO 9 (SCL) | SCL |

*Note: Connect the INA219 in series with the power supply of the target device being measured. If the ESP32 is measuring its own power (which can be tricky due to I2C overhead), it's better to use a secondary ESP32 or an Arduino to monitor the primary ESP32.*

## 2. Firmware Integration (PlatformIO / C++)

Add the `Adafruit INA219` library to your `platformio.ini`:
```ini
lib_deps =
    adafruit/Adafruit INA219 @ ^1.2.2
```

**Basic Code Snippet for ESP32:**
```cpp
#include <Wire.h>
#include <Adafruit_INA219.h>

Adafruit_INA219 ina219;

void setup(void) 
{
  Serial.begin(115200);
  while (!Serial) { delay(1); }
  
  // Initialize I2C with specific pins for ESP32-C3
  Wire.begin(8, 9); 
  
  if (! ina219.begin()) {
    Serial.println("Failed to find INA219 chip");
    while (1) { delay(10); }
  }
  Serial.println("INA219 Setup Complete.");
}

void loop(void) 
{
  float current_mA = ina219.getCurrent_mA();
  float power_mW = ina219.getPower_mW();
  
  // Print comma-separated values for the Python script
  // Format: timestamp_ms, current_mA, power_mW
  Serial.print(millis()); Serial.print(",");
  Serial.print(current_mA); Serial.print(",");
  Serial.println(power_mW);
  
  delay(10); // 100Hz sampling rate
}
```

## 3. Python Data Collection & Graphing

Once the ESP32 outputs CSV data over Serial, you can use a Python script to read, log, and graph the consumption spikes.

**Required Libraries:**
```bash
pip install pyserial matplotlib pandas
```

**Python Graphing Script (`graph_power.py`):**
```python
import serial
import pandas as pd
import matplotlib.pyplot as plt
import time

# Configuration
SERIAL_PORT = '/dev/ttyACM1'
BAUD_RATE = 115200
SAMPLE_TIME = 10 # seconds

def collect_data():
    data = []
    print(f"Connecting to {SERIAL_PORT}...")
    
    try:
        with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
            print("Collecting data...")
            start_time = time.time()
            
            while (time.time() - start_time) < SAMPLE_TIME:
                line = ser.readline().decode('utf-8').strip()
                if line:
                    try:
                        ms, mA, mW = map(float, line.split(','))
                        data.append({'Time_ms': ms, 'Current_mA': mA, 'Power_mW': mW})
                    except ValueError:
                        pass # Ignore corrupted lines
    except Exception as e:
        print(f"Error: {e}")
        
    return pd.DataFrame(data)

def generate_graph(df):
    if df.empty:
        print("No data collected.")
        return
        
    # Normalize time to start at 0
    df['Time_s'] = (df['Time_ms'] - df['Time_ms'].iloc[0]) / 1000.0
    
    plt.figure(figsize=(10, 5))
    plt.plot(df['Time_s'], df['Power_mW'], color='blue', label='Power (mW)')
    
    plt.title('ESP32 Power Consumption During Authentication')
    plt.xlabel('Time (Seconds)')
    plt.ylabel('Power (mW)')
    plt.grid(True)
    plt.legend()
    
    plt.savefig('power_profile.png')
    print("Graph saved as power_profile.png")
    plt.show()

if __name__ == "__main__":
    df = collect_data()
    generate_graph(df)
```

## Next Steps

~~Wire the INA219, run `graph_power.py`, save `power_profile.png`.~~ Superseded — see
the banner at the top of this file. The current path is:

```bash
cd ESP32_Auth_PIO
make benchmark
make analyze CSV=results/<run-id>/benchmark.csv
```

which writes `energy.png`, `latency.png`, `ratios.png`, and `report.md` with no wiring
and no manual correlation.
