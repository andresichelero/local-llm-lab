import bottle


def test_private_contract():
    assert bottle._hkey('x_request_id') == 'X-Request-Id'
    assert bottle._hkey('content-type') == 'Content-Type'
