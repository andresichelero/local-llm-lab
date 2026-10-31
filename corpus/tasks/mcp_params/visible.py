import bottle

assert bottle._parse_http_header('text/plain') == [('text/plain', {})]
print('visible: PASS')
