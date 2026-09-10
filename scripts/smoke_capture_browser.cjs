// Run smoke_object_capture.py first to create the local source fixture.
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const {chromium}=require('../web/node_modules/playwright');
(async()=>{
 const b=await chromium.launch(); const p=await b.newPage({viewport:{width:1280,height:900}});
 const errors=[]; p.on('pageerror',e=>errors.push(e.message));
 await p.goto('http://127.0.0.1:3011',{waitUntil:'networkidle'});
 await p.locator('input[type=file]:not([capture])').setInputFiles(path.join(root, 'output/object-api-smoke/source.png'));
 await p.getByRole('radio',{name:/Backend segmentation cutout/}).check();
 await p.getByRole('button',{name:'Extract mask',exact:true}).click();
 await p.getByRole('button',{name:'Accept A',exact:true}).waitFor();
 await p.waitForFunction(()=>Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Accept A'&&!b.disabled),{timeout:60000});
 await p.getByRole('button',{name:'Accept A',exact:true}).click();
 await p.getByRole('button',{name:/Build guided font/}).click();
 await p.getByRole('link',{name:/TTF/}).first().waitFor({timeout:120000});
 await p.getByLabel('Proof text').waitFor({timeout:30000});
 await p.waitForFunction(()=>Array.from(document.fonts).some(f=>f.family.startsWith('generated-')&&f.status==='loaded'),{timeout:30000});
 const proof=await p.getByLabel('Proof text').inputValue();
 await p.screenshot({path:path.join(root, 'output/browser-object-proof.png'),fullPage:true});
 await p.getByLabel('Proof text').fill('AB');
 await p.getByText(/Missing from proof text: B/).waitFor();
 const links=await p.getByRole('link',{name:/TTF/}).evaluateAll(links=>links.map(l=>({text:l.textContent,href:l.href})));
 const response=await p.request.get(links[0].href); if(!response.ok()) throw new Error('TTF download failed');
 const ttfBytes=(await response.body()).length;
 console.log(JSON.stringify({proof,links,ttfBytes,fontFaceLoaded:true,missingGlyphWarning:true,errors},null,2));
 await b.close();
})().catch(e=>{console.error(e);process.exit(1)});
