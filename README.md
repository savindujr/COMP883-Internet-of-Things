# COMP8832 IoT Weather Monitoring System

A complete IoT weather station built on a Raspberry Pi 3 with a Sense HAT sensor board. The system reads live environmental data (temperature, humidity, pressure), publishes it securely over MQTT/TLS, stores it in InfluxDB, pulls 48-hour forecast data from OpenWeatherMap every 6 hours, and visualises everything in Grafana dashboards.

---

## Repository Contents

| File | Description |
|---|---|
| `flows.json` | Node-RED flow — import this to get the full pipeline running |
| `forecast.py` | Python script — fetches 48h forecast from OWM and writes to InfluxDB |
| `current.py` | Python script — fetches current OWM weather and writes to InfluxDB |
| `README.md` | This file |

---

## Hardware Required

- Raspberry Pi 3 (any model with 40-pin GPIO)
- Raspberry Pi Sense HAT
- MicroSD card (16GB+)
- Power supply
- Network connection (Wi-Fi or Ethernet)

---

## Software Stack

| Software | Version | Role |
|---|---|---|
| Raspberry Pi OS | Debian Trixie (armhf) | Operating system |
| Node-RED | v4.1.10 | Sensor pipeline and MQTT publishing |
| Mosquitto | Latest | MQTT broker with TLS on port 8883 |
| InfluxDB | 1.8.10 | Time-series database |
| Grafana | Latest | Dashboards |
| Python | 3.x | Forecast and current weather scripts |

---

## Architecture

```
Sense HAT --(every 5s)--> Node-RED
                              |
              +---------------+----------------+
              v                                v
      Mosquitto MQTT/TLS (8883)        InfluxDB 'environment'
              |
        (verify via mosquitto_sub)

OpenWeatherMap API --(Python, every 6h via cron)--> InfluxDB 'forecast'
OpenWeatherMap API --(Python, every 10min via cron)--> InfluxDB 'current'

InfluxDB --> Grafana --> 3 dashboards
```

---

## Step 1 — Initial Setup

### 1.1 Flash and connect

Flash Raspberry Pi OS (Debian Trixie, 32-bit / armhf) to the SD card using Raspberry Pi Imager. Enable SSH in the imager settings. Boot the Pi and find its IP:

```bash
# on your PC
nmap -sn 192.168.1.0/24
ssh pi@<PI_IP>
```

### 1.2 Check architecture (important)

```bash
dpkg --print-architecture
```

Must return `armhf`. All packages in this guide are for armhf. Never use arm64 packages.

### 1.3 Update the system

```bash
sudo apt update && sudo apt upgrade -y
```

### 1.4 Enable I2C and install Sense HAT

```bash
sudo raspi-config nonint do_i2c 0
sudo apt install -y i2c-tools sense-hat
i2cdetect -y 1
```

The output should show addresses `1c`, `5c`, `5f`, `6a` confirming the Sense HAT is detected.

---

## Step 2 — Install Mosquitto (MQTT Broker)

```bash
sudo apt install -y mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto
```

---

## Step 3 — Install InfluxDB 1.8.10

> Do not use the InfluxDB apt repository — it is unreliable on Trixie. Install the armhf .deb directly.

```bash
cd ~
curl -LO https://dl.influxdata.com/influxdb/releases/influxdb_1.8.10_armhf.deb
sudo dpkg -i influxdb_1.8.10_armhf.deb
sudo apt -f install -y
sudo systemctl enable --now influxdb
influx -version
rm ~/influxdb_1.8.10_armhf.deb
```

Create the database:

```bash
influx
> CREATE DATABASE weatherdb
> exit
```

---

## Step 4 — Install Grafana

```bash
sudo apt install -y apt-transport-https software-properties-common
curl -fsSL https://apt.grafana.com/gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/grafana.gpg
echo "deb [signed-by=/usr/share/keyrings/grafana.gpg] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt update && sudo apt install -y grafana
sudo systemctl enable --now grafana-server
```

Grafana is available at `http://<PI_IP>:3000` (default login: admin / admin).

---

## Step 5 — Install Node-RED

```bash
sudo systemctl enable --now nodered.service
cd ~/.node-red
npm install node-red-contrib-sensehat node-red-contrib-influxdb
sudo systemctl restart nodered
```

Node-RED is available at `http://<PI_IP>:1880`.

---

## Step 6 — TLS Certificates for MQTT

```bash
sudo mkdir -p /etc/mosquitto/certs
cd /tmp

# Generate CA
openssl genrsa -out ca.key 2048
openssl req -new -x509 -days 3650 -key ca.key -out ca.crt -subj "/CN=WeatherIoT-CA"

# Generate server certificate
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr -subj "/CN=comitup-101"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 3650 \
  -extfile <(printf "subjectAltName=DNS:comitup-101,DNS:comitup-101.local")

# Copy to Mosquitto
sudo cp ca.crt server.crt server.key /etc/mosquitto/certs/
sudo chown mosquitto: /etc/mosquitto/certs/server.key
sudo chmod 600 /etc/mosquitto/certs/server.key
```

