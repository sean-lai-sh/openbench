from svc import api


def job_0():
    return api.legacy_fetch("https://example.test/m08/0")


def job_1():
    return api.legacy_fetch("https://example.test/m08/1", timeout=9)

