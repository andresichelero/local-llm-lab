import bottle

def redirect(target, protocol='HTTP/1.1', code=None):
    bottle.request.bind({'SERVER_PROTOCOL': protocol, 'PATH_INFO': '/dir/page', 'HTTP_HOST': 'example.test', 'wsgi.url_scheme': 'http'})
    bottle.response.bind()
    try:
        bottle.redirect(target, code)
    except bottle.HTTPResponse as result:
        return result.status_code, result.headers['Location']
    raise AssertionError('redirect did not raise')
def test_contract():
    assert redirect('next') == (303, 'http://example.test/dir/next')
    assert redirect('/root', 'HTTP/1.0') == (302, 'http://example.test/root')
    assert redirect('https://other.test/a', code=307) == (307, 'https://other.test/a')
