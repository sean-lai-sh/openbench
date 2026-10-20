from svc.api import legacy_fetch


def job_0():
    return legacy_fetch("https://example.test/m05/0")


def job_1():
    return legacy_fetch("https://example.test/m05/1", timeout=9)


def job_2():
    return legacy_fetch("https://example.test/m05/2")

