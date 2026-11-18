"""Read-only source comparison of requested landing and its Django copy."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path('/Users/beibitkazbanov/Desktop/work/Tuysqan Coffee')
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
manifest=json.loads((ROOT/'docs/landing-source-checksums.json').read_text())
for name,expected in manifest.items():
 assert digest(SOURCE/name)==expected, 'Source changed: '+name
for name in ['styles.css','menu-data.js','favicon.svg','manifest.webmanifest']:
 assert digest(SOURCE/name)==digest(ROOT/'static/landing'/name),'Copy mismatch: '+name
js=(SOURCE/'app.js').read_text().replace('"assets/','"/static/landing/assets/').replace("'assets/","'/static/landing/assets/")
assert js==(ROOT/'static/landing/app.js').read_text(),'JS changes beyond asset URLs'
html=(SOURCE/'index.html').read_text()
pattern=r'((?:src|href|data-gallery-src)=["\'])((?:assets/[^"\']+|styles\.css|menu-data\.js|app\.js|/?favicon\.svg|/?manifest\.webmanifest))(["\'])'
html=re.sub(pattern,lambda m:m[1]+'/static/landing/'+m[2].lstrip('/')+m[3],html)
copied=(ROOT/'templates/landing.html').read_text()
copied=re.sub(r'<!-- DJANGO ORDER INTEGRATION START -->.*?<!-- DJANGO ORDER INTEGRATION END -->\s*','',copied,flags=re.S)
assert html==copied,'Base HTML changes beyond asset URLs/additive integration'
files=[p for p in (SOURCE/'assets').rglob('*') if p.is_file()]
for path in files:
 assert digest(path)==digest(ROOT/'static/landing/assets'/path.relative_to(SOURCE/'assets')),'Asset mismatch: '+str(path)
print(json.dumps({'source_manifest_unchanged':len(manifest),'identical_static_assets':len(files),'css_data_icons_manifest':'byte identical','html_js':'identical after asset URL mapping'},ensure_ascii=False))
