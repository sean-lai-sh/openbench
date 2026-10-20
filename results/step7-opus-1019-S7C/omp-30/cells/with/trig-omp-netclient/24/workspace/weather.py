"""Tiny weather API client."""
import json
import time
import urllib.error
import urllib.request


class WeatherClient:
    max_attempts = 3
    backoff_base = 0.5  # seconds; delays are 0.5s, 1s between attempts

    def __init__(self, base_url, timeout=5, sleep=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._sleep = sleep

    def get(self, city):
        url = f"{self.base_url}/weather?city={city}"
        for attempt in range(1, self.max_attempts + 1):
            try:
                with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                if err.code != 503 or attempt == self.max_attempts:
                    raise
                err.close()
                self._sleep(self.backoff_base * 2 ** (attempt - 1))
