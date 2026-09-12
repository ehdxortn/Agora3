from research_engine.parity import verify_parity

def test_parity_exact_passes():
 v=[{'open_time':'2026-01-01T00:00:00+00:00','close':100.0,'features':{'x':1.25},'signal':True}];r=verify_parity({'vectors':v},v,1e-10);assert r['passed'] is True
def test_parity_signal_mismatch_fails():
 e=[{'open_time':'2026-01-01T00:00:00+00:00','close':100.0,'features':{'x':1.25},'signal':True}];o=[{'open_time':'2026-01-01T00:00:00+00:00','close':100.0,'features':{'x':1.25},'signal':False}];r=verify_parity({'vectors':e},o,1e-10);assert r['passed'] is False