> Replace `comitup-101` with your Pi's actual hostname if different.

Create the TLS config:

```bash
sudo nano /etc/mosquitto/conf.d/tls.conf
```

Paste:

```
listener 8883
cafile /etc/mosquitto/certs/ca.crt
certfile /etc/mosquitto/certs/server.crt
keyfile /etc/mosquitto/certs/server.key
allow_anonymous true
```

Restart and verify:

```bash
sudo systemctl restart mosquitto
ss -tlnp | grep 8883
```

Test the broker in a second terminal:

```bash
mosquitto_sub -h comitup-101 -p 8883 --cafile /etc/mosquitto/certs/ca.crt -t weather/temperature -d
```

---

## Step 7 — Import the Node-RED Flow

1. Open `http://<PI_IP>:1880` in a browser
2. Click the hamburger menu (top right) → **Import**
3. Paste the contents of `flows.json` from this repo
4. Click **Import** then **Deploy**

The flow contains two chains:

**Chain A — CPU temperature (every 10s):**
`Inject CPU Time` → `Read CPU Temp` → `Convert CPU Temp` → `Store CPU Temp`

**Chain B — Sensor pipeline (every 5s):**
`timestamp` + `Sense HAT Env` → `function with cpu` → `MQTT out` + `InfluxDB out`

### Temperature calibration

The `function with cpu` node applies a fixed offset to correct for Pi CPU heat:

```javascript
let calibratedTemp = rawTemp - 18;
```

Adjust the offset value (`18`) to match your environment:
1. Find the real room temperature using a thermometer or phone
2. Check what the Pi reports: `influx -database weatherdb -execute 'SELECT * FROM environment ORDER BY time DESC LIMIT 3'`
3. offset = reported value - actual room temperature
4. Edit the function node in Node-RED and update the offset number
5. Click **Done** then **Deploy**

### Verify live data is flowing

```bash
influx -database weatherdb -execute 'SELECT * FROM environment ORDER BY time DESC LIMIT 5'
```

You should see rows updating every few seconds with `device=raspberrypi-sensehat` and `location=Auckland`.

---

## Step 8 — Python Environment and Scripts

```bash
mkdir -p ~/comp8832-weather-forecast
cd ~/comp8832-weather-forecast
python3 -m venv venv
./venv/bin/pip install requests influxdb
```

Copy `forecast.py` and `current.py` from this repo into `~/comp8832-weather-forecast/`.

### Update your OWM API key

