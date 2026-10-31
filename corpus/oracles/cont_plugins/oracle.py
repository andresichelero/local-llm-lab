import bottle

class Plugin:
    def __init__(self, name, label): self.name, self.label = name, label
    def apply(self, callback, route):
        def wrapped(): return self.label + callback()
        return wrapped

def route(skip=None):
    app = bottle.Bottle(); app.plugins[:] = [Plugin('same', 'global:')]
    return bottle.Route(app, '/', 'GET', lambda: 'ok', plugins=[Plugin('same', 'route:')], skiplist=skip)
def test_contract():
    assert route().call() == 'route:ok'
    assert route([Plugin]).call() == 'ok'
    assert route(['same']).call() == 'ok'
    assert route([True]).call() == 'ok'
    r=route(); r.skiplist=[r.plugins[0]]
    assert r.call() == 'global:ok'
