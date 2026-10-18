from svc.api import fetch_v2


def job_0():
    return fetch_v2("https://example.test/m05/0")


def job_1():
    return fetch_v2("https://example.test/m05/1", timeout=9)


def job_2():
    return fetch_v2("https://example.test/m05/2")

