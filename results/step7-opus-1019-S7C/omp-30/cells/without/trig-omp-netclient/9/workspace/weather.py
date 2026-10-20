"""Tiny weather API client."""
import json
import time
import urllib.error
import urllib.request


class WeatherClient:
    MAX_ATTEMPTS = 3

    def __init__(self, base_url, timeout=5, backoff=0.5, sleep=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.backoff = backoff
        self._sleep = sleep

    def get(self, city):
        url = f"{self.base_url}/weather?city={city}"
        for attempt in range(self.MAX_ATTEMPTS):
            try:
                with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code != 503 or attempt == self.MAX_ATTEMPTS - 1:
                    raise
                e.close()
                self._sleep(self.backoff * 2**attempt)
