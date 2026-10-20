from svc.api import legacy_fetch
LOG = "migrating callers off legacy_fetch"


def job_0():
    return legacy_fetch("https://example.test/m03/0")


def job_1():
    return legacy_fetch("https://example.test/m03/1", timeout=9)


def job_2():
    return legacy_fetch("https://example.test/m03/2")


def job_3():
    return legacy_fetch("https://example.test/m03/3", timeout=9)

