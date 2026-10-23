'use strict';
const $ = id => document.getElementById(id);
const FILES = 'abcdefgh';
const NAMES = {p:'peón', n:'caballo', b:'alfil', r:'torre', q:'dama', k:'rey'};
const LEVELS = {1:'Principiante',2:'Intermedio',3:'Avanzado',4:'Experto'};
const LEVEL_NOTES = {1:'Una buena forma de empezar.',2:'Un equilibrio entre rapidez y cálculo.',3:'Más variantes, mejores respuestas.',4:'Hasta 5,5 segundos para encontrar una jugada.'};
const SESSION_KEY = 'neurochess-session-v3';
let game=null, selected=null, flipped=false, generation=0, pending='', recovery=false, notice='';
let tipTimer, soundOn=false, audioContext;
function readPref(key,fallback){try{return localStorage.getItem(key)||fallback}catch{return fallback}}
function savePref(key,value){try{localStorage.setItem(key,value)}catch{}}
function forgetSession(){try{localStorage.removeItem(SESSION_KEY)}catch{}}
function persist(){if(game)savePref(SESSION_KEY,JSON.stringify({game_id:game.game_id,player:game.player,difficulty:game.difficulty}))}
function el(tag,cls,text){const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node}
function setText(id,text){$(id).textContent=text}
function white(piece){return piece!=='.'&&piece===piece.toUpperCase()}
function mine(piece){return piece!=='.'&&white(piece)===(game.player==='white')}
function myTurn(){return game&&!game.status.finished&&game.turn===game.player}
function pieceAt(square){return game.board[8-Number(square[1])][FILES.indexOf(square[0])]}
function pieceImage(piece,cls='piece'){const img=el('img',cls);img.src='/pieces/'+(white(piece)?'w':'b')+piece.toUpperCase()+'.svg';img.alt='';img.draggable=false;img.setAttribute('aria-hidden','true');return img}
function toast(message){clearTimeout(tipTimer);setText('toast',message);$('toast').classList.add('show');tipTimer=setTimeout(()=>$('toast').classList.remove('show'),4200)}
async function post(path,data){
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),35000);
 try{
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data),signal:controller.signal});
  const contentType=response.headers.get('content-type')||'';
  if(!contentType.includes('application/json'))throw new Error('El servidor está despertando. Prueba de nuevo en unos segundos.');
  const answer=await response.json();
  if(!response.ok){const error=new Error(answer.error||'No se pudo completar la acción.');error.status=response.status;throw error}
  return answer;
 }catch(error){
  if(error.name==='AbortError')throw new Error('La conexión tardó demasiado. Puedes reintentar sin perder tu partida.');
  if(error instanceof TypeError)throw new Error('No hay conexión con el servidor. Comprueba tu conexión y reintenta.');
  throw error;
 }finally{clearTimeout(timeout)}
}
function gameRequest(path,extra={}){return post(path,{game_id:game.game_id,revision:game.revision,...extra})}
function playSound(){
 if(!soundOn)return;
 try{
  audioContext=audioContext||new (window.AudioContext||window.webkitAudioContext)();
  if(audioContext.state!=='running')return;
  const tone=audioContext.createOscillator(),volume=audioContext.createGain();
  tone.type='sine';tone.frequency.setValueAtTime(510,audioContext.currentTime);tone.frequency.exponentialRampToValueAtTime(260,audioContext.currentTime+.06);
  volume.gain.setValueAtTime(.035,audioContext.currentTime);volume.gain.exponentialRampToValueAtTime(.001,audioContext.currentTime+.08);
  tone.connect(volume);volume.connect(audioContext.destination);tone.start();tone.stop(audioContext.currentTime+.08);
 }catch{}
}
function renderBoard(){
 if(!game)return;
 const board=$('board'),focus=document.activeElement?.dataset?.square;
 const last=game.moves.at(-1)?.uci||'', options=selected?game.legal_moves.filter(m=>m.startsWith(selected)):[];
 const rows=flipped?[7,6,5,4,3,2,1,0]:[0,1,2,3,4,5,6,7],cols=flipped?[7,6,5,4,3,2,1,0]:[0,1,2,3,4,5,6,7];
 const frag=document.createDocumentFragment();
 for(const [vr,r] of rows.entries())for(const [vc,c] of cols.entries()){
  const square=FILES[c]+(8-r),piece=game.board[r][c],button=el('button','square '+((r+c)%2?'dark':'light'));
  button.type='button';button.dataset.square=square;button.setAttribute('role','gridcell');
  button.setAttribute('aria-label',square+', '+(piece==='.'?'vacía':NAMES[piece.toLowerCase()]+' '+(white(piece)?'blanco':'negro')));
  button.setAttribute('aria-selected',String(square===selected));
  button.setAttribute('aria-rowindex',vr+1);button.setAttribute('aria-colindex',vc+1);
  button.tabIndex=square===(focus||selected||(flipped?'e7':'e2'))?0:-1;
  if(square===selected)button.classList.add('selected');
  if([last.slice(0,2),last.slice(2,4)].includes(square))button.classList.add('last-move');
  if(game.hint&&[game.hint.uci.slice(0,2),game.hint.uci.slice(2,4)].includes(square))button.classList.add('hint-square');
  if(game.status.check&&piece===(game.turn==='white'?'K':'k'))button.classList.add('check-square');
  if(piece!=='.')button.append(pieceImage(piece));
  if(options.some(m=>m.slice(2,4)===square))button.append(el('span',piece==='.'?'move-dot':'capture-ring'));
  if(vc===0)button.append(el('span','coord rank',8-r));
  if(vr===7)button.append(el('span','coord file',FILES[c]));
  button.addEventListener('click',()=>void selectSquare(square));
  button.addEventListener('keydown',ev=>{
   if(ev.key==='Escape'){selected=null;renderBoard();return}
   const delta={ArrowLeft:-1,ArrowRight:1,ArrowUp:-8,ArrowDown:8}[ev.key];
   if(delta===undefined)return;
   ev.preventDefault();
   const index=vr*8+vc,next=index+delta;
   if(next<0||next>63||(ev.key==='ArrowLeft'&&vc===0)||(ev.key==='ArrowRight'&&vc===7))return;
   const cells=board.querySelectorAll('button');cells[index].tabIndex=-1;cells[next].tabIndex=0;cells[next].focus();
  });
  frag.append(button);
 }
 board.replaceChildren(frag);
 board.setAttribute('aria-busy',String(Boolean(pending)));
 if(focus){const target=board.querySelector('[data-square="'+focus+'"]');if(target)target.focus({preventScroll:true})}
}
function renderMoves(){
 const history=$('moveHistory'),atBottom=history.scrollHeight-history.scrollTop-history.clientHeight<40;
 const oldLength=Number(history.dataset.length||0);history.dataset.length=game.moves.length;
 setText('count',game.moves.length+' '+(game.moves.length===1?'jugada':'jugadas'));
 if(!game.moves.length){
  history.innerHTML='<div class="empty-history"><svg viewBox="0 0 40 40" aria-hidden="true"><path d="M10 8h20v26H10zM15 4h10v8H15zM15 18h10m-10 6h10m-10 6h6"/></svg><strong>La primera jugada '+(game.player==='white'?'es tuya.':'es del ordenador.')+'</strong><p>Elige una pieza y luego su destino.<br>Las casillas marcadas te guían.</p></div>';return;
 }
 const scrollTop=history.scrollTop,groups=new Map();
 for(const move of game.moves){if(!groups.has(move.number))groups.set(move.number,{});groups.get(move.number)[move.side]=move}
 const frag=document.createDocumentFragment();
 for(const [number,moves] of groups){
  const row=el('div','move-row');row.append(el('span','num',number+'.'));
  for(const side of ['white','black']){
   const move=moves[side],node=el('span','played'+(move===game.moves.at(-1)?' latest':''),move?.san||'—');
   if(move)node.title=move.uci.slice(0,2)+' → '+move.uci.slice(2,4);
   row.append(node);
  }frag.append(row);
 }
 history.replaceChildren(frag);
 history.scrollTop=atBottom||oldLength!==game.moves.length?history.scrollHeight:scrollTop;
}
function renderCaptures(){
 const values={p:1,n:3,b:3,r:5,q:9,k:0},captured={white:[],black:[]};
 for(const move of game.moves)if(move.captured)captured[move.side].push(move.captured);
 const totals=side=>captured[side].reduce((sum,p)=>sum+values[p.toLowerCase()],0);
 for(const actor of ['human','opponent']){
  const side=actor==='human'?game.player:(game.player==='white'?'black':'white'),target=$(actor+'Captures');
  target.replaceChildren();captured[side].sort((a,b)=>values[b.toLowerCase()]-values[a.toLowerCase()]);
  for(const p of captured[side])target.append(pieceImage(p,'captured-piece'));
  const advantage=totals(side)-totals(side==='white'?'black':'white');
  if(advantage>0)target.append(el('span','material','+'+advantage));
 }
}
function renderMetrics(){
 const m=game.last_search;
 setText('nodes',m?m.nodes.toLocaleString('es-PE'):'—');setText('cuts',m?m.cutoffs.toLocaleString('es-PE'):'—');
 setText('time',m?(m.elapsed_ms/1000).toFixed(2)+' s':'—');setText('depth',m?m.depth+' / '+game.difficulty:'—');
 const score=m?m.score_cp:0;
 setText('score',Math.abs(score)>=99000?(score>0?'+Mate':'−Mate'):(score>0?'+':'')+(score/100).toFixed(2));
 $('evalFill').style.width=Math.max(2,Math.min(98,50+42*Math.tanh(score/500)))+'%';
 setText('engineNote',m?(m.depth<game.difficulty?'El límite de tiempo redujo la profundidad. ':'')+'Evaluación desde el lado de las blancas.':'El análisis aparece tras la primera respuesta.');
}
function render(){
 const hasGame=Boolean(game),busy=Boolean(pending),finished=game?.status.finished;
 $('boardLoading').hidden=hasGame||!busy;
 $('difficulty').disabled=busy||!hasGame;
 $('undoBtn').disabled=!hasGame||!game.can_undo||busy;
 $('hintBtn').disabled=!myTurn()||busy;
 $('resignBtn').disabled=!hasGame||finished||busy;
 $('exportBtn').disabled=!game?.moves.length;
 $('retryBtn').hidden=!recovery;
 $('retryBtn').disabled=busy;
 $('drawBtn').hidden=!game?.status.claimable_draw||finished||!myTurn();$('drawBtn').disabled=busy;
 setText('hintBtn',pending==='hint'?'Calculando…':'◇ Pista');
 if(!game){setText('feedback',notice||'Preparando tu partida…');return}
 renderBoard();renderMoves();renderCaptures();renderMetrics();
 $('difficulty').value=game.difficulty;
 setText('difficultyNote',pending==='settings'?'Aplicando dificultad…':LEVEL_NOTES[game.difficulty]);
 setText('opponentLevel',LEVELS[game.difficulty]);
 setText('topSub','Juega con '+(game.player==='white'?'negras':'blancas'));
 setText('bottomSub','Juegas con '+(game.player==='white'?'blancas':'negras'));
 $('thinkingLabel').classList.toggle('is-thinking',pending==='ai');
 $('statusPill').classList.toggle('done',Boolean(finished));
 if(finished){
  const title=game.status.winner?(game.status.winner===game.player?'Ganaste':'Gana el ordenador'):'Tablas';
  setText('statusPill',title);setText('thinkingLabel','Partida terminada');setText('feedback',game.status.reason+'. '+(game.status.winner?title+'. ':'')+'Puedes revisar las jugadas o empezar otra partida.');
 }else if(pending==='ai'){
  setText('statusPill','Su turno');setText('thinkingLabel','Pensando…');setText('feedback','El ordenador está pensando su respuesta…');
 }else if(pending==='hint'){
  setText('statusPill','Tu turno');setText('thinkingLabel','Calculando pista…');setText('feedback','Buscando una sugerencia para ti…');
 }else{
  setText('thinkingLabel',game.turn===game.player?'Listo':'Su turno');
  setText('statusPill',game.status.check?'Jaque':myTurn()?'Tu turno':'Su turno');
  setText('feedback',notice||(game.hint?'Pista: '+game.hint.uci.slice(0,2)+' → '+game.hint.uci.slice(2,4)+'.':game.status.check?'Tu rey está en jaque. Busca una casilla segura o cubre el ataque.':myTurn()?'Selecciona una pieza para ver sus movimientos.':'El ordenador tiene la siguiente jugada.'));
 }
}
function accept(data){game=data;savePref('neurochess-difficulty',String(game.difficulty));persist();render()}
function fail(error){notice=error.message;recovery=true;toast(error.message)}
async function selectSquare(square){
 if(!myTurn()||pending)return;
 if(mine(pieceAt(square))){selected=selected===square?null:square;renderBoard();return}
 if(!selected)return;
 const options=game.legal_moves.filter(m=>m.startsWith(selected+square));
 if(!options.length){selected=null;renderBoard();return}
 if(options.length>1){choosePromotion(options);return}
 await moveHuman(options[0]);
}
function choosePromotion(options){
 const choices=$('promotionChoices');choices.replaceChildren();
 for(const letter of ['q','r','b','n']){
  const uci=options.find(m=>m.endsWith(letter));if(!uci)continue;
  const button=el('button','');button.type='button';button.setAttribute('aria-label',NAMES[letter]);
  button.append(pieceImage(game.player==='white'?letter.toUpperCase():letter),el('span','',NAMES[letter]));
  button.addEventListener('click',()=>{$('promotionDialog').close();void moveHuman(uci)});choices.append(button);
 }$('promotionDialog').showModal();
}
async function moveHuman(move){
 if(!game||pending||!myTurn())return;
 const run=generation;pending='move';selected=null;notice='';recovery=false;render();
 try{
  const data=await gameRequest('/api/move',{move});if(run!==generation)return;
  pending='';accept(data);playSound();if(!data.status.finished)await moveAI(run);
 }catch(error){if(run===generation){pending='';fail(error);render()}}
}
async function moveAI(run=generation){
 if(run!==generation||!game||game.status.finished||myTurn())return;
 pending='ai';notice='';recovery=false;render();
 try{const data=await gameRequest('/api/ai');if(run!==generation)return;game=data;persist();playSound()}
 catch(error){if(run===generation)fail(error)}
 finally{if(run===generation){pending='';render()}}
}
async function startGame(player='white'){
 const run=++generation,previous=game;pending='new';game=null;selected=null;notice='';recovery=false;render();
 try{
  const data=await post('/api/new',{player,difficulty:Number($('difficulty').value)});
  if(run!==generation)return;flipped=player==='black';pending='';accept(data);
  if(!myTurn())await moveAI(run);
 }catch(error){if(run===generation){pending='';game=previous;fail(error);render()}}
}
async function initialize(){
 const run=++generation;pending='load';notice='';recovery=false;render();
 let saved;try{saved=JSON.parse(readPref(SESSION_KEY,'null'))}catch{}
 if(saved?.game_id){
  try{
   const data=await post('/api/state',{game_id:saved.game_id});
   if(run!==generation)return;flipped=data.player==='black';pending='';accept(data);
   if(!data.status.finished&&!myTurn())await moveAI(run);return;
  }catch(error){
   if(run!==generation)return;
   if(error.status!==404){pending='';fail(error);render();return}
   forgetSession();toast('El servidor se reinició. Comenzamos una nueva partida.');
  }
 }
 pending='';await startGame(saved?.player||'white');
}
async function action(path,type,extra={}){
 if(!game||pending)return;
 const run=generation;pending=type;notice='';recovery=false;render();
 try{const data=await gameRequest(path,extra);if(run!==generation)return;selected=null;game=data;persist()}
 catch(error){if(run===generation)fail(error)}
 finally{if(run===generation){pending='';render()}}
}
async function retry(){
 if(pending)return;
 if(!game){await initialize();return}
 const run=generation;pending='load';notice='';recovery=false;render();
 try{
  const data=await post('/api/state',{game_id:game.game_id});
  if(run!==generation)return;pending='';accept(data);
  if(!game.status.finished&&!myTurn())await moveAI(run);
 }catch(error){
  if(run!==generation)return;pending='';
  if(error.status===404){forgetSession();toast('Esta partida ya no está disponible. Puedes guardar su PGN y empezar otra.');notice='El servidor se reinició. Guarda tu PGN y empieza una nueva partida.';recovery=false}
  else fail(error);render();
 }
}
function openNewGame(){
 if($('promotionDialog').open)$('promotionDialog').close();
 $('newGameForm').elements.color.value=game?.player||'white';
 setText('newGameLevel',LEVELS[$('difficulty').value]);
 setText('newGameWarning',game?.moves.length&&!game.status.finished?'Se cerrará tu partida actual. Puedes cancelarlo para seguir jugando.':'Elige tu color. Las blancas siempre empiezan.');
 $('newGameDialog').showModal();
}
function pgn(){
 if(!game)return '';
 const result=game.status.finished?(game.status.winner==='white'?'1-0':game.status.winner==='black'?'0-1':'1/2-1/2'):'*';
 const stamp=new Date().toISOString().slice(0,10).replaceAll('-','.');
 const tags={Event:'NeuroChess - Partida de práctica',Site:window.location.origin,Date:stamp,Round:'-',White:game.player==='white'?'Jugador':'NeuroChess',Black:game.player==='black'?'Jugador':'NeuroChess',Result:result};
 const notation=[];for(const m of game.moves){if(m.side==='white')notation.push(m.number+'.');notation.push(m.san)}
 return Object.entries(tags).map(([key,value])=>'['+key+' "'+value+'"]').join('\n')+'\n\n'+notation.join(' ')+' '+result+'\n';
}
function exportPGN(){
 if(!game?.moves.length)return;
 const blob=new Blob([pgn()],{type:'application/x-chess-pgn;charset=utf-8'}),url=URL.createObjectURL(blob),link=el('a');
 link.href=url;link.download='neurochess-'+new Date().toISOString().slice(0,10)+'.pgn';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
$('newBtn').addEventListener('click',openNewGame);
$('cancelNewGame').addEventListener('click',()=>$('newGameDialog').close());
$('newGameForm').addEventListener('submit',event=>{event.preventDefault();const player=$('newGameForm').elements.color.value;$('newGameDialog').close();void startGame(player)});
$('undoBtn').addEventListener('click',()=>void action('/api/undo','undo'));
$('hintBtn').addEventListener('click',()=>{if(myTurn())void action('/api/hint','hint')});
$('flipBtn').addEventListener('click',()=>{flipped=!flipped;renderBoard()});
$('retryBtn').addEventListener('click',()=>void retry());
$('drawBtn').addEventListener('click',()=>void action('/api/claim-draw','draw'));
$('exportBtn').addEventListener('click',exportPGN);
$('resignBtn').addEventListener('click',()=>$('resignDialog').showModal());
$('cancelResign').addEventListener('click',()=>$('resignDialog').close());
$('confirmResign').addEventListener('click',()=>{$('resignDialog').close();void action('/api/resign','resign')});
$('cancelPromotion').addEventListener('click',()=>$('promotionDialog').close());
$('difficulty').addEventListener('change',()=>{const difficulty=Number($('difficulty').value);void action('/api/settings','settings',{difficulty})});
$('boardTheme').addEventListener('change',()=>{document.body.dataset.board=$('boardTheme').value;savePref('neurochess-board',$('boardTheme').value)});
function applyTheme(theme){document.body.dataset.theme=theme;$('themeToggle').setAttribute('aria-label','Activar tema '+(theme==='dark'?'claro':'oscuro'));document.querySelector('meta[name="theme-color"]').content=theme==='dark'?'#202520':'#f4f2ec'}
$('themeToggle').addEventListener('click',()=>{const theme=document.body.dataset.theme==='dark'?'light':'dark';applyTheme(theme);savePref('neurochess-theme',theme)});
function renderSound(){
 $('soundToggle').setAttribute('aria-pressed',String(soundOn));
 $('soundToggle').setAttribute('aria-label',(soundOn?'Desactivar':'Activar')+' sonido');
 $('soundToggle').querySelector('path').setAttribute('d',soundOn?'M11 4 5 9H2v6h3l6 5V4Zm4 4a5 5 0 0 1 0 8m3-11a9 9 0 0 1 0 14':'M11 4 5 9H2v6h3l6 5V4Zm5 5 5 6m0-6-5 6');
 $('soundToggle').style.opacity=soundOn?'1':'.65';
}
$('soundToggle').addEventListener('click',()=>{
 soundOn=!soundOn;savePref('neurochess-sound',String(soundOn));renderSound();
 if(soundOn){try{audioContext=audioContext||new(window.AudioContext||window.webkitAudioContext)();void audioContext.resume().then(playSound)}catch{}}
});
applyTheme(readPref('neurochess-theme','light')==='dark'?'dark':'light');
const palette=readPref('neurochess-board','sage');if(['sage','wood','slate'].includes(palette)){document.body.dataset.board=palette;$('boardTheme').value=palette}
const preferredLevel=readPref('neurochess-difficulty','2');
if(LEVELS[preferredLevel])$('difficulty').value=preferredLevel;
soundOn=readPref('neurochess-sound','false')==='true';renderSound();
void initialize();
