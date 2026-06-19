import requests
from influxdb import InfluxDBClient

# --- Configuration ---
INFLUX_HOST = 'localhost'
INFLUX_PORT = 8086
INFLUX_DB   = 'weatherdb'

OWM_API_KEY = '508a96ba8ee43c033acfdef7ab093ca3'
LATITUDE    = '-36.8485'
LONGITUDE   = '174.7633'
UNITS       = 'metric'

MEASUREMENT = 'current'
CITY_NAME   = 'Auckland'

client = InfluxDBClient(host=INFLUX_HOST, port=INFLUX_PORT, database=INFLUX_DB)


def fetch_current():
    owm_url = (
        f"http://api.openweathermap.org/data/2.5/weather?"
        f"lat={LATITUDE}&lon={LONGITUDE}&units={UNITS}&appid={OWM_API_KEY}"
    )
    try:
        response = requests.get(owm_url, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from OWM: {e}")
        return

    main = data['main']
    point = [{
        "measurement": MEASUREMENT,
        "tags": {
            "city": CITY_NAME,
            "location": "remote_cloud",
            "source": "openweathermap",
            "device": "openweathermap-cloud",
        },
        "fields": {
            "temperature": float(main['temp']),
            "humidity":    float(main['humidity']),
            "pressure":    float(main['pressure']),
        },
    }]

    client.write_points(point)
    print(f"Wrote current reading: {main['temp']}C, {main['humidity']}%, {main['pressure']}hPa")


if __name__ == "__main__":
    fetch_current()