Edit both scripts and replace `OWM_API_KEY` with your own key from [openweathermap.org](https://openweathermap.org/api):

```bash
nano ~/comp8832-weather-forecast/forecast.py
nano ~/comp8832-weather-forecast/current.py
```

> New OWM API keys take up to 2 hours to activate. If you get `401 Unauthorized`, wait and try again.

### Test both scripts

```bash
cd ~/comp8832-weather-forecast

./venv/bin/python forecast.py
# Expected: Successfully wrote 16 forecast points to InfluxDB.

./venv/bin/python current.py
# Expected: Wrote current reading: XX.XC, XX%, XXXXhPa
```

Verify data in InfluxDB:

```bash
influx -database weatherdb -execute 'SELECT * FROM forecast ORDER BY time DESC LIMIT 5'
influx -database weatherdb -execute 'SELECT * FROM current ORDER BY time DESC LIMIT 5'
```

---

## Step 9 — Schedule with Cron

```bash
crontab -e
```

Add these two lines at the bottom:

```
0 0,6,12,18 * * * /home/comitup/comp8832-weather-forecast/venv/bin/python /home/comitup/comp8832-weather-forecast/forecast.py >> /home/comitup/comp8832-weather-forecast/forecast.log 2>&1
*/10 * * * * /home/comitup/comp8832-weather-forecast/venv/bin/python /home/comitup/comp8832-weather-forecast/current.py >> /home/comitup/comp8832-weather-forecast/current.log 2>&1
```

> Replace `comitup` with your Pi username if different.

Verify:

```bash
crontab -l
```

---

## Step 10 — Grafana Dashboards

### Data source

1. Go to `http://<PI_IP>:3000` → Connections → Data Sources → Add
2. Select **InfluxDB**
3. Settings:
   - Query language: InfluxQL
   - URL: `http://localhost:8086`
   - Database: `weatherdb`
4. Save and Test

### Dashboard 1 — IoT Live Weather (6 gauges)

Create a new dashboard and add 6 Gauge panels:

| Panel title | FROM | Field | Unit | Min | Max |
|---|---|---|---|---|---|
| Temperature (°C) Pi | environment | temperature | Celsius | 0 | 40 |
| Humidity (%) Pi | environment | humidity | Percent | 0 | 100 |
| Pressure (hPa) Pi | environment | pressure | Hectopascals | 980 | 1040 |
| OpenWeather - Temperature | current | temperature | Celsius | 0 | 40 |
| OpenWeather - Humidity | current | humidity | Percent | 0 | 100 |
| OpenWeather - Pressure | current | pressure | Hectopascals | 980 | 1040 |

For each gauge: enable **Show threshold markers** and set thresholds:
- Temperature: base green / 20 orange / 28 red
- Humidity: base green / 60 orange / 80 red
- Pressure: base green / 1000 orange / 1020 red

### Dashboard 2 — OpenWeatherMap Forecast (3 time series)

Set time range to `now-1h` to `now+48h` before saving.

| Panel title | FROM | Field |
|---|---|---|
| Temperature Forecast (°C) | forecast | temperature |
| Humidity Forecast (%) | forecast | humidity |
| Pressure Forecast (hPa) | forecast | pressure |

### Dashboard 3 — IoT Weather Comparison (3 overlays)

Each panel has two queries (A and B). Set time range to `now-1h` to `now+48h`.

| Panel title | Query A | Query B |
|---|---|---|
| Temperature - Sensed vs Forecast | environment / temperature | forecast / temperature |
| Humidity - Sensed vs Forecast | environment / humidity | forecast / humidity |
| Pressure - Sensed vs Forecast | environment / pressure | forecast / pressure |

---

## Step 11 — Verify Everything

Run all checks:

```bash
# All four services active
systemctl is-active mosquitto influxdb grafana-server nodered

# TLS listening on 8883
ss -tlnp | grep 8883

# Live sensor data with device and location tags
influx -database weatherdb -execute 'SELECT * FROM environment ORDER BY time DESC LIMIT 3'

# Forecast data with device tag
influx -database weatherdb -execute 'SELECT * FROM forecast ORDER BY time DESC LIMIT 3'
influx -database weatherdb -execute 'SHOW TAG KEYS FROM forecast'

# Current API data
influx -database weatherdb -execute 'SELECT * FROM current ORDER BY time DESC LIMIT 1'

# MQTT live stream (run in a second terminal, Ctrl+C to stop)
mosquitto_sub -h comitup-101 -p 8883 --cafile /etc/mosquitto/certs/ca.crt -t weather/temperature -d

# Cron jobs registered
crontab -l
```

---

## Metadata Model

Both data streams carry full metadata as required:

**Live sensor (environment measurement):**
```json
[
  { "temperature": 14.2, "humidity": 36.5, "pressure": 1014 },
  { "device": "raspberrypi-sensehat", "location": "Auckland" }
]
```

**Forecast and current (forecast / current measurements):**
```
tags: city=Auckland, location=remote_cloud,
      source=openweathermap, device=openweathermap-cloud
fields: temperature, humidity, pressure
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| dpkg fails on InfluxDB | Wrong architecture | Use the armhf .deb directly |
| Temperature reads 50C+ | Offset not set or too small | Recalibrate the offset in `function with cpu` |
| No MQTT messages | Flow not deployed or Inject node disabled | Deploy the flow; check Inject node is Enabled |
| mosquitto_sub fails | Wrong port or cert CN mismatch | Add `-p 8883`; cert CN must match hostname |
| InfluxDB node shows error | Version set to 2.0 | Set to 1.x in the InfluxDB node config |
| ModuleNotFoundError influxdb | Wrong Python used | Use `./venv/bin/python`, not `python` |
| Forecast 401 Unauthorized | API key not active yet | Wait up to 2 hours after creating the key |
| Forecast dashboard shows No data | Time range ends at now | Set To: `now+48h` and save the dashboard |
| Duplicate forecast rows | Tag value changed after data existed | Run `DROP SERIES FROM forecast WHERE device=''` then rerun forecast.py |
| Pressure shows wrong unit | Unit set to kPa | Set Grafana unit to Hectopascals (hPa) |

---

## After Power Off / Restart

All four services start automatically on boot. After the Pi powers back on:

```bash
ping <PI_IP>
ssh comitup@<PI_IP>
systemctl is-active mosquitto influxdb grafana-server nodered
```

If any service is inactive:

```bash
sudo systemctl start mosquitto influxdb grafana-server nodered
```

Run `forecast.py` manually once to refresh forecast data, then open Grafana.

---

## Assignment Requirements Coverage

| Requirement | Where satisfied |
|---|---|
| Public cloud API | OpenWeatherMap in `forecast` and `current` measurements |
| Environmental readings | temperature, humidity, pressure from Sense HAT |
| JSON with timestamp | InfluxDB timestamp on every row |
| Signal readings | three fields in each measurement |
| Location metadata | `location` tag on all streams |
| Device label metadata | `device` tag: raspberrypi-sensehat / openweathermap-cloud |
| Stored in a database | InfluxDB weatherdb |
| Published to personal broker | Mosquitto MQTT over TLS on 8883 |
| Real-time display | Grafana IoT Live Weather gauges |
| 48-hour prediction | OWM Forecast dashboard |
| Sensor and cloud integration | Grafana Comparison overlay |
| Broker access demonstrated | `mosquitto_sub` live JSON stream |

---

- Student: Savindu Ranasinghe 
- Course: COMP8832 Internet of Things
- Data source: [OpenWeatherMap](https://openweathermap.org)