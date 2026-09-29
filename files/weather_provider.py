import requests
from datetime import datetime, timedelta

class WeatherProvider:
    """Get accurate weather data using Open-Meteo (free, no API key needed)"""

    def __init__(self):
        self.geocoding_url = "https://geocoding-api.open-meteo.com/v1/search"
        self.weather_url = "https://api.open-meteo.com/v1/forecast"

        # Common city coordinates (for instant lookup)
        self.city_coords = {
            'vilnius': (54.6872, 25.2797),
            'london': (51.5074, -0.1278),
            'new york': (40.7128, -74.0060),
            'paris': (48.8566, 2.3522),
            'tokyo': (35.6762, 139.6503),
            'sydney': (-33.8688, 151.2093),
            'toronto': (43.6532, -79.3832),
            'moscow': (55.7558, 37.6173),
        }

    def get_coordinates(self, city_name):
        """Get latitude and longitude for a city"""
        city_lower = city_name.lower().strip()
        # "Paris, France" -> geocode "Paris" (the API matches on the place name only)
        city_name = city_name.split(',')[0].strip()

        # Check if in cache
        if city_lower in self.city_coords:
            return self.city_coords[city_lower]

        # Try to find via geocoding API
        try:
            params = {
                'name': city_name,
                'count': 1,
                'language': 'en',
                'format': 'json'
            }

            response = requests.get(self.geocoding_url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()

            if data.get('results') and len(data['results']) > 0:
                result = data['results'][0]
                return (result['latitude'], result['longitude'])

        except (requests.exceptions.RequestException, ValueError, KeyError) as e:
            print(f"Geocoding error for '{city_name}': {e}")

        return None

    def get_weather(self, city_name):
        """Get weather forecast for a city"""
        coords = self.get_coordinates(city_name)

        if not coords:
            return f"❌ Could not find location: {city_name}"

        try:
            lat, lon = coords

            params = {
                'latitude': lat,
                'longitude': lon,
                'current': 'temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m',
                'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max',
                'temperature_unit': 'celsius',
                'wind_speed_unit': 'kmh',
                'precipitation_unit': 'mm',
                'forecast_days': 7,
                'timezone': 'auto'
            }

            response = requests.get(self.weather_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            return self._format_weather(city_name, data)

        except Exception as e:
            return f"❌ Weather error: {str(e)}"

    def _format_weather(self, city_name, data):
        """Format weather data nicely"""
        try:
            report = f"🌤️ Weather Forecast for {city_name.title()}\n"
            report += "=" * 50 + "\n\n"

            # Current weather
            if data.get('current'):
                current = data['current']
                temp = current.get('temperature_2m', 'N/A')
                humidity = current.get('relative_humidity_2m', 'N/A')
                wind = current.get('wind_speed_10m', 'N/A')
                weather_code = current.get('weather_code', 0)
                condition = self._get_weather_condition(weather_code)

                report += "📍 Current Conditions:\n"
                report += f"  Temperature: {temp}°C\n"
                report += f"  Condition: {condition}\n"
                report += f"  Humidity: {humidity}%\n"
                report += f"  Wind Speed: {wind} km/h\n\n"

            # Daily forecast
            if data.get('daily'):
                daily = data['daily']
                report += "📅 7-Day Forecast:\n"

                for i in range(min(7, len(daily.get('time', [])))):
                    date = daily['time'][i]
                    temp_max = daily['temperature_2m_max'][i]
                    temp_min = daily['temperature_2m_min'][i]
                    weather_code = daily['weather_code'][i]
                    condition = self._get_weather_condition(weather_code)
                    precipitation = daily['precipitation_sum'][i]

                    # Format date
                    date_obj = datetime.fromisoformat(date)
                    date_str = date_obj.strftime('%a, %b %d')

                    report += f"\n{date_str}:\n"
                    report += f"  🌡️  {temp_min}°C to {temp_max}°C\n"
                    report += f"  ☁️  {condition}\n"

                    if precipitation:
                        report += f"  🌧️  Precipitation: {precipitation}mm\n"

            return report

        except Exception as e:
            return f"Error formatting weather: {str(e)}"

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
        coords = self.get_coordinates(city_name)

        if not coords:
            return f"❌ Could not find location: {city_name}"

        try:
            lat, lon = coords

            params = {
                'latitude': lat,
                'longitude': lon,
                'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum',
                'temperature_unit': 'celsius',
                'forecast_days': 2,
                'timezone': 'auto'
            }

            response = requests.get(self.weather_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('daily') and len(data['daily'].get('time', [])) > 1:
                daily = data['daily']
                # Get tomorrow (index 1)
                tomorrow = daily['time'][1]
                temp_max = daily['temperature_2m_max'][1]
                temp_min = daily['temperature_2m_min'][1]
                weather_code = daily['weather_code'][1]
                condition = self._get_weather_condition(weather_code)
                precipitation = daily['precipitation_sum'][1]

                report = f"🌤️ Weather Tomorrow in {city_name.title()}:\n"
                report += f"Temperature: {temp_min}°C to {temp_max}°C\n"
                report += f"Condition: {condition}\n"

                if precipitation:
                    report += f"Precipitation: {precipitation}mm\n"

                return report

            return "Could not get tomorrow's weather"

        except Exception as e:
            return f"Error: {str(e)}"
