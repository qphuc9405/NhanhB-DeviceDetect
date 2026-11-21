import json
import time

from backend.app import main
from research.presence import PresenceConfig
from scripts.probe_fixture import generate
from test_in_room import SETUP, records, references
from test_presence import B, probe, status


def simulated_live(monkeypatch, rows, config=None):
    service = main.svc
    service.reset_stream()
    service.mode, service.connection = 'serial', 'connected'
    service.timeline_origin = 100.
    if config is not None:
        service.dashboard.config = config
        service.dashboard.setup_id = config.setup_id
    def ingest(new_rows):
        for t, p in new_rows:
            service.ingest(json.dumps(p), now=service.timeline_origin + t)
    ingest(rows)
    monkeypatch.setattr(service, 'alg_now', lambda: service.clock - service.timeline_origin)
    return service, ingest


def test_idle_and_backend_valid_empty_are_distinguished(client, monkeypatch):
    idle = client.get('/api/probe/dashboard').json()
    assert idle['source'] is None and idle['status'] == 'disconnected'
    assert all(value is None for value in idle['metrics'].values())
    service, _ = simulated_live(monkeypatch, [status(0), status(1)])
    observed = client.get('/api/probe/dashboard').json()
    assert observed['source'] == 'LIVE' and observed['status'] == 'empty'
    assert observed['metrics']['confirmed_count'] == observed['metrics']['raw_mac_count'] == 0
    assert observed['metrics']['estimated_in_room_count'] is None
    assert observed['source_id'] == client.get('/api/probe/state').json()['dashboard_source_id']
    service.connection = 'reconnecting'
    lost = client.get('/api/probe/dashboard').json()
    assert lost['status'] == 'disconnected' and lost['metrics']['raw_mac_count'] is None


def test_live_aliases_history_departure_and_disconnect(client, monkeypatch):
    config = main.svc.dashboard.config.model_copy(update={'presence': PresenceConfig(
        observation_window_s=8, min_observation_spacing_s=2, stale_timeout_s=4, departure_timeout_s=9)})
    rows = sorted([status(t) for t in (0, 2, 4)] + [probe(t) for t in (0, .1, .2)]
                  + [probe(t, B) for t in (2, 4, 4.1)], key=lambda row: row[0])
    service, ingest = simulated_live(monkeypatch, rows, config)
    response = client.get('/api/probe/dashboard')
    report = response.json()
    assert report['status'] == 'ready'
    assert report['metrics']['raw_mac_count'] == report['metrics']['active_mac_count'] == 2
    assert report['metrics']['inferred_cluster_count'] == report['metrics']['confirmed_count'] == 1
    assert report['metrics']['location_unknown_count'] == 1
    assert report['metrics']['estimated_in_room_count'] is None
    row, = report['clusters']
    assert row['mac_alias_count'] == 2 and row['presence_state'] == 'CONFIRMED'
    assert row['association_history'][-1]['reason'] == 'complete_link_match'
    assert '02:00:00:00:00:' not in response.text

    ingest([status(t) for t in (6, 8, 10)])
    stale = client.get('/api/probe/dashboard').json()
    assert stale['metrics']['stale_count'] == 1 and stale['clusters'][0]['presence_state'] == 'STALE'
    ingest([status(t) for t in (12, 14)])
    report = client.get('/api/probe/dashboard').json()
    left, = report['clusters']
    assert left['cluster_id'] == row['cluster_id'] and left['presence_state'] == 'ABSENT'
    assert left['state_history'][-1]['reason'] == 'observation_timeout'
    assert report['metrics']['confirmed_count'] == 0 and report['metrics']['absent_count'] == 1
    assert [point['confirmed_count'] for point in report['history']] == [1, 0, 0]

    service.connection = 'reconnecting'
    lost = client.get('/api/probe/dashboard').json()
    assert lost['history'][-1]['confirmed_count'] is None


def test_calibrated_current_room_estimate_uses_real_collector_records(client, monkeypatch):
    cfg = main.svc.dashboard.config.model_copy(update={'setup_id': SETUP, 'calibration': references()})
    simulated_live(monkeypatch, records([-80] * 6), cfg)
    report = client.get('/api/probe/dashboard').json()
    assert report['calibration_status'] == 'ready'
    assert report['metrics']['estimated_in_room_count'] == 1
    assert report['clusters'][0]['location_state'] == 'in_room_confirmed'


def test_replay_and_demo_use_collector_and_label_each_source(client):
    folder = main.svc.store.root / 'experiments' / 'room-test'
    generate(folder)
    meta = folder / 'metadata.json'
    meta.write_text(json.dumps(dict(json.loads(meta.read_text()), id='room-test', synthetic=False)))
    for session, source in [('room-test', 'REPLAY'), ('synthetic-probe-demo', 'DEMO')]:
        assert client.post('/api/probe/replay', json={'name': session, 'speed': 100}).status_code == 200
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            report = client.get('/api/probe/dashboard').json()
            if report['status'] == 'finished':
                break
            time.sleep(.03)
        assert report['source'] == source and report['status'] == 'finished'
        assert report['metrics']['raw_mac_count'] == 2
        assert report['metrics']['inferred_cluster_count'] == 2
        assert report['metrics']['estimated_in_room_count'] is None
        assert client.post('/api/probe/disconnect').status_code == 200
