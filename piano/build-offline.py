#!/usr/bin/env python3
"""Bundle the multi-page site into one standalone offline HTML file."""
import re, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))

css  = open('site.css').read()
cat  = open('catalog.js').read()
play = open('play.html').read()

play_styles = re.findall(r'<style>(.*?)</style>', play, re.S)
play_body   = re.search(r'<body>(.*?)</body>', play, re.S).group(1)
play_body   = re.sub(r'<nav class="sitenav">.*?</nav>', '', play_body, flags=re.S)
play_script = re.search(r'<script>(.*?)</script>\s*$', play_body, re.S).group(1)
play_markup = re.sub(r'<script>.*?</script>\s*$', '', play_body, flags=re.S)

pages, scripts = {}, {}
for f in ['index.html', 'songs.html', 'learn.html', 'progress.html']:
    key = f.split('.')[0]
    s = open(f).read()
    body = re.search(r'<body>(.*?)</body>', s, re.S).group(1)
    body = re.sub(r'<nav class="nav">.*?</nav>', '', body, flags=re.S)
    body = body.replace('<script src="catalog.js"></script>', '')
    scripts[key] = "\n".join(re.findall(r'<script>(.*?)</script>', body, re.S))
    pages[key]   = re.sub(r'<script>.*?</script>', '', body, flags=re.S)

# progress page renders lazily via the router
# expose progress renderer to the router; only replace the final bare call
scripts['progress'] = scripts['progress'].rstrip()
assert scripts['progress'].endswith('render();')
scripts['progress'] = scripts['progress'][:-len('render();')] + 'window.renderProgress=render; render();'

init = "".join(
    "<script>(function(){%s})();</script>\n" % scripts[k]
    for k in ['index', 'songs', 'learn', 'progress'] if scripts[k].strip())

html = f'''<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🎹 پیانو استودیو — نسخه کامل آفلاین</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🎹</text></svg>">
<style>{css}</style>
<style>{"".join(play_styles)}</style>
<style>
  body{{display:block}}
  .pg{{display:none}} .pg.on{{display:block}}
  #pg-play main{{padding:14px;display:flex;flex-direction:column;gap:14px}}
  #pg-play header{{padding:12px 16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap;
    border-bottom:1px solid var(--line);position:static;background:none}}
  .nav a.lnk,.brand,.navCta{{cursor:pointer}}
</style>
</head>
<body>
<nav class="nav"><div class="container">
  <a class="brand" data-go="home">🎹 پیانو <em>استودیو</em></a>
  <button class="burger" onclick="document.getElementById('m').classList.toggle('open')">☰</button>
  <ul id="m">
    <li><a class="lnk on" data-go="home">خانه</a></li>
    <li><a class="lnk" data-go="songs">آهنگ‌ها</a></li>
    <li><a class="lnk" data-go="learn">آموزش</a></li>
    <li><a class="lnk" data-go="progress">پیشرفت من</a></li>
    <li><a class="lnk" data-go="play">نواختن</a></li>
  </ul>
  <a class="navCta" data-go="play">▶ شروع نواختن</a>
</div></nav>

<div class="pg on" id="pg-home">{pages['index']}</div>
<div class="pg" id="pg-songs">{pages['songs']}</div>
<div class="pg" id="pg-learn">{pages['learn']}</div>
<div class="pg" id="pg-progress">{pages['progress']}</div>
<div class="pg" id="pg-play">{play_markup}</div>

<script>{cat}</script>
{init}
<script>{play_script}</script>
<script>
window.stopAllX = stopAll;
window.openSong = function(id){{
  var i = SONGS.findIndex(function(s){{ return s.id===id; }});
  if(i<0) return;
  selectSong(i);
  var el = listEl.children[i];
  if(el && el.scrollIntoView) el.scrollIntoView({{block:'nearest'}});
  setTimeout(function(){{ document.getElementById('btnTeach').click(); }}, 250);
}};
function go(p, song){{
  document.querySelectorAll('.pg').forEach(function(x){{ x.classList.toggle('on', x.id==='pg-'+p); }});
  document.querySelectorAll('.nav .lnk').forEach(function(a){{ a.classList.toggle('on', a.dataset.go===p); }});
  document.getElementById('m').classList.remove('open');
  window.scrollTo(0,0);
  if(p!=='play') window.stopAllX();
  if(p==='progress' && window.renderProgress) window.renderProgress();
  if(p==='play'){{ buildKB(); paintProgress(); if(song) window.openSong(song); }}
}}
document.addEventListener('click', function(e){{
  var a = e.target.closest('[data-go]');
  if(a){{ e.preventDefault(); go(a.dataset.go); return; }}
  var s = e.target.closest('a[href*="play.html?song="]');
  if(s){{ e.preventDefault(); go('play', s.getAttribute('href').split('song=')[1]); return; }}
  var l = e.target.closest('a[href$=".html"]');
  if(l){{ var f = l.getAttribute('href').replace('.html','');
          e.preventDefault(); go(f==='index' ? 'home' : f); }}
}});
if(window.renderProgress) window.renderProgress();
</script>
</body></html>'''

open('piano-studio-offline.html', 'w').write(html)
print('built piano-studio-offline.html —', len(html), 'bytes')
