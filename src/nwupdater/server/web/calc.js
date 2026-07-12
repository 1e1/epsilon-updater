"use strict";
// Faithful SVG rendering of the two NumWorks families (from the real key matrix keys.inc).
// Screen labels mirror the device's own home screen and are intentionally not localized.

const _esc = (s) => String(s ?? "").replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const PAL = {
  graphing: { body:"#e9eaec", edge:"#d0d2d6", key:"#f7f8fa", keyEdge:"#dbdde1",
              text:"#22242a", sec:"#e8930c", word:"#7c7f85", okKey:"#f7f8fa", okText:"#22242a" },
  scientific:{ body:"#3b3e44", edge:"#2a2c30", key:"#484c53", keyEdge:"#33363b",
              text:"#f1f1ef", sec:"#efa73c", word:"#c9cbcf", okKey:"#484c53", okText:"#f1f1ef" },
};
const HOME = "#f5a623", POWER = "#2b2d31";
function _rr(x,y,w,h,r,fill,stroke){ return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="${r.toFixed(1)}" fill="${fill}" stroke="${stroke}" stroke-width="0.8"/>`; }
function _ci(cx,cy,r,fill,stroke){ return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="0.8"/>`; }
function _gl(cx,cy,t,fs,fill){ return `<text x="${cx}" y="${cy+fs*0.35}" text-anchor="middle" font-family="var(--sans)" font-size="${fs}" fill="${fill}">${t}</text>`; }

function buildCalc(variant){
  const p = PAL[variant] || PAL.graphing, W = 210, pad = 7;
  const H = variant === "graphing" ? 430 : 366;
  const A = []; const push = (s) => A.push(s);
  push(`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="NumWorks ${variant}">`);
  push(_rr(pad, pad, W-2*pad, H-2*pad, 24, p.body, p.edge));
  push(`<text x="${W/2}" y="26" text-anchor="middle" font-family="var(--sans)" font-size="8.5" font-weight="700" letter-spacing="1.5" fill="${p.word}">NUMWORKS</text>`);

  const sx = 22, sy = 34, sw = W-44;
  const sh = Math.round(variant === "graphing" ? sw/1.42 : sw/2.4);
  if (variant === "graphing") screenGraphing(push, sx, sy, sw, sh);
  else screenScientific(push, sx, sy, sw, sh);

  const navY = sy+sh+42;
  const dx = 46, arw = 15;
  const arrow = (cx,cy,g) => push(_rr(cx-arw/2, cy-arw/2, arw, arw, 4.5, p.key, p.keyEdge) +
    `<text x="${cx}" y="${cy+3.2}" text-anchor="middle" font-size="8" fill="${p.text}">${g}</text>`);
  arrow(dx, navY-18, "▵"); arrow(dx, navY+18, "▿"); arrow(dx-18, navY, "◁"); arrow(dx+18, navY, "▹");
  push(_rr(90, navY-27, 40, 22, 11, HOME, HOME) + _gl(110, navY-16, "⌂", 9, "#5a3d05"));
  push(_ci(110, navY+12, 12, POWER, POWER) + _gl(110, navY+12, "⏻", 8.5, "#d7d8da"));
  push(_ci(158, navY, 14, p.okKey, p.keyEdge) + _gl(158, navY, "OK", 7.5, p.okText));
  push(_ci(188, navY, 14, p.okKey, p.keyEdge) + _gl(188, navY, "↩", 9, p.okText));

  const rowsG = [
    [["shift",null,null,"o"],["alpha","ALPHA",null],["x,n,t","cut",null],["var","copy",null],["▤","paste",null],["⌫","clear",null]],
    [["eˣ",null,"A"],["ln",null,"B"],["log",null,"C"],["i",null,"D"],[",",null,"E"],["xʸ",null,"F"]],
    [["sin","asin","G"],["cos","acos","H"],["tan","atan","I"],["π","=","J"],["√",null,"K"],["x²",null,"L"]],
    [["7",null,"M"],["8",null,"N"],["9",null,"O"],["(",null,"P"],[")",null,"Q"]],
    [["4",null,"R"],["5",null,"S"],["6",null,"T"],["×",null,"U"],["÷",null,"V"]],
    [["1",null,"W"],["2",null,"X"],["3",null,"Y"],["+",null,"Z"],["−",null,null]],
    [["0",null,null],[".",null,null],["×10ˣ",null,null],["Ans",null,null],["EXE",null,null]],
  ];
  const rowsS = [
    [["shift",null,null,"o"],["x,y,z","eˣ",null],["ln",null,null],["log",null,null],["var",null,null],["⌫","clear",null]],
    [["sin","asin",null],["cos","acos",null],["tan","atan",null],["π","=",null],["√",null,null],["x²",null,null]],
    [["7"],["8"],["9"],["("],[")"]], [["4"],["5"],["6"],["×"],["÷"]],
    [["1"],["2"],["3"],["+"],["−"]], [["0"],["."],["×10ˣ"],["Ans"],["EXE"]],
  ];
  const rows = variant === "graphing" ? rowsG : rowsS;
  const gx0 = 15, gW = W-30, gapx = 4.5, gapy = 5, rh = 22.5;
  let ry = navY+30;
  rows.forEach(row => {
    const n = row.length, kw = (gW-(n-1)*gapx)/n;
    row.forEach((k,i) => {
      const main = k[0], sec = k[1], letter = k[2], special = k[3];
      const x = gx0+i*(kw+gapx);
      let kf = p.key, kt = p.text;
      if (main === "EXE") { kf = HOME; kt = "#5a3d05"; }
      push(_rr(x, ry, kw, rh, Math.min(kw,rh)*0.42, kf, p.keyEdge));
      const mainColor = special === "o" ? p.sec : kt;
      const fs = main.length > 3 ? 6.3 : 8.2;
      push(`<text x="${(x+kw/2).toFixed(1)}" y="${(ry+rh/2+2.6).toFixed(1)}" text-anchor="middle" font-family="var(--sans)" font-size="${fs}" fill="${mainColor}">${_esc(main)}</text>`);
      if (sec) push(`<text x="${(x+3.5).toFixed(1)}" y="${(ry+5.6).toFixed(1)}" font-family="var(--sans)" font-size="4.6" fill="${p.sec}">${_esc(sec)}</text>`);
      if (letter) push(`<text x="${(x+kw-3.5).toFixed(1)}" y="${(ry+5.6).toFixed(1)}" text-anchor="end" font-family="var(--sans)" font-size="4.6" fill="${p.sec}">${letter}</text>`);
    });
    ry += rh+gapy;
  });
  push(`</svg>`);
  return A.join("");
}

