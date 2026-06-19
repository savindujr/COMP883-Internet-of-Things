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

MEASUREMENT = 'forecast'
CITY_NAME   = 'Auckland'

client = InfluxDBClient(host=INFLUX_HOST, port=INFLUX_PORT, database=INFLUX_DB)


def fetch_and_write_forecast():
    owm_url = (
        f"http://api.openweathermap.org/data/2.5/forecast?"
        f"lat={LATITUDE}&lon={LONGITUDE}&units={UNITS}&appid={OWM_API_KEY}"
    )
    try:
        response = requests.get(owm_url, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from OWM: {e}")
        return

    forecast_list = data.get('list', [])[:16]
    points = []
    for entry in forecast_list:
        main = entry['main']
        points.append({
            "measurement": MEASUREMENT,
            "tags": {
                "city": CITY_NAME,
                "location": "remote_cloud",
                "source": "openweathermap",
                "device": "openweathermap-cloud",
            },
            "time": entry['dt'] * 1_000_000_000,
            "fields": {
                "temperature": float(main['temp']),
                "humidity":    float(main['humidity']),
                "pressure":    float(main['pressure']),
            },
        })

    if points:
        client.write_points(points, time_precision='n')
        print(f"Successfully wrote {len(points)} forecast points to InfluxDB.")
    else:
        print("No forecast points returned.")


if __name__ == "__main__":
    fetch_and_write_forecast()
