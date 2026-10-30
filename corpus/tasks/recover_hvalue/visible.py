import bottle

assert bottle._hval(' x ') == ' x '
print('visible: PASS')
