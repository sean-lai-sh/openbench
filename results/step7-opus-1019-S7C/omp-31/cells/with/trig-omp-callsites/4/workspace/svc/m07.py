from svc.api import legacy_fetch


def job_0():
    return legacy_fetch("https://example.test/m07/0")


def job_1():
    return legacy_fetch("https://example.test/m07/1", timeout=9)

