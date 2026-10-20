from svc import api


def job_0():
    return api.fetch_v2("https://example.test/m02/0")


def job_1():
    return api.fetch_v2("https://example.test/m02/1", timeout=9)


def job_2():
    return api.fetch_v2("https://example.test/m02/2")


def job_3():
    return api.fetch_v2("https://example.test/m02/3", timeout=9)

