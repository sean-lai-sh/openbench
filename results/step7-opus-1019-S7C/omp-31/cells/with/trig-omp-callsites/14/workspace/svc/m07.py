from svc.api import fetch_v2


def job_0():
    return fetch_v2("https://example.test/m07/0")


def job_1():
    return fetch_v2("https://example.test/m07/1", timeout=9)

