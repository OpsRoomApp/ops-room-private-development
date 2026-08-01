(()=>{
  'use strict';
  const byId=id=>document.getElementById(id);
  const text=id=>(byId(id)?.textContent||'').trim();
  function copyCanvases(source,clone){
    const a=[...source.querySelectorAll('canvas')],b=[...clone.querySelectorAll('canvas')];
    a.forEach((canvas,index)=>{
      const out=b[index];if(!out)return;
      const w=Math.max(1,canvas.width||1),h=Math.max(1,canvas.height||1);
      out.width=w;out.height=h;
      const ctx=out.getContext('2d');if(ctx)ctx.drawImage(canvas,0,0,w,h);
    });
  }
  function cloneNode(source){const clone=source.cloneNode(true);copyCanvases(source,clone);if(source.id)clone.classList.add(`pdf-source-${source.id}`);clone.querySelectorAll('[id]').forEach(el=>el.removeAttribute('id'));clone.removeAttribute('id');return clone}
  function header(page,title,total){
    const route=`${text('originIcao')||'----'} ? ${text('destinationIcao')||'----'}`;
    const cs=text('flightCallsign')||'FLIGHT';
    const logo=byId('airlineLogoTop')?.innerHTML||'';const div=document.createElement('div');div.className='pdf-page-head';div.innerHTML=`<div class="pdf-brand">${logo}<span>OPS ROOM <b>FLIGHT ANALYSIS</b></span></div><div class="pdf-route"><strong>${route}</strong><span>${cs} · ${title} · PAGE ${page} / ${total}</span></div>`;return div;
  }
  function footer(page,total){const d=document.createElement('div');d.className='pdf-page-foot';d.innerHTML=`<span>OPS ROOM 0.25.51</span><span>PAGE ${page} / ${total}</span><span>OPS ROOM</span>`;return d}
  function page(cls,title,bodyBuilder){const p=document.createElement('section');p.className=`pdf-page ${cls}`;p.dataset.title=title;const body=document.createElement('div');body.className='pdf-page-body';bodyBuilder(body);p.append(body);return p}
  function simpleSectionPage(cls,title,id){return page(cls,title,body=>body.append(cloneNode(byId(id))))}
  function invoicePages(){
    const finance=byId('finance');if(!finance)return[];
    const result=[];
    const summary=page('pdf-finance-summary','FINANCE',body=>{
      const section=cloneNode(finance);section.querySelectorAll('.invoice-card').forEach(x=>x.remove());body.append(section);
    });result.push(summary);
    const cards=[...finance.querySelectorAll('.invoice-card')];
    const perPage=4;
    for(let start=0;start<cards.length;start+=perPage){
      result.push(page('pdf-finance-receipts','GSX RECEIPTS',body=>{
        const title=document.createElement('div');title.className='pdf-subtitle';title.textContent=`GSX SERVICE RECEIPTS · ${start+1}-${Math.min(start+perPage,cards.length)} OF ${cards.length}`;body.append(title);
        const grid=document.createElement('div');grid.className='pdf-invoice-grid';cards.slice(start,start+perPage).forEach(card=>grid.append(cloneNode(card)));body.append(grid);
      }));
    }
    return result;
  }
  function reviewPages(){
    const violations=[...byId('violationList')?.children||[]],timeline=[...byId('timelineList')?.children||[]];
    const notes=(byId('pilotNotes')?.textContent||'No notes were added to this flight.').trim();
    const perCol=9,maxPages=Math.max(1,Math.ceil(Math.max(violations.length,timeline.length)/perCol));const pages=[];
    for(let i=0;i<maxPages;i++)pages.push(page('pdf-review','FLIGHT REVIEW',body=>{
      const grid=document.createElement('div');grid.className='pdf-review-grid';
      const col=(heading,rows)=>{const wrap=document.createElement('article');wrap.className='pdf-review-column';wrap.innerHTML=`<h3>${heading}</h3>`;const list=document.createElement('div');list.className='review-list';rows.forEach(row=>list.append(cloneNode(row)));if(!rows.length)list.innerHTML='<div class="empty">No entries.</div>';wrap.append(list);return wrap};
      grid.append(col('DEVIATIONS AND FLAGS',violations.slice(i*perCol,(i+1)*perCol)),col('EVENT TIMELINE',timeline.slice(i*perCol,(i+1)*perCol)));body.append(grid);
      if(i===maxPages-1){const n=document.createElement('article');n.className='pdf-notes';n.innerHTML='<h3>PILOT NOTES</h3>';const para=document.createElement('p');para.textContent=notes;n.append(para);body.append(n)}
    }));
    return pages;
  }
  function build(){
    if(window.__OPSROOM_PDF_READY__)return;
    const original=byId('reportContent');if(!original||original.hidden)return;
    // Ensure canvases have the final deterministic pixel content before cloning.
    try{window.dispatchEvent(new Event('resize'))}catch{}
    const pages=[];
    pages.push(page('pdf-overview','OVERVIEW',body=>{body.append(cloneNode(byId('summary')),cloneNode(byId('profile')))}));
    pages.push(simpleSectionPage('pdf-departure','DEPARTURE','departure'));
    pages.push(simpleSectionPage('pdf-enroute','ENROUTE','enroute'));
    pages.push(simpleSectionPage('pdf-approach','APPROACH','approach'));
    pages.push(simpleSectionPage('pdf-landing','LANDING','landing'));
    pages.push(...invoicePages());
    pages.push(...reviewPages());
    const doc=document.createElement('main');doc.id='pdfDocument';
    const total=pages.length;pages.forEach((p,index)=>{p.prepend(header(index+1,p.dataset.title||'PIREP',total));p.append(footer(index+1,total));doc.append(p)});
    document.body.append(doc);document.documentElement.classList.add('pdf-export');
    requestAnimationFrame(()=>requestAnimationFrame(()=>{window.__OPSROOM_PDF_READY__=true;document.documentElement.dataset.pirepPdfReady='1'}));
  }
  const wait=()=>{if(window.__OPSROOM_PIREP_READY__)build();else setTimeout(wait,50)};wait();
})();
