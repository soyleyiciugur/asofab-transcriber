<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ASOFAB Transcriber</title>
<style>
:root{--bg:#14161a;--panel:#1d2026;--panel2:#252932;--line:#333845;--fg:#e8eaf0;--mute:#98a0b3;--acc:#d9a441;--ok:#4cb782;--bad:#e0605a;--warn:#e0a13a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
header{display:flex;align-items:center;gap:16px;padding:12px 20px;border-bottom:1px solid var(--line);background:var(--panel);position:sticky;top:0;z-index:5}
header h1{font-size:16px;letter-spacing:.14em;margin:0;color:var(--acc)}
header .sp{flex:1}
.pill{padding:2px 10px;border-radius:99px;font-size:12px;background:var(--panel2);border:1px solid var(--line);color:var(--mute)}
.pill.ok{color:var(--ok);border-color:var(--ok)}.pill.bad{color:var(--bad);border-color:var(--bad)}
main{max-width:1100px;margin:0 auto;padding:18px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
input,select,textarea,button{font:inherit;color:var(--fg);background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:7px 10px}
input[type=text],input[type=password],textarea{flex:1;min-width:200px}
textarea{width:100%;min-height:60px;resize:vertical}
button{cursor:pointer}button:hover{border-color:var(--acc)}
button.primary{background:var(--acc);color:#1a1405;border-color:var(--acc);font-weight:600}
button:disabled{opacity:.5;cursor:default}
nav{display:flex;gap:4px;margin:16px 0;border-bottom:1px solid var(--line);flex-wrap:wrap}
nav button{border:0;border-bottom:2px solid transparent;border-radius:0;background:none;color:var(--mute)}
nav button.on{color:var(--acc);border-color:var(--acc)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px;margin:12px 0}
.card h3{margin:0 0 8px;font-size:14px;color:var(--acc)}
.mute{color:var(--mute)}.small{font-size:12px}
.bar{height:8px;background:var(--panel2);border-radius:4px;overflow:hidden}
.bar>i{display:block;height:100%;background:var(--acc)}
.stages{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.stage{padding:8px;border:1px solid var(--line);border-radius:6px;background:var(--panel2)}
.stage.done{border-color:var(--ok)}.stage.running{border-color:var(--acc)}.stage.failed{border-color:var(--bad)}.stage.stopped{border-color:var(--warn)}
.err{color:var(--bad);white-space:pre-wrap}
.seg{display:grid;grid-template-columns:170px 1fr;gap:10px;padding:8px 0;border-bottom:1px solid var(--line)}
.seg.flag{border-left:3px solid var(--warn);padding-left:8px}
.seg select{width:100%}
.ctx{padding:6px 10px;background:var(--panel2);border-radius:6px;margin:4px 0}
.unc{padding:6px 10px;background:#3a2f12;border-radius:6px;margin:4px 0}
table{width:100%;border-collapse:collapse}td,th{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
a{color:var(--acc)}
.hidden{display:none}
audio{height:32px}
</style>
</head>
<body>
<header>
  <h1>ASOFAB TRANSCRIBER</h1>
  <span id="pGoogle" class="pill">Google</span>
  <span id="pHw" class="pill">donanım</span>
  <span class="sp"></span>
  <select id="jobSel" title="Önceki işler"></select>
</header>
<main>
  <div class="card">
    <div class="row">
      <input type="text" id="link" placeholder="Meet linki, Drive kayıt linki veya conferenceRecords/... kimliği">
      <button class="primary" id="go">Analyze Recording</button>
      <button id="connect">Connect Google Account</button>
    </div>
    <div id="msg" class="small" style="margin-top:8px"></div>
  </div>

  <nav id="tabs"></nav>
  <section id="view"></section>
</main>

<script>
const TOKEN="__TOKEN__";
const TABS=[["rec","Recording"],["spk","Speakers"],["rev","To Be Checked"],["tr","Transcript"],["exp","Export"],["glo","Glossary"],["set","Settings"]];
let S={tab:"rec",job:null,status:null,info:null,timer:null};
const $=s=>document.querySelector(s);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

async function api(path,opt={}){
  const o={method:opt.method||"GET",headers:{"X-ASOFAB-Token":TOKEN}};
  if(opt.body!==undefined){o.method=opt.method||"POST";o.headers["Content-Type"]="application/json";o.body=JSON.stringify(opt.body)}
  const r=await fetch("/api"+path,o);
  let d=null;try{d=await r.json()}catch(e){}
  if(!r.ok)throw new Error((d&&d.detail)||("HTTP "+r.status));
  return d;
}
function say(t,bad){const m=$("#msg");m.textContent=t||"";m.className="small "+(bad?"err":"mute")}
const clipUrl=(a,b,pad=2)=>`/api/jobs/${S.job}/clip?start=${a}&end=${b}&pad=${pad}&t=${TOKEN}`;
const fmt=s=>{s=Math.max(0,s|0);return `${(s/3600|0)}:${String((s/60|0)%60).padStart(2,"0")}:${String(s%60).padStart(2,"0")}`};

function drawTabs(){
  $("#tabs").innerHTML=TABS.map(([k,n])=>`<button data-k="${k}" class="${S.tab===k?"on":""}">${n}</button>`).join("");
  $("#tabs").querySelectorAll("button").forEach(b=>b.onclick=()=>{S.tab=b.dataset.k;drawTabs();render()});
}

async function loadStatus(){
  try{
    S.status=await api("/status");
    const st=S.status;
    $("#pGoogle").textContent=st.signed_in?"Google bağlı":(st.client_secret?"Google bağlı değil":"OAuth istemcisi yok");
    $("#pGoogle").className="pill "+(st.signed_in?"ok":"bad");
    $("#pHw").textContent=st.hardware.device==="cuda"?`GPU ${st.hardware.gpu_name||""}`:"CPU (yavaş)";
  }catch(e){say(e.message,true)}
}
async function loadJobs(){
  const js=await api("/jobs");
  const sel=$("#jobSel");
  sel.innerHTML=`<option value="">Önceki işler</option>`+js.map(j=>`<option value="${j.id}" ${j.id===S.job?"selected":""}>${esc(j.id)} · ${esc((j.link||"").slice(0,40))}</option>`).join("");
  sel.onchange=()=>{if(sel.value)openJob(sel.value)};
}
function openJob(id){S.job=id;poll();render()}

async function poll(){
  clearInterval(S.timer);
  if(!S.job)return;
  const tick=async()=>{
    try{
      S.info=await api("/jobs/"+S.job);
      if(S.tab==="rec")render();
      if(!S.info.running){clearInterval(S.timer);render()}
    }catch(e){say(e.message,true)}
  };
  await tick();
  S.timer=setInterval(tick,2000);
}

$("#go").onclick=async()=>{
  const link=$("#link").value.trim();
  if(!link)return say("Bir link girin.",true);
  try{const r=await api("/analyze",{body:{link}});say("İş başlatıldı.");await loadJobs();S.tab="rec";drawTabs();openJob(r.job)}
  catch(e){say(e.message,true)}
};
$("#connect").onclick=async()=>{
  say("Tarayıcıda Google onayını tamamlayın...");
  try{await api("/google/connect",{body:{}});say("Google hesabı bağlandı.");loadStatus()}
  catch(e){say(e.message,true)}
};

function render(){
  const v=$("#view");
  const fn={rec:vRec,spk:vSpk,rev:vRev,tr:vTr,exp:vExp,glo:vGlo,set:vSet}[S.tab];
  if(!S.job&&["rec","spk","rev","tr","exp"].includes(S.tab)){v.innerHTML=`<div class="card mute">Bir link girip analiz başlatın veya önceki işlerden birini seçin.</div>`;return}
  fn(v);
}

/* ---------------- Recording ---------------- */
function vRec(v){
  const m=(S.info&&S.info.meta)||{};
  const stages=m.stages||{};
  const names=(S.status&&S.status.stages)||Object.keys(stages);
  const prog=S.info&&S.info.progress;
  const li=m.link_info||{};
  const ev=m.evidence||{};
  const at=ev.attribution||{};
  const yes=b=>b?"✔ var":"✘ yok";
  let h=`<div class="card"><h3>Aşamalar</h3><div class="stages">`+names.map(n=>{
    const s=stages[n]||{};const f=Math.round((s.fraction||0)*100);
    return `<div class="stage ${s.status||""}"><b>${n}</b><div class="small mute">${s.status||"pending"}${s.status==="running"?" "+f+"%":""}</div>
      <div class="small"><button data-retry="${n}" class="small">Retry</button></div>
      ${s.error?`<div class="err small">${esc(s.error)}</div>`:""}</div>`}).join("")+`</div>`;
  if(prog)h+=`<div style="margin-top:10px" class="small">${esc(prog.stage)}: ${esc(prog.message)}</div><div class="bar"><i style="width:${Math.round(prog.fraction*100)}%"></i></div>`;
  h+=`<div class="row" style="margin-top:10px">${S.info&&S.info.running?`<button id="stop">Stop</button>`:`<button id="resume" class="primary">Resume</button>`}<button id="cleanup">Geçici dosyaları sil</button></div></div>`;

  h+=`<div class="card"><h3>Link ne gösteriyor?</h3><div>${esc(li.explanation||"Henüz çözümlenmedi.")}</div>`;
  if(li.drive_name)h+=`<div class="small mute">Kayıt: ${esc(li.drive_name)} (${li.drive_size?Math.round(li.drive_size/1e6)+" MB":"?"})</div>`;
  if(li.candidates&&li.candidates.length>1){
    h+=`<div style="margin-top:8px" class="small">Bulunan toplantı örnekleri (seçimi değiştirebilirsiniz):</div><table>`+li.candidates.map(c=>
      `<tr><td>${esc(c.start||"")}</td><td>${c.duration_s?Math.round(c.duration_s/60)+" dk":""}</td><td><button data-rec="${esc(c.name)}">Bunu kullan</button></td></tr>`).join("")+`</table>`;
  }
  h+=`</div>`;

  h+=`<div class="card"><h3>Gerçekte hangi kanıtlar vardı?</h3><table>
   <tr><td>Meet katılımcı kayıtları</td><td>${yes(at.meet_participants)}</td></tr>
   <tr><td>Meet transkript girdileri</td><td>${yes(at.meet_transcript_entries)}</td></tr>
   <tr><td>Kimlik için Meet verisi kullanıldı</td><td>${yes(at.native_identity_used)}</td></tr>
   <tr><td>Ayrı ses kanalları</td><td>${yes(at.separate_audio_tracks)}</td></tr>
   <tr><td>Akustik kümeleme</td><td>${yes(at.audio_clustering)}</td></tr>
   <tr><td>Sizin onaylarınız</td><td>${yes(at.user_calibration)}</td></tr>
   <tr><td>Ses prototipleri</td><td>${yes(at.voice_prototypes)}</td></tr>
   <tr><td>Görsel çapraz kontrol</td><td>✘ yok (uygulanmadı)</td></tr></table>`;
  if(ev.media)h+=`<div class="small mute" style="margin-top:8px">${(ev.media.notes||[]).map(esc).join(" ")}</div>`;
  if(ev.asr_runtime)h+=`<div class="small mute">ASR: ${esc(ev.asr_runtime.model)} · ${esc(ev.asr_runtime.device)} · ${esc(ev.asr_runtime.compute_type)}. ${esc(ev.asr_runtime.note)}</div>`;
  if(ev.suppressed_hallucinations!==undefined)h+=`<div class="small mute">Sessizlikte uydurulan ve atılan ifade sayısı: ${ev.suppressed_hallucinations}</div>`;
  if(ev.meet&&ev.meet.problems&&ev.meet.problems.length)h+=`<div class="small" style="margin-top:6px">`+ev.meet.problems.map(p=>`• ${esc(p)}`).join("<br>")+`</div>`;
  h+=`</div>`;
  v.innerHTML=h;
  v.querySelectorAll("[data-retry]").forEach(b=>b.onclick=()=>act(()=>api(`/jobs/${S.job}/retry/${b.dataset.retry}`,{body:{}})));
  v.querySelectorAll("[data-rec]").forEach(b=>b.onclick=()=>act(()=>api(`/jobs/${S.job}/choose-record`,{body:{record:b.dataset.rec}})));
  const st=$("#stop");if(st)st.onclick=()=>act(()=>api(`/jobs/${S.job}/stop`,{body:{}}));
  const rs=$("#resume");if(rs)rs.onclick=()=>act(()=>api(`/jobs/${S.job}/resume`,{body:{}}));
  $("#cleanup").onclick=()=>confirm("Kaynak kayıt ve geçici ses dosyası silinsin mi? Ses oynatma devre dışı kalır.")&&act(()=>api(`/jobs/${S.job}/cleanup`,{body:{}}));
}
async function act(fn){try{await fn();say("");poll()}catch(e){say(e.message,true)}}

/* ---------------- Speakers ---------------- */
async function vSpk(v){
  v.innerHTML=`<div class="card mute">Yükleniyor...</div>`;
  let d;try{d=await api(`/jobs/${S.job}/speakers`)}catch(e){v.innerHTML=`<div class="card err">${esc(e.message)}</div>`;return}
  const spk=d.speakers||{},cl=spk.clusters||{},dec=spk.decisions||{},as=spk.assignments||{};
  const people=(S.status&&S.status.people)||{};
  if(!Object.keys(cl).length){v.innerHTML=`<div class="card mute">Konuşmacı kümeleri henüz yok. Analiz tamamlanınca burada görünür.</div>`;return}
  let h=`<div class="card small mute">Her ses için örnekleri dinleyin ve kimin olduğunu seçin. Emin değilseniz boş bırakın; o ses "Unknown Speaker [to be checked]" olarak kalır. Meet verisi kimliği zaten belirlediyse bu adım isteğe bağlıdır.</div>`;
  for(const c of Object.keys(cl)){
    const D=dec[c]||{};
    const ev=(D.evidence||[]).map(e=>e.source+(e.person?`:${e.person}`:"")).join(", ");
    h+=`<div class="card"><h3>Ses ${esc(c)} · ${Math.round(cl[c].seconds||0)} sn</h3>
      <div class="row"><select data-c="${esc(c)}"><option value="">(belirsiz)</option>${Object.keys(people).map(k=>`<option value="${esc(k)}" ${as[c]===k?"selected":""}>${esc(people[k])}</option>`).join("")}</select>
      <span class="small mute">Şu an: ${esc(D.person||"belirsiz")} ${D.conflict?"· ÇELİŞKİ":""} ${D.confirmed?"· onaylı":""} · kanıt: ${esc(ev||"yok")}</span></div>`;
    for(const s of (d.samples[c]||[])){
      h+=`<div class="ctx"><div class="small mute">${fmt(s.start)}</div>${esc(s.text)}<br><audio controls preload="none" src="${clipUrl(s.start,s.end,0.3)}"></audio></div>`;
    }
    h+=`</div>`;
  }
  h+=`<div class="card"><div class="row"><button id="proto">Ses prototiplerini oluştur ve tüm kayda uygula</button><span class="small mute">En az iki kişi için onaylı örnek gerekir. İlk çalıştırmada model indirilir.</span></div></div>`;
  v.innerHTML=h;
  v.querySelectorAll("select[data-c]").forEach(s=>s.onchange=async()=>{
    try{await api(`/jobs/${S.job}/cluster`,{body:{cluster:s.dataset.c,person:s.value||null}});say("Kaydedildi.");vSpk(v)}catch(e){say(e.message,true)}});
  $("#proto").onclick=async()=>{say("Prototipler hesaplanıyor, bu biraz sürebilir...");try{await api(`/jobs/${S.job}/prototypes`,{body:{}});say("Tamamlandı.");vSpk(v)}catch(e){say(e.message,true)}};
}

/* ---------------- To Be Checked ---------------- */
async function vRev(v){
  let items;try{items=await api(`/jobs/${S.job}/review`)}catch(e){v.innerHTML=`<div class="card err">${esc(e.message)}</div>`;return}
  const people=(S.status&&S.status.people)||{};
  const open=items.filter(i=>i.status==="open");
  const showAll=v.dataset.all==="1";
  const list=(showAll?items:open).slice(0,100);
  let h=`<div class="row"><b>${open.length} açık / ${items.length} toplam</b><label class="small"><input type="checkbox" id="all" ${showAll?"checked":""}> çözülenleri de göster</label></div>`;
  if(!list.length)h+=`<div class="card mute">Gösterilecek madde yok.</div>`;
  for(const r of list){
    h+=`<div class="card" data-r="${r.id}"><div class="row"><b>${r.id}</b><span class="pill">${esc(r.status)}</span><span class="small mute">${fmt(r.start)} · ${esc(r.speaker)}</span></div>
     <div class="small" style="margin:6px 0">${esc(r.issue)}</div>
     <div class="ctx small"><span class="mute">Önceki:</span> ${esc(r.previous)}</div>
     <div class="unc"><span class="mute small">Şüpheli:</span> ${esc(r.uncertain)}</div>
     <div class="ctx small"><span class="mute">Sonraki:</span> ${esc(r.next)}</div>
     ${r.alternatives.length?`<div class="small">Alternatifler: `+r.alternatives.map(a=>`<button class="small alt" data-t="${esc(a)}">${esc(a)}</button>`).join(" ")+`</div>`:""}
     <audio controls preload="none" src="${clipUrl(r.start,r.end,3)}"></audio>
     <textarea placeholder="Düzeltilmiş metin">${esc(r.corrected_text||(r.uncertain==="[to be checked]"?"":r.uncertain))}</textarea>
     <div class="row"><select class="who"><option value="">(konuşmacıyı değiştirme)</option>${Object.keys(people).map(k=>`<option value="${esc(k)}">${esc(people[k])}</option>`).join("")}</select>
     <button class="primary res">Çözüldü</button><button class="skip">Atla</button></div></div>`;
  }
  v.innerHTML=h;
  $("#all").onchange=e=>{v.dataset.all=e.target.checked?"1":"0";vRev(v)};
  v.querySelectorAll(".card[data-r]").forEach(c=>{
    const id=c.dataset.r,ta=c.querySelector("textarea");
    c.querySelectorAll(".alt").forEach(b=>b.onclick=()=>ta.value=b.dataset.t);
    const send=async st=>{try{await api(`/jobs/${S.job}/review/${id}`,{body:{text:ta.value,speaker:c.querySelector(".who").value||undefined,status:st}});vRev(v)}catch(e){say(e.message,true)}};
    c.querySelector(".res").onclick=()=>send("resolved");
    c.querySelector(".skip").onclick=()=>send("skipped");
  });
}

/* ---------------- Transcript ---------------- */
const ICS=["Uncertain IC/OOC","IC","OOC","GM Narration"];
async function vTr(v){
  let segs;try{segs=await api(`/jobs/${S.job}/segments`)}catch(e){v.innerHTML=`<div class="card err">${esc(e.message)}</div>`;return}
  const people=(S.status&&S.status.people)||{};
  const page=+(v.dataset.p||0),size=150,q=(v.dataset.q||"").toLowerCase();
  const f=q?segs.filter(s=>s.text.toLowerCase().includes(q)):segs;
  const part=f.slice(page*size,page*size+size);
  let h=`<div class="row"><input type="text" id="q" placeholder="Ara" value="${esc(v.dataset.q||"")}"><span class="small mute">${f.length} parça</span>
    <button id="prev" ${page?"":"disabled"}>←</button><span class="small">${page+1}/${Math.max(1,Math.ceil(f.length/size))}</span><button id="next" ${(page+1)*size<f.length?"":"disabled"}>→</button></div>`;
  for(const s of part){
    h+=`<div class="seg ${s.review_open?"flag":""}" data-id="${s.id}">
      <div><select class="spk"><option value="">Unknown</option>${Object.keys(people).map(k=>`<option value="${esc(k)}" ${s.speaker===k?"selected":""}>${esc(people[k])}</option>`).join("")}</select>
      <select class="ic" style="margin-top:4px">${ICS.map(i=>`<option ${s.ic_ooc===i?"selected":""}>${i}</option>`).join("")}</select>
      <div class="small mute">${fmt(s.start)}${s.overlap?" · örtüşme":""}</div></div>
      <div><textarea>${esc(s.text)}</textarea><audio controls preload="none" src="${clipUrl(s.start,s.end,1)}"></audio></div></div>`;
  }
  v.innerHTML=h;
  $("#q").onchange=e=>{v.dataset.q=e.target.value;v.dataset.p=0;vTr(v)};
  $("#prev").onclick=()=>{v.dataset.p=page-1;vTr(v)};$("#next").onclick=()=>{v.dataset.p=page+1;vTr(v)};
  v.querySelectorAll(".seg").forEach(r=>{
    const id=r.dataset.id;
    const save=async body=>{try{await api(`/jobs/${S.job}/segment/${id}`,{body});say("Kaydedildi.")}catch(e){say(e.message,true)}};
    r.querySelector("textarea").onchange=e=>save({text:e.target.value});
    r.querySelector(".spk").onchange=e=>save({speaker:e.target.value||null});
    r.querySelector(".ic").onchange=e=>save({ic_ooc:e.target.value});
  });
}

/* ---------------- Export ---------------- */
function vExp(v){
  const L=(k,n,x="")=>`<tr><td><a href="/api/jobs/${S.job}/export/${k}?t=${TOKEN}${x}" download>${n}</a></td></tr>`;
  v.innerHTML=`<div class="card"><h3>Dışa aktar</h3><label class="small"><input type="checkbox" id="ic" checked> IC/OOC etiketlerini ekle</label>
  <table id="tbl"></table></div>`;
  const draw=()=>{const x=$("#ic").checked?"&ic=true":"";
    $("#tbl").innerHTML=L("md","ASOFAB_Full_Transcript.md",x)+L("csv","ASOFAB_To_Be_Checked.csv")+L("json","ASOFAB_Transcript.json")+L("srt","ASOFAB.srt")+L("chapter","ASOFAB_Chapter_Source.md")};
  $("#ic").onchange=draw;draw();
}

/* ---------------- Glossary ---------------- */
async function vGlo(v){
  let g;try{g=await api("/glossary")}catch(e){v.innerHTML=`<div class="card err">${esc(e.message)}</div>`;return}
  const q=(v.dataset.q||"").toLowerCase();
  const f=g.filter(e=>!q||e.canonical.toLowerCase().includes(q)||e.aliases.some(a=>a.toLowerCase().includes(q))).slice(0,300);
  v.innerHTML=`<div class="card"><h3>Ekle / güncelle</h3><div class="row">
    <input type="text" id="gc" placeholder="Tercih edilen yazım"><select id="gk">${["player","character","dragon","house","place","term"].map(c=>`<option>${c}</option>`).join("")}</select>
    <input type="text" id="ga" placeholder="Duyulduğu biçimler (virgülle)"><input type="text" id="gn" placeholder="Not"><button class="primary" id="gs">Kaydet</button></div>
    <div class="small mute">Takma ad olarak sıradan bir kelime yazarsanız metin değiştirilmez, yalnızca denetime işaretlenir.</div></div>
    <div class="row"><input type="text" id="gq" placeholder="Ara" value="${esc(v.dataset.q||"")}"><span class="small mute">${f.length} / ${g.length}</span></div>
    <div class="card"><table><tr><th>Yazım</th><th>Tür</th><th>Takma adlar</th><th>Not</th><th></th></tr>`+
    f.map(e=>`<tr><td>${esc(e.canonical)}</td><td>${esc(e.category)}</td><td>${esc(e.aliases.join(", "))}</td><td class="small">${esc(e.note)}</td><td><button data-d="${esc(e.canonical)}">Sil</button></td></tr>`).join("")+`</table></div>`;
  $("#gq").onchange=e=>{v.dataset.q=e.target.value;vGlo(v)};
  $("#gs").onclick=async()=>{const c=$("#gc").value.trim();if(!c)return;
    try{await api("/glossary",{body:{canonical:c,category:$("#gk").value,aliases:$("#ga").value.split(",").map(x=>x.trim()).filter(Boolean),note:$("#gn").value}});vGlo(v)}catch(e){say(e.message,true)}};
  v.querySelectorAll("[data-d]").forEach(b=>b.onclick=async()=>{if(confirm("Silinsin mi?")){await api("/glossary/"+encodeURIComponent(b.dataset.d),{method:"DELETE"});vGlo(v)}});
}

/* ---------------- Settings ---------------- */
function vSet(v){
  const st=S.status||{},se=st.settings||{},hw=st.hardware||{};
  v.innerHTML=`<div class="card"><h3>Donanım</h3><div>${esc(hw.device||"")} ${esc(hw.compute_type||"")} ${esc(hw.gpu_name||"")}</div><div class="small mute">${esc(hw.notes||"")}</div></div>
  <div class="card"><h3>Google kurulumu</h3><div class="small mute">Adımlar için SETUP_GOOGLE.md dosyasına bakın. İndirdiğiniz client_secret JSON metnini yapıştırın.</div>
    <textarea id="cs" placeholder='{"installed":{...}}'></textarea>
    <div class="row"><button id="csb">Save OAuth client</button><button id="so">Oturumu kapat</button><span class="small mute">İstemci: ${st.client_secret?"kayıtlı":"yok"} · Oturum: ${st.signed_in?"açık":"kapalı"}</span></div></div>
  <div class="card"><h3>Modeller ve işleme</h3>
    <div class="row"><input type="password" id="hf" placeholder="Hugging Face read token ${se.hf_token_set?"(kayıtlı, boş bırakırsanız korunur)":""}"></div>
    <div class="row" style="margin-top:8px"><label><input type="checkbox" id="dt" ${se.delete_temp_audio_after?"checked":""}> Bitince geçici sesi sil</label>
    <label><input type="checkbox" id="sm" ${se.allow_smaller_model?"checked":""}> Daha küçük (daha az doğru) modele izin ver</label></div>
    <div class="row" style="margin-top:8px"><label>Model <input type="text" id="am" value="${esc(se.asr_model||"large-v3")}" style="min-width:120px"></label>
    <label>Beklenen konuşmacı <input type="text" id="es" value="${se.expected_speakers??4}" style="min-width:60px;width:60px"></label>
    <label>Min <input type="text" id="mn" value="${se.min_speakers??2}" style="min-width:60px;width:60px"></label>
    <label>Max <input type="text" id="mx" value="${se.max_speakers??6}" style="min-width:60px;width:60px"></label></div>
    <div class="row" style="margin-top:10px"><button class="primary" id="sv">Kaydet</button></div></div>`;
  $("#csb").onclick=async()=>{try{await api("/google/client-secret",{body:{text:$("#cs").value}});say("İstemci kaydedildi.");await loadStatus();vSet(v)}catch(e){say(e.message,true)}};
  $("#so").onclick=async()=>{await api("/google/signout",{body:{}});await loadStatus();vSet(v)};
  $("#sv").onclick=async()=>{try{await api("/settings",{body:{hf_token:$("#hf").value,delete_temp_audio_after:$("#dt").checked,allow_smaller_model:$("#sm").checked,
      asr_model:$("#am").value.trim()||"large-v3",expected_speakers:+$("#es").value||4,min_speakers:+$("#mn").value||2,max_speakers:+$("#mx").value||6}});say("Ayarlar kaydedildi.");await loadStatus()}catch(e){say(e.message,true)}};
}

drawTabs();
loadStatus().then(()=>{loadJobs();render()});
</script>
</body>
</html>
