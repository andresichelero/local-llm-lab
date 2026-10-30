import bottle
import pytest


def test_private_contract():
    r = bottle.Router()
    r.add('/p/<n:int>/<word>', 'GET', 'ok')
    assert r.match({'PATH_INFO': '/p/-7/abc', 'REQUEST_METHOD': 'GET'}) == ('ok', {'n': -7, 'word': 'abc'})
    assert r.match({'PATH_INFO': '/p/0/x', 'REQUEST_METHOD': 'GET'})[1]['n'] == 0
    r.add_filter('custom', lambda conf: (r'\d+', lambda value: 'converted:' + value, None))
    r.add('/custom/<v:custom>', 'GET', 'custom')
    assert r.match({'PATH_INFO': '/custom/42', 'REQUEST_METHOD': 'GET'}) == ('custom', {'v': 'converted:42'})
    def reject(value):
        raise ValueError('invalid')
    r.add_filter('reject', lambda conf: (r'\w+', reject, None))
    r.add('/bad/<v:reject>', 'GET', 'bad')
    with pytest.raises(bottle.HTTPError) as error:
        r.match({'PATH_INFO': '/bad/value', 'REQUEST_METHOD': 'GET'})
    assert error.value.status_code == 400
