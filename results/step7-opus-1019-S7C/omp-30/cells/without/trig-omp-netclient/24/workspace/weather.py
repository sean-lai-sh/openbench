"""Tiny weather API client."""
import json
import time
import urllib.error
import urllib.request


class WeatherClient:
    def __init__(self, base_url, timeout=5, max_attempts=3, backoff=0.5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff = backoff

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
            # Exponential backoff: backoff, 2*backoff, 4*backoff, ...
            time.sleep(self.backoff * 2 ** (attempt - 1))
