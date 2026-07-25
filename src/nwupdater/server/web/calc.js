"use strict";
/* Self-contained NumWorks vector renderer (graphing + scientific), pure SVG.
   The six graphing app icons are faithful vector redraws of the real Epsilon home
   screen; the scientific screen keeps its monochrome line-art. Exposes a single
   global: buildCalc(variant) or buildCalc({variant, finish, textless, uid}).

   Hidden flags (not surfaced in the UI): screens ship textless so the same render
   serves the bilingual FR/EN interface — only language-neutral illustrations and
   math symbols remain (+ − × =, f(x), x=). Flip DEFAULT_TEXTLESS to false to bring
   back the localized on-screen text (real-device view). DEFAULT_FINISH is the
   validated "realistic" look; "flat" and "premium" remain available in code. */
(function (root) {
  var DEFAULT_TEXTLESS = true, DEFAULT_FINISH = "realistic";
  var ORANGE = "#f0a94c", PY_Y = "#f2c033", INK = "#2c2f35";
  var f1 = function (n) { return (+n).toFixed(1); };
  function esc(s){ return String(s==null?"":s).replace(/[&<>]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;"}[c];}); }
  function rr(x, y, w, h, r, fill, stroke, sw) {
    return '<rect x="'+f1(x)+'" y="'+f1(y)+'" width="'+f1(w)+'" height="'+f1(h)+'" rx="'+f1(r)+'" fill="'+fill+'"'+(stroke?' stroke="'+stroke+'" stroke-width="'+(sw||0.8)+'"':"")+'/>'; }
  function ci(cx, cy, r, fill, stroke, sw){ return '<circle cx="'+f1(cx)+'" cy="'+f1(cy)+'" r="'+f1(r)+'" fill="'+fill+'"'+(stroke?' stroke="'+stroke+'" stroke-width="'+(sw||0.8)+'"':"")+'/>'; }
  function P(d, attrs){ return '<path d="'+d+'" '+attrs+'/>'; }
  function txt(x, y, t, fs, fill, opt){ opt = opt||{}; return '<text x="'+f1(x)+'" y="'+f1(y)+'" '+(opt.anchor?'text-anchor="'+opt.anchor+'" ':'')+'font-family="'+(opt.mono?'var(--mono)':'var(--sans)')+'"'+(opt.weight?' font-weight="'+opt.weight+'"':'')+(opt.ls?' letter-spacing="'+opt.ls+'"':'')+' font-size="'+f1(fs)+'" fill="'+fill+'">'+esc(t)+'</text>'; }

  /* ---------- app icons (square [x,x+s]×[y,y+s]) ---------- */
  function tile(x, y, s, fill, stroke){ return rr(x, y, s, s, s*0.19, fill, stroke, 1); }
  function calcIcon(x, y, s){
    var o = tile(x, y, s, "#f6f7f9", "#e4e6ea");
    var p=s*0.15, g=s-2*p, gx=x+p, gy=y+p, mx=gx+g/2, my=gy+g/2, r=s*0.19;
    o += P('M'+f1(mx)+' '+f1(my)+' H'+f1(gx+g)+' V'+f1(gy+g-r)+' Q'+f1(gx+g)+' '+f1(gy+g)+' '+f1(gx+g-r)+' '+f1(gy+g)+' H'+f1(mx)+' Z','fill="'+ORANGE+'"');
    o += '<line x1="'+f1(mx)+'" y1="'+f1(gy)+'" x2="'+f1(mx)+'" y2="'+f1(gy+g)+'" stroke="#d3d6db" stroke-width="'+(s*0.02)+'"/>';
    o += '<line x1="'+f1(gx)+'" y1="'+f1(my)+'" x2="'+f1(gx+g)+'" y2="'+f1(my)+'" stroke="#d3d6db" stroke-width="'+(s*0.02)+'"/>';
    function gl(cx,cy,t,col){ return txt(cx, cy+s*0.07, t, s*0.2, col, {anchor:"middle",weight:700}); }
    o += gl(gx+g*0.25, gy+g*0.25, "+", INK) + gl(gx+g*0.75, gy+g*0.25, "−", INK);
    o += gl(gx+g*0.25, gy+g*0.75, "×", INK) + gl(gx+g*0.75, gy+g*0.75, "=", "#fff");
    return o;
  }
  function graphIcon(x, y, s, uid){
    var o = tile(x, y, s, "#f6f7f9", "#e4e6ea");
    var p=s*0.2, ox=x+p, oy=y+s-p, top=y+p*0.8, right=x+s-p*0.72, w=right-ox, h=oy-top;
    o += '<line x1="'+f1(ox)+'" y1="'+f1(top)+'" x2="'+f1(ox)+'" y2="'+f1(oy)+'" stroke="#c7cad0" stroke-width="'+(s*0.03)+'" stroke-linecap="round"/>';
    o += '<line x1="'+f1(ox)+'" y1="'+f1(oy)+'" x2="'+f1(right)+'" y2="'+f1(oy)+'" stroke="#c7cad0" stroke-width="'+(s*0.03)+'" stroke-linecap="round"/>';
    var curve='M'+f1(ox)+' '+f1(oy)+' C '+f1(ox+w*0.06)+' '+f1(oy-h*0.62)+' '+f1(ox+w*0.34)+' '+f1(top+h*0.02)+' '+f1(right)+' '+f1(top+h*0.04);
    o += P(curve+' L '+f1(right)+' '+f1(oy)+' Z','fill="url(#gf'+uid+')"');
    o += P(curve,'fill="none" stroke="'+ORANGE+'" stroke-width="'+(s*0.05)+'" stroke-linecap="round" stroke-linejoin="round"');
    return o;
  }
  function pythonIcon(x, y, s){
    var o = tile(x, y, s, "#f6f7f9", "#e4e6ea");
    var k=s*0.62/17, tx=x+s*0.19, ty=y+s*0.17;
    var blue="M8.51.146c-.71.003-1.39.064-1.988.17-1.76.31-2.08.96-2.08 2.16v1.58h4.16v.53H2.876c-1.21 0-2.27.727-2.6 2.11-.382 1.583-.4 2.57 0 4.223.294 1.233 1 2.11 2.21 2.11h1.43v-1.894c0-1.373 1.19-2.586 2.6-2.586h4.155c1.157 0 2.08-.952 2.08-2.114V2.476c0-1.128-.95-1.974-2.08-2.16-.714-.117-1.455-.173-2.17-.17zM6.26 1.42c.43 0 .78.355.78.79 0 .434-.35.786-.78.786-.432 0-.78-.352-.78-.786 0-.435.348-.79.78-.79z";
    var yell="M13.09 4.94v1.84c0 1.43-1.213 2.634-2.6 2.634H6.335c-1.138 0-2.08.974-2.08 2.114v3.96c0 1.128.98 1.79 2.08 2.113 1.317.387 2.58.456 4.155 0 1.05-.303 2.08-.916 2.08-2.113v-1.58H8.415v-.53h6.235c1.21 0 1.66-.844 2.08-2.11.434-1.304.416-2.558 0-4.223-.3-1.196-.87-2.11-2.08-2.11h-1.56zm-2.336 10.03c.43 0 .78.353.78.787 0 .436-.35.79-.78.79-.43 0-.78-.354-.78-.79 0-.434.35-.787.78-.787z";
    o += '<g transform="translate('+f1(tx)+' '+f1(ty)+') scale('+k.toFixed(4)+')">'+P(blue,'fill="#4b4e57"')+P(yell,'fill="'+PY_Y+'"')+'</g>';
    return o;
  }
  function statsIcon(x, y, s){
    var o = tile(x, y, s, "#494d55", "#3a3d43");
    var base=y+s*0.74, bw=s*0.16, gap=s*0.07, total=3*bw+2*gap, x0=x+(s-total)/2, hs=[0.34,0.5,0.24];
    for (var i=0;i<3;i++){ var bx=x0+i*(bw+gap), bh=s*hs[i], by=base-bh, d=s*0.05;
      o += P('M'+f1(bx)+' '+f1(by)+' L'+f1(bx+d)+' '+f1(by-d)+' L'+f1(bx+bw+d)+' '+f1(by-d)+' L'+f1(bx+bw)+' '+f1(by)+' Z','fill="#d7dade"');
      o += P('M'+f1(bx+bw)+' '+f1(by)+' L'+f1(bx+bw+d)+' '+f1(by-d)+' L'+f1(bx+bw+d)+' '+f1(base-d)+' L'+f1(bx+bw)+' '+f1(base)+' Z','fill="#b9bdc4"');
      o += rr(bx, by, bw, base-by, s*0.012, "#f1f2f4"); }
    return o;
  }
  function probaIcon(x, y, s, uid){
    var o = tile(x, y, s, "#494d55", "#3a3d43");
    var base=y+s*0.72, L=x+s*0.14, R=x+s*0.86, peak=y+s*0.24, mid=x+s*0.5;
    var bell='M'+f1(L)+' '+f1(base)+' C '+f1(mid-s*0.16)+' '+f1(base)+' '+f1(mid-s*0.16)+' '+f1(peak)+' '+f1(mid)+' '+f1(peak)+' C '+f1(mid+s*0.16)+' '+f1(peak)+' '+f1(mid+s*0.16)+' '+f1(base)+' '+f1(R)+' '+f1(base);
    o += P(bell+' Z','fill="url(#pf'+uid+')"');
    o += P(bell,'fill="none" stroke="'+ORANGE+'" stroke-width="'+(s*0.045)+'" stroke-linecap="round"');
    o += '<line x1="'+f1(x+s*0.1)+'" y1="'+f1(base)+'" x2="'+f1(x+s*0.9)+'" y2="'+f1(base)+'" stroke="#6d7178" stroke-width="'+(s*0.02)+'"/>';
    return o;
  }
  function eqIcon(x, y, s){
    var o = tile(x, y, s, "#494d55", "#3a3d43");
    var cx=x+s*0.44, cy=y+s*0.42, r=s*0.24;
    o += ci(cx, cy, r, "none", PY_Y, s*0.055);
    o += '<line x1="'+f1(cx+r*0.72)+'" y1="'+f1(cy+r*0.72)+'" x2="'+f1(x+s*0.82)+'" y2="'+f1(y+s*0.8)+'" stroke="'+PY_Y+'" stroke-width="'+(s*0.09)+'" stroke-linecap="round"/>';
    o += txt(cx, cy+s*0.085, "x=", s*0.24, PY_Y, {anchor:"middle",weight:700});
    return o;
  }
  var APPS = [
    {name:"Calculs", draw:calcIcon, sel:true}, {name:"Grapheur", draw:graphIcon}, {name:"Python", draw:pythonIcon},
    {name:"Statistiques", draw:statsIcon}, {name:"Probabilités", draw:probaIcon}, {name:"Equations", draw:eqIcon}
  ];

  /* ---------- palettes & finishes ---------- */
  var PAL = {
    graphing:{ body:"#eceef1", body2:"#e2e4e8", edge:"#d3d5d9", key:"#ffffff", key2:"#f3f4f6", keyEdge:"#e0e2e6",
               text:"#24262c", sec:ORANGE, letter:"#a7aab0", word:"#83868c", okKey:"#ffffff", okText:"#24262c" },
    scientific:{ body:"#3b3e44", body2:"#34373c", edge:"#2a2c30", key:"#4a4e55", key2:"#43474e", keyEdge:"#34373c",
               text:"#f1f1ef", sec:"#efa73c", letter:"#8c9099", word:"#c9cbcf", okKey:"#4a4e55", okText:"#f1f1ef" }
  };
  var HOME = "#f5a623", POWER = "#2b2d31";

  function screenGraphing(push, x, y, w, h, uid, finish, textless){
    var bez = finish==="flat" ? 3 : 5;
    push(rr(x-bez, y-bez, w+2*bez, h+2*bez, 8, "#d9dbdf", "#cfd1d5", 0.8));
    push(rr(x, y, w, h, 3, "#ffffff", "#ffffff"));
    var tb=13;
    push('<clipPath id="sc'+uid+'"><rect x="'+f1(x)+'" y="'+f1(y)+'" width="'+f1(w)+'" height="'+f1(h)+'" rx="3"/></clipPath>');
    push('<g clip-path="url(#sc'+uid+')">');
    push('<rect x="'+f1(x)+'" y="'+f1(y)+'" width="'+f1(w)+'" height="'+tb+'" fill="'+ORANGE+'"/>');
    if (!textless){
      push(txt(x+5, y+9, "rad", 6.4, "#fff", {mono:true}));
      push(txt(x+w/2, y+9, "APPLICATIONS", 6.4, "#fff", {anchor:"middle",weight:700,ls:0.6}));
    }
    push(rr(x+w-14, y+3.6, 9, 5.4, 1, "#fff"));
    push('<rect x="'+f1(x+w-4.4)+'" y="'+f1(y+5.2)+'" width="1.3" height="2.2" fill="#fff"/>');
    // 3×2 grid — icon size from vertical fit; labels drop out (and icons enlarge) when textless
    var topPad=8, botPad=textless?8:7, labelH=textless?0:11, rowGap=textless?13:7, ipad=9;
    var gridH=h-tb-topPad-botPad, s=(gridH-2*labelH-rowGap)/2;
    var maxS=(w-2*ipad-2*8)/3; if (s>maxS) s=maxS;
    var gridTotalH=2*s+2*labelH+rowGap, gtop=y+tb+topPad+(gridH-gridTotalH)/2;
    var gapx=(w-2*ipad-3*s)/2;
    for (var kk=0; kk<APPS.length; kk++){
      var a=APPS[kk], c=kk%3, r=(kk/3|0);
      var ix=x+ipad+c*(s+gapx), iy=gtop+r*(s+labelH+rowGap);
      push(a.draw(ix, iy, s, uid));
      if (!textless){
        var lx=ix+s/2, ly=iy+s+8.6;
        if (a.sel){ var pw=s*0.92; push(rr(lx-pw/2, ly-8.2, pw, 10.6, 3, ORANGE)); push(txt(lx, ly, a.name, 6, "#3a2a08", {anchor:"middle",weight:600})); }
        else push(txt(lx, ly, a.name, 6, "#33353a", {anchor:"middle"}));
      }
    }
    // scrollbar hint
    push(rr(x+w-3, gtop, 1.4, gridTotalH, 0.7, "#e6e8eb"));
    push(rr(x+w-3, gtop, 1.4, gridTotalH*0.5, 0.7, "#c2c5ca"));
    push('</g>');
    return y+h;
  }

  function screenScientific(push, x, y, w, h, uid, finish, textless){
    var S="#c9d3c8", INKS="#28331f";
    push(rr(x-4, y-4, w+8, h+8, 7, "#0c0f0b", "#0c0f0b"));
    push(rr(x, y, w, h, 2, S, S));
    if (!textless){
      push(txt(x+5, y+13, "Calculs", 8.5, INKS, {mono:true}));
      push(txt(x+w-26, y+13, "deg", 7, INKS, {mono:true}));
    }
    push('<rect x="'+f1(x+w-13)+'" y="'+f1(y+7.5)+'" width="9" height="6" rx="1" fill="none" stroke="'+INKS+'" stroke-width="0.8"/><rect x="'+f1(x+w-11)+'" y="'+f1(y+9)+'" width="4.5" height="3" fill="'+INKS+'"/>');
    var n=4,m=6,gap=5,iw=(w-2*m-(n-1)*gap)/n;
    var ih=Math.min(iw, textless?h-22:h-26), iy=textless?(y+(h-ih)/2-2):(y+17);
    for (var i=0;i<n;i++){ var ix=x+m+i*(iw+gap), cx=ix+iw/2, cy=iy+ih/2;
      push('<rect x="'+f1(ix)+'" y="'+f1(iy)+'" width="'+f1(iw)+'" height="'+f1(ih)+'" fill="none" stroke="'+INKS+'" stroke-width="1"/>');
      if (i===0){ push('<line x1="'+f1(ix)+'" y1="'+f1(cy)+'" x2="'+f1(ix+iw)+'" y2="'+f1(cy)+'" stroke="'+INKS+'" stroke-width="0.8"/><line x1="'+f1(cx)+'" y1="'+f1(iy)+'" x2="'+f1(cx)+'" y2="'+f1(iy+ih)+'" stroke="'+INKS+'" stroke-width="0.8"/>');
        push(txt(ix+iw*0.27, iy+iw*0.34, "+", 6, INKS, {anchor:"middle"})+txt(ix+iw*0.74, iy+iw*0.34, "−", 6, INKS, {anchor:"middle"})+txt(ix+iw*0.27, iy+iw*0.82, "×", 6, INKS, {anchor:"middle"})+txt(ix+iw*0.74, iy+iw*0.82, "=", 6, INKS, {anchor:"middle"}));
      } else if (i===1){ var fx=[0.28,0.5,0.72], bhs=[0.4,0.7,0.55]; for (var bi=0;bi<3;bi++){ var bh=bhs[bi]*ih; push('<rect x="'+f1(ix+iw*fx[bi]-2)+'" y="'+f1(iy+ih-bh-2)+'" width="4" height="'+f1(bh)+'" fill="'+INKS+'"/>'); }
      } else if (i===2){ push('<line x1="'+f1(ix)+'" y1="'+f1(cy)+'" x2="'+f1(ix+iw)+'" y2="'+f1(cy)+'" stroke="'+INKS+'" stroke-width="0.7"/><line x1="'+f1(cx)+'" y1="'+f1(iy)+'" x2="'+f1(cx)+'" y2="'+f1(iy+ih)+'" stroke="'+INKS+'" stroke-width="0.7"/>');
        push('<rect x="'+f1(cx)+'" y="'+f1(iy)+'" width="'+f1(iw/2)+'" height="'+f1(ih/2)+'" fill="'+INKS+'" opacity="0.55"/>'); push(txt(cx, iy+ih-3, "f(x)", 5.2, INKS, {anchor:"middle"}));
      } else { push('<circle cx="'+f1(cx-1)+'" cy="'+f1(cy-1)+'" r="'+f1(iw*0.3)+'" fill="none" stroke="'+INKS+'" stroke-width="1"/><line x1="'+f1(cx+iw*0.15)+'" y1="'+f1(cy+iw*0.15)+'" x2="'+f1(ix+iw-2)+'" y2="'+f1(iy+ih-2)+'" stroke="'+INKS+'" stroke-width="1.2"/>'); push(txt(cx-1, cy+1, "x=", 5, INKS, {anchor:"middle"})); }
    }
    push('<line x1="'+f1(x+w*0.3)+'" y1="'+f1(y+h-9)+'" x2="'+f1(x+w*0.7)+'" y2="'+f1(y+h-9)+'" stroke="'+INKS+'" stroke-width="1.4"/>');
    return y+h;
  }

  var rowsG = [
    [["shift",null,null,"o"],["alpha","ALPHA",null],["x,n,t","cut",null],["var","copy",null],["▤","paste",null],["⌫","clear",null]],
    [["eˣ",null,"A"],["ln",null,"B"],["log",null,"C"],["i",null,"D"],[",",null,"E"],["xʸ",null,"F"]],
    [["sin","asin","G"],["cos","acos","H"],["tan","atan","I"],["π","=","J"],["√",null,"K"],["x²",null,"L"]],
    [["7",null,"M"],["8",null,"N"],["9",null,"O"],["(",null,"P"],[")",null,"Q"]],
    [["4",null,"R"],["5",null,"S"],["6",null,"T"],["×",null,"U"],["÷",null,"V"]],
    [["1",null,"W"],["2",null,"X"],["3",null,"Y"],["+",null,"Z"],["−",null,"⌐"]],
    [["0",null,null],[".",null,null],["×10ˣ",null,null],["Ans",null,null],["EXE",null,null]]
  ];
  var rowsS = [
    [["shift",null,null,"o"],["x,y,z","eˣ",null],["ln",null,null],["log",null,null],["var",null,null],["⌫","clear",null]],
    [["sin","asin",null],["cos","acos",null],["tan","atan",null],["π","=",null],["√",null,null],["x²",null,null]],
    [["7"],["8"],["9"],["("],[")"]], [["4"],["5"],["6"],["×"],["÷"]],
    [["1"],["2"],["3"],["+"],["−"]], [["0"],["."],["×10ˣ"],["Ans"],["EXE"]]
  ];

  /* ---------- compact family glyph (mode:"icon") — roster cell, ~28px ---------- */
  function buildIcon(variant){
    var g = variant !== "scientific";
    var body = g ? "#eceef1" : "#3b3e44", edge = g ? "#d3d5d9" : "#2a2c30";
    var scr = g ? "#ffffff" : "#c9d3c8", keyc = g ? "#cfd2d7" : "#565a62";
    var a = [];
    a.push('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 44 44" role="img" aria-label="NumWorks '+(g?"graphique":"scientifique")+'">');
    a.push(rr(3, 2, 38, 40, 9, body, edge, 1));
    a.push(rr(7, 6, 30, g?11:14, 2.5, scr, g?"#e2e4e8":"#0c0f0b", g?0.6:1));
    if (g) a.push('<rect x="7" y="6" width="30" height="3.4" rx="1.6" fill="'+ORANGE+'"/>'); // orange status bar
    // key dots: 3 rows × 4, with the home key in orange
    var ky = g ? 23 : 25;
    for (var r=0; r<3; r++) for (var c=0; c<4; c++){
      var home = (r===0 && c===1);
      a.push('<circle cx="'+(11+c*7.3)+'" cy="'+(ky+r*6)+'" r="1.7" fill="'+(home?HOME:keyc)+'"/>');
    }
    a.push('</svg>');
    return a.join("");
  }

  /* ---------- screen-only thumbnail (mode:"thumb"), ~ device screen + bezel ---------- */
  function buildThumb(variant, finish, textless, uid){
    var g = variant !== "scientific", sw = 192, sh = g ? 158 : 80, pad = 9;
    var W = sw + 2*pad, H = sh + 2*pad, a = [], push = function(s){ a.push(s); };
    push('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+W+' '+H+'" role="img" aria-label="NumWorks '+(g?"graphique":"scientifique")+' — écran">');
    push('<defs><linearGradient id="gf'+uid+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="'+ORANGE+'" stop-opacity="0.55"/><stop offset="1" stop-color="'+ORANGE+'" stop-opacity="0.06"/></linearGradient>'+
      '<linearGradient id="pf'+uid+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="'+ORANGE+'" stop-opacity="0.95"/><stop offset="1" stop-color="'+ORANGE+'" stop-opacity="0.32"/></linearGradient></defs>');
    if (g) screenGraphing(push, pad, pad, sw, sh, uid, finish, textless);
    else screenScientific(push, pad, pad, sw, sh, uid, finish, textless);
    push('</svg>');
    return a.join("");
  }

  function buildCalc(input){
    var opts = typeof input === "string" ? { variant: input } : (input || {});
    var variant = opts.variant||"graphing", finish = opts.finish||DEFAULT_FINISH, uid = opts.uid||variant;
    opts.textless = opts.textless !== undefined ? opts.textless : DEFAULT_TEXTLESS;
    var mode = opts.mode || "device";
    if (mode === "icon") return buildIcon(variant);
    if (mode === "thumb") return buildThumb(variant, finish, opts.textless, uid);
    var p = PAL[variant]||PAL.graphing, W=232, pad=8;
    var H = variant==="graphing" ? 466 : 372;
    var A=[]; var push=function(s){ A.push(s); };
    push('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+W+' '+H+'" role="img" aria-label="NumWorks '+variant+'">');
    // defs: gradients + shadow filter
    var shadow = finish==="flat" ? "" :
      '<filter id="ks'+uid+'" x="-40%" y="-40%" width="180%" height="200%"><feDropShadow dx="0" dy="'+(finish==="premium"?1.1:0.8)+'" stdDeviation="'+(finish==="premium"?1.1:0.8)+'" flood-color="#000" flood-opacity="'+(finish==="premium"?0.22:0.16)+'"/></filter>'+
      '<filter id="bs'+uid+'" x="-15%" y="-15%" width="130%" height="130%"><feDropShadow dx="0" dy="2.5" stdDeviation="3.5" flood-color="#000" flood-opacity="0.18"/></filter>';
    push('<defs>'+
      '<linearGradient id="bg'+uid+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="'+p.body+'"/><stop offset="1" stop-color="'+p.body2+'"/></linearGradient>'+
      '<linearGradient id="kg'+uid+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="'+p.key+'"/><stop offset="1" stop-color="'+p.key2+'"/></linearGradient>'+
      '<linearGradient id="gf'+uid+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="'+ORANGE+'" stop-opacity="0.55"/><stop offset="1" stop-color="'+ORANGE+'" stop-opacity="0.06"/></linearGradient>'+
      '<linearGradient id="pf'+uid+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="'+ORANGE+'" stop-opacity="0.95"/><stop offset="1" stop-color="'+ORANGE+'" stop-opacity="0.32"/></linearGradient>'+
      '<linearGradient id="gl'+uid+'" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff" stop-opacity="'+(variant==="scientific"?0.1:0.5)+'"/><stop offset="1" stop-color="#ffffff" stop-opacity="0"/></linearGradient>'+
      shadow+'</defs>');
    // body
    var kfill = finish==="flat" ? p.key : 'url(#kg'+uid+')';
    var bodyFill = finish==="flat" ? p.body : 'url(#bg'+uid+')';
    push('<g '+(finish==="flat"?"":'filter="url(#bs'+uid+')"')+'>'+rr(pad, pad, W-2*pad, H-2*pad, 26, bodyFill, p.edge, 0.8)+'</g>');
    if (finish==="premium"){ // glossy top highlight sweep
      push('<clipPath id="bc'+uid+'"><rect x="'+pad+'" y="'+pad+'" width="'+(W-2*pad)+'" height="'+(H-2*pad)+'" rx="26"/></clipPath>');
      push('<rect x="'+pad+'" y="'+pad+'" width="'+(W-2*pad)+'" height="'+((H-2*pad)*0.5)+'" clip-path="url(#bc'+uid+')" fill="url(#gl'+uid+')"/>');
    }
    push(txt(W/2, 25, "NUMWORKS", 8.5, p.word, {anchor:"middle",weight:700,ls:1.6}));

    var sx=20, sy=33, sw=W-40, sh = variant==="graphing" ? 158 : Math.round(sw/2.4);
    var scrBottom = variant==="graphing" ? screenGraphing(push, sx, sy, sw, sh, uid, finish, opts.textless)
                                         : screenScientific(push, sx, sy, sw, sh, uid, finish, opts.textless);

    // nav cluster
    var navY = scrBottom + 40, dx = 48, arw = 15;
    function keyShadow(){ return finish==="flat" ? "" : ' filter="url(#ks'+uid+')"'; }
    function arrow(cx,cy,g){ push('<g'+keyShadow()+'>'+rr(cx-arw/2, cy-arw/2, arw, arw, 4.8, kfill, p.keyEdge, 0.8)+'</g>'+txt(cx, cy+3, g, 8, p.text, {anchor:"middle"})); }
    arrow(dx, navY-18, "▵"); arrow(dx, navY+18, "▿"); arrow(dx-18, navY, "◁"); arrow(dx+18, navY, "▹");
    push('<g'+keyShadow()+'>'+rr(96, navY-27, 42, 22, 11, HOME, HOME, 0)+'</g>'+txt(117, navY-16, "⌂", 9, "#5a3d05", {anchor:"middle"}));
    push('<g'+keyShadow()+'>'+ci(117, navY+13, 12, POWER, POWER, 0)+'</g>'+txt(117, navY+13, "⏻", 8.5, "#d7d8da", {anchor:"middle"}));
    push('<g'+keyShadow()+'>'+ci(170, navY, 14, kfill, p.keyEdge, 0.8)+'</g>'+txt(170, navY, "OK", 7.5, p.okText, {anchor:"middle"}));
    push('<g'+keyShadow()+'>'+ci(201, navY, 14, kfill, p.keyEdge, 0.8)+'</g>'+txt(201, navY, "↩", 9, p.okText, {anchor:"middle"}));

    // keyboard
    var rows = variant==="graphing" ? rowsG : rowsS;
    var gx0=15, gW=W-30, gapx=4.6, gapy=5.2, rh=22.5, ry=navY+30;
    rows.forEach(function(row){
      var n=row.length, kw=(gW-(n-1)*gapx)/n;
      row.forEach(function(k,i){
        var main=k[0], sec=k[1], letter=k[2], special=k[3], x=gx0+i*(kw+gapx);
        var kf=kfill, kt=p.text, rad=Math.min(kw,rh)*0.5;
        push('<g'+keyShadow()+'>'+rr(x, ry, kw, rh, rad, kf, p.keyEdge, 0.8)+'</g>');
        var mainColor = special==="o" ? p.sec : kt;
        var fs = main.length>3 ? 6.3 : 8.4;
        push(txt(x+kw/2, ry+rh/2+2.7, main, fs, mainColor, {anchor:"middle"}));
        if (sec) push(txt(x+3.6, ry+5.8, sec, 4.6, p.sec));
        if (letter) push(txt(x+kw-3.6, ry+5.8, letter, 4.6, p.letter, {anchor:"end"}));
      });
      ry += rh+gapy;
    });
    push('</svg>');
    return A.join("");
  }

  root.buildCalc = buildCalc;
})(typeof globalThis !== "undefined" ? globalThis : this);
