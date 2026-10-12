"""Prueba opcional, SIN backend ni GLB, de layout y activación por clic.

Instalar dependencias de prueba si se desea ejecutar en Windows:
  python -m pip install playwright
  python -m playwright install chromium
  python tests/browser_smoke_v52.py

El código lee automáticamente los archivos ya instalados en frontend/.
"""
from pathlib import Path
import asyncio
import os
import re
from playwright.async_api import async_playwright

FRONTEND = Path(__file__).resolve().parents[1]
HG = FRONTEND / 'src/worlds/hologram'
CORE = FRONTEND / 'src/core'

def required(path):
    if not path.is_file():
        raise FileNotFoundError(f'Falta archivo requerido del frontend: {path}')
    return path.read_text(encoding='utf-8')

HTML = required(HG/'index.html')
for link in re.findall(r'<link rel="stylesheet" href="\.\/[^\"]+"\s*/>', HTML):
    HTML = HTML.replace(link, '')
HTML = re.sub(r'<script type="module" src="\.\/main\.js\?[^\"]+"></script>', '', HTML)
STYLES = '\n'.join([
    required(HG/'style.css').replace('@import "../../core/present.css";', ''),
    required(HG/'hologram-premium-v5.css'),
    required(HG/'hologram-projection-v52.css'),
])
HTML = HTML.replace('</head>', '<style>'+STYLES+'</style></head>')
BOOT_SOURCE = required(CORE/'boot-loader-v43.js').replace("import './boot-loader-v43.css';", '')
BOOT_CSS = required(CORE/'boot-loader-v43.css')

async def main():
    async with async_playwright() as playwright:
        kwargs = {'headless': True}
        if os.environ.get('CHROMIUM_EXECUTABLE'):
            kwargs['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
        browser = await playwright.chromium.launch(**kwargs)
        for width, height in [(1440,900),(1080,1080),(1920,1080),(390,844)]:
            page = await browser.new_page(viewport={'width':width,'height':height})
            await page.set_content(HTML)
            await page.evaluate('''()=>{
                document.body.classList.add('hg-fan');
                const panel=document.getElementById('hgDataPanel');
                panel.classList.add('hg-with-data','hg-has-kpis');
                document.getElementById('result').innerHTML=`
                <section class="hg-brief"><div class="hg-kpis">
                  <article class="hg-kpi"><span>Ocupación</span><strong>82%</strong></article>
                  <article class="hg-kpi"><span>Personal</span><strong>24</strong></article>
                  <article class="hg-kpi"><span>Debe ocultarse</span><strong>3</strong></article>
                </div></section>`;
            }''')
            result = await page.evaluate('''()=>({
                background:getComputedStyle(document.body).backgroundColor,
                overflow:document.documentElement.scrollWidth>innerWidth,
                mic:getComputedStyle(document.querySelector('.hud')).display,
                third:getComputedStyle(document.querySelectorAll('.hg-kpi')[2]).display
            })''')
            assert result == {'background':'rgb(0, 0, 0)','overflow':False,'mic':'none','third':'none'}, result
            print(f'FAN {width}x{height}: OK')
            await page.close()

        page = await browser.new_page(viewport={'width':1440,'height':900})
        await page.set_content('<html><head><style>'+BOOT_CSS+'\n'+required(HG/'hologram-projection-v52.css')+'</style></head><body></body></html>')
        await page.evaluate('''async src=>{
            const url=URL.createObjectURL(new Blob([src],{type:'text/javascript'}));
            const {MiaBootLoader}=await import(url);
            window.boot=new MiaBootLoader({mode:'hologram'});
            window.audioCalls=[];
            window.bootPromise=window.boot.complete({onContinue:()=>{
                window.audioCalls.push(navigator.userActivation?.isActive);
                return {status:'playing'};
            }});
        }''', BOOT_SOURCE)
        await page.wait_for_selector('[data-boot-continue]:visible')
        assert await page.locator('[data-boot-percent]').inner_text() == '100'
        await page.locator('[data-boot-continue]').click()
        await page.evaluate('window.bootPromise')
        assert await page.evaluate('window.audioCalls') == [True]
        assert await page.locator('.mia-boot').count() == 0
        print('Loading 100 % y clic auténtico de voz: OK')
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
