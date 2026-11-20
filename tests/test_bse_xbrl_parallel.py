"""BSE shareholding XBRL files fetched side by side (collectors/bse/events.fetch_xbrls, 20 Nov 2026)."""
import threading
import time

from collectors.bse import events
from collectors.bse.client import Blocked, Missing


class Fake:
    def __init__(self, refuse=(), missing=(), delay=0.0, gate=None):
        self.asked, self.refuse, self.missing, self.delay, self.gate = [], set(refuse), set(missing), delay, gate

    def shareholding_xbrl(self, url, covers=None):
        if self.gate is not None:
            self.gate.wait(5)
        time.sleep(self.delay)
        self.asked.append(url)
        if url in self.refuse:
            if self.gate is not None:
                self.gate.set()
            raise Blocked(f'HTTP 403 from {url}')
        if url in self.missing:
            raise Missing(f'HTTP 404 from {url}')
        return f'<x>{url}</x>'.encode()

    def close(self):
        pass


def todo(n):
    return [(i, f'/x/{i}.html', {'bse_code': str(500000 + i), 'quarter_end': '2026-09-30'}) for i in range(n)]


def test_parallel_matches_serial_and_asks_each_file_once():
    items = todo(13)
    serial = events.fetch_xbrls(Fake(missing={'/x/4.html'}), items, workers=1)
    made = []

    def factory():
        made.append(Fake(missing={'/x/4.html'}, delay=0.005))
        return made[-1]
    par = events.fetch_xbrls(object(), items, workers=4, client_factory=factory)
    assert len(made) == 4
    assert sorted(u for f in made for u in f.asked) == sorted(u for _, u, _ in items)
    assert par.keys() == serial.keys()
    for i in serial:
        assert par[i][0] == serial[i][0]
        if serial[i][0] == 'ok':
            assert par[i][1] == serial[i][1]
    assert par[4][0] == 'failed'


def test_a_refusal_stops_every_lane():
    items = todo(40)
    gate = threading.Event()
    clients = iter([Fake(refuse={'/x/0.html'}), Fake(gate=gate, delay=0.02), Fake(gate=gate, delay=0.02),
                    Fake(gate=gate, delay=0.02)])
    out = events.fetch_xbrls(object(), items, workers=4, client_factory=lambda: next(clients))
    assert out[0][0] == 'blocked'
    assert len(out) < 10   # the other lanes stopped after at most their file in flight


def test_a_test_double_is_asked_one_file_at_a_time_in_order():
    f = Fake(refuse={'/x/2.html'})
    out = events.fetch_xbrls(f, todo(5))
    assert f.asked == ['/x/0.html', '/x/1.html', '/x/2.html'] and sorted(out) == [0, 1, 2]
