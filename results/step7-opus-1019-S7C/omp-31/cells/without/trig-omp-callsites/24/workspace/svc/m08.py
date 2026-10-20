from svc import api


def job_0():
    return api.fetch_v2("https://example.test/m08/0")


def job_1():
    return api.fetch_v2("https://example.test/m08/1", timeout=9)

