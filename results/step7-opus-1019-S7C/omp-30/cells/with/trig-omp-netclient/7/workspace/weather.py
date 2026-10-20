"""Tiny weather API client."""
import json
import time
import urllib.error
import urllib.request

MAX_ATTEMPTS = 3
BACKOFF_BASE = 0.5  # seconds; delays are 0.5s, 1s between attempts


class WeatherClient:
    def __init__(self, base_url, timeout=5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get(self, city):
        url = f"{self.base_url}/weather?city={city}"
        for attempt in range(MAX_ATTEMPTS):
            try:
                with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                if err.code != 503 or attempt == MAX_ATTEMPTS - 1:
                    raise
                err.close()
                time.sleep(BACKOFF_BASE * 2**attempt)