function screenGraphing(push, x, y, w, h){
  push(_rr(x-4, y-4, w+8, h+8, 7, "#d8dade", "#d8dade"));
  push(_rr(x, y, w, h, 2, "#ffffff", "#ffffff"));
  push(`<rect x="${x}" y="${y}" width="${w}" height="12" fill="${HOME}"/>`);
  push(`<text x="${x+4}" y="${y+8.6}" font-family="var(--mono)" font-size="6" fill="#fff">rad</text>`);
  push(`<text x="${x+w/2}" y="${y+8.6}" text-anchor="middle" font-family="var(--sans)" font-size="6" font-weight="700" fill="#fff">APPLICATIONS</text>`);
  push(`<rect x="${x+w-13}" y="${y+3.5}" width="9" height="5" rx="1" fill="#fff"/>`);
  const apps = [["Calculs","#eceef1","="],["Grapheur","#f0a63a","∿"],["Python","#3b6fb0","py"],
                ["Statistiques","#4a90d9","▮▮"],["Probabilités","#e8930c","∩"],["Equations","#8a8f98","x="]];
  const cols = 3, iw = (w-4-2*6-(cols-1)*7)/cols, ih = iw*0.82, x0 = x+6, y0 = y+18, gy = 13;
  apps.forEach((a,k) => {
    const c = k%3, r = (k/3|0), ix = x0+c*(iw+7), iy = y0+r*(ih+gy+7);
    push(_rr(ix, iy, iw, ih, 3, a[1], "#dfe1e5"));
    push(`<text x="${(ix+iw/2).toFixed(1)}" y="${(iy+ih/2+2.4).toFixed(1)}" text-anchor="middle" font-family="var(--sans)" font-size="6" fill="${a[1]==='#eceef1'?'#333':'#fff'}">${a[2]}</text>`);
    push(`<text x="${(ix+iw/2).toFixed(1)}" y="${(iy+ih+8).toFixed(1)}" text-anchor="middle" font-family="var(--sans)" font-size="5.4" fill="#33353a">${a[0]}</text>`);
    if (k === 0) push(`<rect x="${(ix+iw/2-11).toFixed(1)}" y="${(iy+ih+10).toFixed(1)}" width="22" height="1.4" fill="${HOME}"/>`);
  });
}

