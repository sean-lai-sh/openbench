"""Tiny weather API client."""
import json
import time
import urllib.error
import urllib.request


class WeatherClient:
    def __init__(self, base_url, timeout=5, attempts=3, backoff=0.5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.attempts = attempts
        self.backoff = backoff

    def get(self, city):
        """GET weather for `city`; retry on HTTP 503 with exponential backoff."""
        url = f"{self.base_url}/weather?city={city}"
        for attempt in range(self.attempts):
            try:
                with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code != 503 or attempt == self.attempts - 1:
                    raise
                time.sleep(self.backoff * 2 ** attempt)
