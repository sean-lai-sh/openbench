"""Tiny weather API client."""
import json
import time
import urllib.error
import urllib.request


class WeatherClient:
    MAX_ATTEMPTS = 3

    def __init__(self, base_url, timeout=5, backoff=0.5):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.backoff = backoff

    def get(self, city):
        """Fetch weather for `city`, retrying up to 3 attempts on HTTP 503.

        Waits `backoff * 2**n` seconds between attempts (0.5s, 1s by default).
        Other HTTP errors, and the final 503, propagate as HTTPError.
        """
        url = f"{self.base_url}/weather?city={city}"
        for attempt in range(self.MAX_ATTEMPTS):
            try:
                with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                if err.code != 503 or attempt == self.MAX_ATTEMPTS - 1:
                    raise
                err.close()
            time.sleep(self.backoff * 2**attempt)
