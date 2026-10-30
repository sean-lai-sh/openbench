"""Stage 4 AC3 gate: every harness config is within 5% of its real harness.

Review criterion 4: this test enforces the proxy build check (system-prompt
and tool-schema bytes within 5% of the real harness). For each harness
config it replays the committed real-harness capture's model, instruction
and workdir through the base agent at a loopback stub, and requires a PASS.
A missing capture fails the gate: a config does not count as built until its
capture is checked in (see thesis/base_agent/captures/README.md).

No model is called on either side.
"""
import unittest

from thesis.base_agent import build_check as B
from thesis.base_agent import config as C


def harness_configs():
    out = []
    for path in sorted(C.CONFIG_DIR.glob("*.toml")):
        if path.stem != "fixed":
            cfg = C.load_config(path.stem)
            if cfg.get("harness", "base") != "base":
                out.append(cfg)
    return out


class BuildGate(unittest.TestCase):
    def test_every_harness_config_has_a_capture_and_passes(self):
        configs = harness_configs()
        self.assertEqual(sorted(c["name"] for c in configs), ["opencode", "pi"])
        for cfg in configs:
            with self.subTest(config=cfg["name"]):
                try:
                    res = B.gate(cfg, B.CAPTURES / cfg["name"])
                except ValueError as exc:
                    self.fail(str(exc))
                c = res["comparison"]
                self.assertTrue(c["pass"], f"{cfg['name']} (base_agent_version {res['version']['base_agent_version']}): "
                                f"system {c['system']}, tools {c['tools']}, tool names {c['tool_names']}")


if __name__ == "__main__":
    unittest.main()
