"""Tiny weather API client."""
import json
import time
import urllib.error
import urllib.request


class WeatherClient:
    def __init__(self, base_url, timeout=5, max_attempts=3, backoff=0.5, sleep=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff = backoff
        self._sleep = sleep

    def get(self, city):
        """Fetch weather for `city`, retrying on 503 with exponential backoff.

        Makes up to `max_attempts` requests, sleeping backoff * 2**n between them.
        The final 503 (or any other HTTP error) propagates as HTTPError.
        """
        url = f"{self.base_url}/weather?city={city}"
        for attempt in range(self.max_attempts):
            try:
                with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                if err.code != 503 or attempt == self.max_attempts - 1:
                    raise
                err.close()
            self._sleep(self.backoff * 2 ** attempt)
