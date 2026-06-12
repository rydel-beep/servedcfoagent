/* EDITH HUD engine — VERBATIM from edith-hud-reference.html, plus the
   integration bridge (event wiring + Shift+S focus). The engine's logic,
   timings, particle counts, and ticker lines are the reference's. The demo
   #eh-controls and the demo's hardcoded caption line are preview tooling and
   are not integrated — the caption types the REAL spoken reply text. */
(function(){
  var root=document.getElementById('edith-hud');
  if(!root)return;
  var tick=document.getElementById('eh-tick'),
      cap=document.getElementById('eh-cap'),
      wave=document.getElementById('eh-wave'),
      pl=document.getElementById('eh-pl'),
      cv=document.getElementById('eh-shards'),
      cx=cv.getContext('2d');

  for(var i=0;i<16;i++){wave.appendChild(document.createElement('i'));}
  var bars=wave.children, state='idle', parts=[],
      lines=['ROUTING QUERY','ANALYSING ENGINES','QUERYING FORWARD MRR','COMPOSING RESPONSE','VOCALISING'],
      li=0, glyphs='01·-+/«»<>:'.split(''), W,H;

  function size(){W=cv.width=root.clientWidth;H=cv.height=root.clientHeight;}
  size(); window.addEventListener('resize',size);

  function setTick(t,cursor){tick.innerHTML=t+(cursor?'<span class="eh-cur">▌</span>':'');}

  setInterval(function(){
    if(state==='thinking'){li=(li+1)%lines.length;setTick(lines[li],true);}
  },1400);

  setInterval(function(){
    if(state==='listening'){
      var p=document.createElement('div');p.className='eh-pulse';
      pl.appendChild(p);setTimeout(function(){p.remove();},1500);
    }
  },700);

  function spawn(n){
    for(var i=0;i<n;i++){
      parts.push({x:W/2+(Math.random()-0.5)*260, y:H/2+100+Math.random()*30,
                  vy:0.5+Math.random()*1.1, a:0.85,
                  c:glyphs[(Math.random()*glyphs.length)|0], s:9+Math.random()*4});
    }
  }

  function loop(){
    cx.clearRect(0,0,W,H);
    if(state==='thinking'&&parts.length<48)spawn(2);
    cx.textAlign='center';
    for(var i=parts.length-1;i>=0;i--){
      var p=parts[i]; p.y-=p.vy; p.a-=0.009;
      if(p.a<=0){parts.splice(i,1);continue;}
      cx.globalAlpha=p.a; cx.fillStyle='#7A9ABF';
      cx.font=p.s+'px monospace'; cx.fillText(p.c,p.x,p.y);
    }
    cx.globalAlpha=1;
    for(var j=0;j<bars.length;j++){
      bars[j].style.height=(state==='speaking'?4+Math.random()*24:4)+'px';
    }
    requestAnimationFrame(loop);
  }
  loop();

  var capLine='';   // the REAL reply text (set by the bridge) — never a fake specific
  window.EDITH_HUD={
    setState:function(s){
      state=s; root.setAttribute('data-state',s);
      parts.length=0; cap.textContent='';
      if(s==='idle')setTick('EDITH — STANDBY',false);
      if(s==='listening')setTick('LISTENING',true);
      if(s==='thinking'){li=0;setTick(lines[0],true);}
      if(s==='speaking'){
        setTick('EDITH',false); var k=0; var line=capLine;
        var tw=setInterval(function(){
          if(state!=='speaking'||k>=line.length){clearInterval(tw);return;}
          cap.textContent+=line[k++];
        },28);
      }
    },
    getState:function(){return state;},
    setCaption:function(text){capLine=(text||'').slice(0,220);},
  };

  /* ===== integration bridge: drive setState from the live state machine ===== */
  var MAP={idle:'idle',listening:'listening',thinking:'thinking',speaking:'speaking',
           booting:'thinking',greeting:'speaking'};
  window.addEventListener('edith:state',function(e){
    var s=MAP[e.detail.to];
    if(s)window.EDITH_HUD.setState(s);
  });
  // typed chat drives it too (text replies have no audio: back to idle on reply)
  window.addEventListener('edith:chat',function(e){
    if(e.detail.phase==='sent'&&(state==='idle'))window.EDITH_HUD.setState('thinking');
    if(e.detail.phase==='reply'&&state==='thinking')window.EDITH_HUD.setState('idle');
    if(e.detail.phase==='error'&&state==='thinking')window.EDITH_HUD.setState('idle');
  });
  // TTS lifecycle: real reply text becomes the typed caption
  window.addEventListener('edith:tts',function(e){
    if(e.detail.phase==='synth'&&e.detail.text)window.EDITH_HUD.setCaption(e.detail.text);
  });

  // Focus mode: Shift+S hides overlay layers (brackets/radar/scanline/shards)
  function applyFocus(){
    var on=false;
    try{on=localStorage.getItem('edith-hud-focus')==='1';}catch(err){}
    root.classList.toggle('focus',on);
  }
  applyFocus();
  document.addEventListener('keydown',function(e){
    var tag=(document.activeElement||{}).tagName;
    if(tag==='INPUT'||tag==='TEXTAREA')return;
    if(e.key==='S'&&e.shiftKey&&!e.metaKey&&!e.ctrlKey){
      try{
        var cur=localStorage.getItem('edith-hud-focus')==='1';
        localStorage.setItem('edith-hud-focus',cur?'0':'1');
      }catch(err){}
      applyFocus();
    }
  });

  window.EDITH_HUD.setState('idle');
})();
