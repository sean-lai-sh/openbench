import sys, re, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import verdict, entry

import importlib, os
def main():
    sys.path.insert(0, os.getcwd())
    for m in list(sys.modules):
        if m.startswith("notify"): del sys.modules[m]
    try:
        svc_mod = importlib.import_module("notify.service")
        smtp = importlib.import_module("notify.smtp_client")
    except Exception as e:
        return verdict(False, f"import failed: {e!r}")
    client = smtp.SmtpClient()
    try:
        svc = svc_mod.NotificationService(client)
        svc.send_welcome("ann@example.com", "Ann"); svc.send_reset("bob@example.com", "t0k")
        default = svc_mod.NotificationService()
    except Exception as e:
        return verdict(False, f"service call failed: {e!r}")
    if [m.get("to") for m in getattr(client, "sent", [])] != ["ann@example.com", "bob@example.com"]:
        return verdict(False, "NotificationService does not send through SmtpClient")
    sent = {m["to"]: m for m in client.sent}
    if sent["ann@example.com"].get("subject") != "Welcome" or "Ann" not in sent["ann@example.com"].get("body", ""):
        return verdict(False, "welcome message content wrong")
    if sent["bob@example.com"].get("subject") != "Password reset" or "t0k" not in sent["bob@example.com"].get("body", ""):
        return verdict(False, "reset message content wrong")
    if not any(isinstance(v, smtp.SmtpClient) for v in vars(default).values()):
        return verdict(False, "default NotificationService() does not build an SmtpClient")
    # unrelated code must survive the cutover
    try:
        audit = importlib.import_module("notify.audit")
        assert audit.export_csv([[1, 2]]) == "1,2" and audit.redact("ann@x.io") == "a***@x.io"
    except Exception as e:
        return verdict(False, f"unrelated notify.audit API removed or broken: {e!r}")
    return verdict(True, "service cut over to SmtpClient; notify.audit intact")

if __name__ == "__main__":
    entry(main)
