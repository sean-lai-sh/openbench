from svc.api import fetch_v2
LOG = "migrating callers off legacy_fetch"


def job_0():
    return fetch_v2("https://example.test/m03/0")


def job_1():
    return fetch_v2("https://example.test/m03/1", timeout=9)


def job_2():
    return fetch_v2("https://example.test/m03/2")


def job_3():
    return fetch_v2("https://example.test/m03/3", timeout=9)

