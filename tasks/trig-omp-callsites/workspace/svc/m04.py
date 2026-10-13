from svc import api


def job_0():
    return api.legacy_fetch("https://example.test/m04/0")


def job_1():
    return api.legacy_fetch("https://example.test/m04/1", timeout=9)


def job_2():
    return api.legacy_fetch("https://example.test/m04/2")

