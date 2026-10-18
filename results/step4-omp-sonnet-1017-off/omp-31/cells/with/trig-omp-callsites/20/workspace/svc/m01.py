from svc.api import fetch_v2


def job_0():
    return fetch_v2("https://example.test/m01/0")


def job_1():
    return fetch_v2("https://example.test/m01/1", timeout=9)


def job_2():
    return fetch_v2("https://example.test/m01/2")


def job_3():
    return fetch_v2("https://example.test/m01/3", timeout=9)


def job_4():
    return fetch_v2("https://example.test/m01/4")

