"""Tiny weather API client."""
import json
import time
import urllib.error
import urllib.request


class WeatherClient:
    max_attempts = 3
    backoff_base = 0.5  # seconds; delay doubles after each failed attempt

    def __init__(self, base_url, timeout=5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get(self, city):
        url = f"{self.base_url}/weather?city={city}"
        for attempt in range(self.max_attempts):
            try:
                with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code != 503 or attempt == self.max_attempts - 1:
                    raise
                e.close()
            time.sleep(self.backoff_base * 2**attempt)
