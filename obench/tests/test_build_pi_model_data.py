import json
from pathlib import Path

from thesis.ab import build_pi


def _tree(root: Path) -> Path:
    ai = root / "packages" / "ai"
    ai.mkdir(parents=True)
    (ai / "package.json").write_text(json.dumps({"name": "@earendil-works/pi-ai", "version": "1.4.0"}))
    return ai / "src" / "providers" / "data"


def _fake_pack(calls):
    def pack(root, env, name, version, dest):
        calls.append((name, version))
        data = Path(dest) / "dist" / "providers" / "data"
        data.mkdir(parents=True)
        (data / ".manifest.json").write_text('{"schemaVersion":6}')
        (data / "openai.json").write_text('{"published":true}')
        (data / "anthropic.json").write_text('{"published":true}')
    return pack


def test_hydrates_missing_data_from_published_package(tmp_path, monkeypatch):
    data = _tree(tmp_path)
    data.mkdir(parents=True)
    (data / "openai.json").write_text('{"committed":true}')
    calls = []
    monkeypatch.setattr(build_pi, "_pack_into", _fake_pack(calls))
    build_pi._hydrate_model_data(tmp_path, {})
    assert calls == [("@earendil-works/pi-ai", "1.4.0")]
    assert json.loads((data / ".manifest.json").read_text()) == {"schemaVersion": 6}
    assert json.loads((data / "anthropic.json").read_text()) == {"published": True}
    assert json.loads((data / "openai.json").read_text()) == {"committed": True}


def test_skips_when_manifest_committed(tmp_path, monkeypatch):
    data = _tree(tmp_path)
    data.mkdir(parents=True)
    (data / ".manifest.json").write_text("{}")
    calls = []
    monkeypatch.setattr(build_pi, "_pack_into", _fake_pack(calls))
    build_pi._hydrate_model_data(tmp_path, {})
    assert calls == []
