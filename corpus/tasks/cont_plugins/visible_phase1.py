import bottle

class Plugin:
    def __init__(self, name, label): self.name, self.label = name, label
    def apply(self, callback, route):
        def wrapped(): return self.label + callback()
        return wrapped

def route(skip=None):
    app = bottle.Bottle(); app.plugins[:] = [Plugin('same', 'global:')]
    return bottle.Route(app, '/', 'GET', lambda: 'ok', plugins=[Plugin('same', 'route:')], skiplist=skip)
assert route().call() == 'route:ok'
