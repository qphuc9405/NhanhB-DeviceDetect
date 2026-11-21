import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from fastapi.testclient import TestClient
from backend.app import main
from research.detectors import ProbeConfig
@pytest.fixture
def client(tmp_path,monkeypatch):
    cfg=tmp_path/'config.json';cfg.write_text(ProbeConfig().model_dump_json())
    monkeypatch.setenv('WIFI_PROBE_DATA_DIR',str(tmp_path/'runtime'))
    monkeypatch.setenv('WIFI_PROBE_CONFIG',str(cfg))
    with TestClient(main.app) as c:yield c
