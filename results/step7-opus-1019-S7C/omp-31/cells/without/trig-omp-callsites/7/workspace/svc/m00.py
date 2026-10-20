from svc import api


def job_0():
    return api.fetch_v2("https://example.test/m00/0")


def job_1():
    return api.fetch_v2("https://example.test/m00/1", timeout=9)


def job_2():
    return api.fetch_v2("https://example.test/m00/2")


def job_3():
    return api.fetch_v2("https://example.test/m00/3", timeout=9)


def job_4():
    return api.fetch_v2("https://example.test/m00/4")


def job_5():
    return api.fetch_v2("https://example.test/m00/5", timeout=9)

