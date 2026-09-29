from datetime import datetime

import requests


class WeatherProvider:
    """Get accurate weather data using Open-Meteo (free, no API key needed)"""

    def __init__(self):
        self.geocoding_url = "https://geocoding-api.open-meteo.com/v1/search"
        self.weather_url = "https://api.open-meteo.com/v1/forecast"

    def find_place(self, place):
        """Look up a place with Open-Meteo geocoding.

        "London, Ontario" or "Paris, US" pick the match whose state, country or
        country code fits the part after the comma.

        Returns:
            dict | None: {'latitude', 'longitude', 'label'}
        """
        name, _, qualifier = place.partition(',')
        name, qualifier = name.strip(), qualifier.strip().lower()
        if not name:
            return None

        try:
            response = requests.get(self.geocoding_url, params={
                'name': name,
                'count': 10 if qualifier else 1,
                'language': 'en',
                'format': 'json'
            }, timeout=5)
            response.raise_for_status()
            results = response.json().get('results') or []
        except (requests.exceptions.RequestException, ValueError) as e:
            print(f"Geocoding error for '{place}': {e}")
            return None

        if qualifier:
            def matches(r):
                fields = (r.get('country', ''), r.get('admin1', ''), r.get('country_code', ''))
                return any(qualifier == f.lower() or (len(qualifier) > 3 and qualifier in f.lower())
                           for f in fields if f)
            results = [r for r in results if matches(r)]
        if not results:
            return None

        best = results[0]
        label = ", ".join(dict.fromkeys(  # dict.fromkeys drops repeats like "Singapore, Singapore"
            part for part in (best.get('name'), best.get('admin1'), best.get('country')) if part))
        return {'latitude': best['latitude'], 'longitude': best['longitude'], 'label': label}

    def _forecast(self, place, params):
        """Call the forecast API for a place found by find_place()"""
        response = requests.get(self.weather_url, params={
            'latitude': place['latitude'],
            'longitude': place['longitude'],
            'temperature_unit': 'celsius',
            'wind_speed_unit': 'kmh',
            'precipitation_unit': 'mm',
            'timezone': 'auto',
            **params
        }, timeout=10)
        response.raise_for_status()
        return response.json()

    def get_weather(self, city_name):
        """Get current weather and a 7-day forecast for a city"""
        place = self.find_place(city_name)
        if not place:
            return f"❌ Could not find location: {city_name}"

        try:
            data = self._forecast(place, {
                'current': 'temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m',
                'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum',
                'forecast_days': 7,
            })
        except (requests.exceptions.RequestException, ValueError) as e:
            return f"❌ Weather error: {e}"
        return self._format_weather(place['label'], data)

    def _format_weather(self, label, data):
        """Format weather data nicely"""
        report = f"🌤️ Weather Forecast for {label}\n" + "=" * 50 + "\n\n"

        current = data.get('current') or {}
        if current:
            local_time = current.get('time', '').replace('T', ' ')
            report += f"📍 Current Conditions (local time {local_time}):\n"
            report += f"  Temperature: {current.get('temperature_2m', 'N/A')}°C\n"
            report += f"  Condition: {self._get_weather_condition(current.get('weather_code'))}\n"
            report += f"  Humidity: {current.get('relative_humidity_2m', 'N/A')}%\n"
            report += f"  Wind Speed: {current.get('wind_speed_10m', 'N/A')} km/h\n\n"

        daily = data.get('daily') or {}
        days = daily.get('time', [])
        if days:
            report += "📅 7-Day Forecast:\n"
        for i, day in enumerate(days[:7]):
            date_str = datetime.fromisoformat(day).strftime('%a, %b %d')
            report += f"\n{date_str}:\n"
            report += f"  🌡️  {daily['temperature_2m_min'][i]}°C to {daily['temperature_2m_max'][i]}°C\n"
            report += f"  ☁️  {self._get_weather_condition(daily['weather_code'][i])}\n"
            precipitation = daily['precipitation_sum'][i]
            if precipitation:
                report += f"  🌧️  Precipitation: {precipitation}mm\n"
        return report

    def _get_weather_condition(self, code):
        """Convert WMO weather code to condition string"""
        codes = {
            0: "Clear sky",
            1: "Mainly clear",
            2: "Partly cloudy",
            3: "Overcast",
            45: "Foggy",
            48: "Depositing rime fog",
            51: "Light drizzle",
            53: "Moderate drizzle",
            55: "Dense drizzle",
            61: "Slight rain",
            63: "Moderate rain",
            65: "Heavy rain",
            71: "Slight snow",
            73: "Moderate snow",
            75: "Heavy snow",
            77: "Snow grains",
            80: "Slight rain showers",
            81: "Moderate rain showers",
            82: "Violent rain showers",
            85: "Slight snow showers",
            86: "Heavy snow showers",
            95: "Thunderstorm",
            96: "Thunderstorm with slight hail",
            99: "Thunderstorm with heavy hail",
        }

        return codes.get(code, f"Unknown (code {code})")

    def get_weather_for_tomorrow(self, city_name):
        """Get weather specifically for tomorrow"""
        place = self.find_place(city_name)
        if not place:
            return f"❌ Could not find location: {city_name}"

        try:
            data = self._forecast(place, {
                'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum',
                'forecast_days': 2,
            })
        except (requests.exceptions.RequestException, ValueError) as e:
            return f"❌ Weather error: {e}"

        daily = data.get('daily') or {}
        if len(daily.get('time', [])) < 2:
            return "Could not get tomorrow's weather"

        # Index 1 is tomorrow in the place's own time zone
        date_str = datetime.fromisoformat(daily['time'][1]).strftime('%a, %b %d')
        report = f"🌤️ Weather Tomorrow ({date_str}) in {place['label']}:\n"
        report += f"Temperature: {daily['temperature_2m_min'][1]}°C to {daily['temperature_2m_max'][1]}°C\n"
        report += f"Condition: {self._get_weather_condition(daily['weather_code'][1])}\n"
        if daily['precipitation_sum'][1]:
            report += f"Precipitation: {daily['precipitation_sum'][1]}mm\n"
        return report
