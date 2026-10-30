import bottle

assert bottle.http_date(0) == 'Thu, 01 Jan 1970 00:00:00 GMT'
print('visible: PASS')
