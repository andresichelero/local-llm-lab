import bottle

assert list(bottle.parse_range_header('bytes=2-4', 10)) == [(2, 5)]
print('visible: PASS')
