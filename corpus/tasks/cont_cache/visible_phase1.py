import bottle
import os
import tempfile

def status(ims=None, tag=None):
    with tempfile.TemporaryDirectory() as root:
        path=os.path.join(root, 'asset.txt')
        with open(path, 'wb') as f: f.write(b'abc')
        os.utime(path, (1600000000, 1600000000))
        env={'REQUEST_METHOD':'GET'}
        if ims is not None: env['HTTP_IF_MODIFIED_SINCE']=ims
        if tag is not None: env['HTTP_IF_NONE_MATCH']=tag
        bottle.request.bind(env)
        res=bottle.static_file('asset.txt', root, etag='AbC')
        if hasattr(res.body, 'close'): res.body.close()
        return res.status_code
assert status(ims=bottle.http_date(1600000000)) == 304
