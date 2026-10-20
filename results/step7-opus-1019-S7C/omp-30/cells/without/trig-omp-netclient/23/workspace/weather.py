"""Tiny weather API client."""
import json
import time
import urllib.error
import urllib.request


class WeatherClient:
    def __init__(self, base_url, timeout=5, max_attempts=3, backoff_base=0.5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base

    def get(self, city):
        url = f"{self.base_url}/weather?city={city}"
        for attempt in range(1, self.max_attempts + 1):
            try:
                with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code != 503 or attempt == self.max_attempts:
                    raise
                e.close()
            # Exponential backoff: backoff_base, 2*backoff_base, ...
            time.sleep(self.backoff_base * 2 ** (attempt - 1))
