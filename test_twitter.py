import yt_dlp
opts = {
    'quiet': True,
    'no_warnings': True,
    'format': 'best',
    'noplaylist': True,
    'socket_timeout': 30,
    'http_timeout': 30,
}
ydl = yt_dlp.YoutubeDL(opts)
info = ydl.extract_info('https://x.com/elonmusk/status/1936706483206486224', download=False)
if info:
    print('title:', info.get('title','')[:50])
    print('ext:', info.get('ext'))
    print('url:', (info.get('url') or '')[:100])
else:
    print('no info')
