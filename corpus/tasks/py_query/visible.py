import bottle

assert bottle._parse_qsl('q=two+words') == [('q', 'two words')]
print('visible: PASS')
