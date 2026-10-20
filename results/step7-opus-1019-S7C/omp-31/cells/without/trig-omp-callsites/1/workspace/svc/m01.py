from svc.api import legacy_fetch


def job_0():
    return legacy_fetch("https://example.test/m01/0")


def job_1():
    return legacy_fetch("https://example.test/m01/1", timeout=9)


def job_2():
    return legacy_fetch("https://example.test/m01/2")


def job_3():
    return legacy_fetch("https://example.test/m01/3", timeout=9)


def job_4():
    return legacy_fetch("https://example.test/m01/4")

