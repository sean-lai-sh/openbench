"""Tiny weather API client."""
import json
import urllib.request


class WeatherClient:
    def __init__(self, base_url, timeout=5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get(self, city):
        url = f"{self.base_url}/weather?city={city}"
        with urllib.request.urlopen(url, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