function screenScientific(push, x, y, w, h){
  const S = "#c9d3c8", INK = "#28331f";
  push(_rr(x-4, y-4, w+8, h+8, 7, "#0c0f0b", "#0c0f0b"));
  push(_rr(x, y, w, h, 2, S, S));
  push(`<text x="${x+5}" y="${y+13}" font-family="var(--mono)" font-size="8.5" fill="${INK}">Calculs</text>`);
  push(`<text x="${x+w-26}" y="${y+13}" font-family="var(--mono)" font-size="7" fill="${INK}">deg</text>`);
  push(`<rect x="${x+w-13}" y="${y+7.5}" width="9" height="6" rx="1" fill="none" stroke="${INK}" stroke-width="0.8"/><rect x="${x+w-11}" y="${y+9}" width="4.5" height="3" fill="${INK}"/>`);
  const n = 4, m = 6, gap = 5, iw = (w-2*m-(n-1)*gap)/n, iy = y+17, ih = Math.min(iw, h-26);
  for (let i = 0; i < n; i++){
    const ix = x+m+i*(iw+gap);
    push(`<rect x="${ix.toFixed(1)}" y="${iy.toFixed(1)}" width="${iw.toFixed(1)}" height="${ih.toFixed(1)}" fill="none" stroke="${INK}" stroke-width="1"/>`);
    const cx = ix+iw/2, cy = iy+ih/2;
    if (i === 0){
      push(`<line x1="${ix}" y1="${cy}" x2="${ix+iw}" y2="${cy}" stroke="${INK}" stroke-width="0.8"/><line x1="${cx}" y1="${iy}" x2="${cx}" y2="${iy+ih}" stroke="${INK}" stroke-width="0.8"/>`);
      push(`<text x="${ix+iw*0.27}" y="${iy+iw*0.34}" text-anchor="middle" font-size="6" fill="${INK}">+</text><text x="${ix+iw*0.74}" y="${iy+iw*0.34}" text-anchor="middle" font-size="6" fill="${INK}">−</text><text x="${ix+iw*0.27}" y="${iy+iw*0.82}" text-anchor="middle" font-size="6" fill="${INK}">×</text><text x="${ix+iw*0.74}" y="${iy+iw*0.82}" text-anchor="middle" font-size="6" fill="${INK}">=</text>`);
    } else if (i === 1){
      [0.28,0.5,0.72].forEach((fx,bi) => { const bh = [0.4,0.7,0.55][bi]*ih; push(`<rect x="${(ix+iw*fx-2).toFixed(1)}" y="${(iy+ih-bh-2).toFixed(1)}" width="4" height="${bh.toFixed(1)}" fill="${INK}"/>`); });
    } else if (i === 2){
      push(`<line x1="${ix}" y1="${cy}" x2="${ix+iw}" y2="${cy}" stroke="${INK}" stroke-width="0.7"/><line x1="${cx}" y1="${iy}" x2="${cx}" y2="${iy+ih}" stroke="${INK}" stroke-width="0.7"/>`);
      push(`<rect x="${cx.toFixed(1)}" y="${iy.toFixed(1)}" width="${(iw/2).toFixed(1)}" height="${(ih/2).toFixed(1)}" fill="${INK}" opacity="0.55"/>`);
      push(`<text x="${cx}" y="${iy+ih-3}" text-anchor="middle" font-size="5.2" fill="${INK}">f(x)</text>`);
    } else {
      push(`<circle cx="${(cx-1).toFixed(1)}" cy="${(cy-1).toFixed(1)}" r="${(iw*0.3).toFixed(1)}" fill="none" stroke="${INK}" stroke-width="1"/><line x1="${(cx+iw*0.15).toFixed(1)}" y1="${(cy+iw*0.15).toFixed(1)}" x2="${(ix+iw-2).toFixed(1)}" y2="${(iy+ih-2).toFixed(1)}" stroke="${INK}" stroke-width="1.2"/>`);
      push(`<text x="${(cx-1).toFixed(1)}" y="${(cy+1).toFixed(1)}" text-anchor="middle" font-size="5" fill="${INK}">x=</text>`);
    }
  }
  push(`<line x1="${x+w*0.3}" y1="${y+h-9}" x2="${x+w*0.7}" y2="${y+h-9}" stroke="${INK}" stroke-width="1.4"/>`);
}
