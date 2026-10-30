import bottle


def test_private_contract():
    response = bottle.BaseResponse()
    response.set_cookie('session', {'id': 3}, secret='key')
    value = response._cookies['session'].value
    request = bottle.BaseRequest({'HTTP_COOKIE': 'session=' + value + '; other=' + value})
    assert request.get_cookie('session', secret='key') == {'id': 3}
    assert request.get_cookie('other', default='missing', secret='key') == 'missing'
    assert request.get_cookie('session', default='bad', secret='wrong') == 'bad'
    assert request.get_cookie('absent', default='missing', secret='key') == 'missing'
