import bottle
import pytest


def test_private_contract():
    r = bottle.Router()
    r.add('/p/<n:int>/<word>', 'GET', 'ok')
    assert r.match({'PATH_INFO': '/p/-7/abc', 'REQUEST_METHOD': 'GET'}) == ('ok', {'n': -7, 'word': 'abc'})
    assert r.match({'PATH_INFO': '/p/0/x', 'REQUEST_METHOD': 'GET'})[1]['n'] == 0
    def reject(value):
        raise ValueError('invalid')
    r.add_filter('reject', lambda conf: (r'\w+', reject, None))
    r.add('/bad/<v:reject>', 'GET', 'bad')
    with pytest.raises(bottle.HTTPError) as error:
        r.match({'PATH_INFO': '/bad/value', 'REQUEST_METHOD': 'GET'})
    assert error.value.status_code == 400
