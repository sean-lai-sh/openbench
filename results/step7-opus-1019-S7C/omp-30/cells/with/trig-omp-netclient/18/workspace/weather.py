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
        """Fetch weather for `city`, retrying on HTTP 503 with exponential backoff.

        Makes up to `max_attempts` attempts, sleeping `backoff * 2**n` seconds
        between them. Re-raises the final 503 if all attempts fail; any other
        error propagates immediately.
        """
        url = f"{self.base_url}/weather?city={city}"
        for attempt in range(self.max_attempts):
            try:
                with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code != 503 or attempt == self.max_attempts - 1:
                    raise
                e.close()
            time.sleep(self.backoff * 2**attempt)
