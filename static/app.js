/* NeuroChess: vista web sin frameworks. La validación y la IA viven en Python. */
'use strict';
const $ = id => document.getElementById(id);
const FILES = 'abcdefgh';
const PIECES = {K:'♔',Q:'♕',R:'♖',B:'♗',N:'♘',P:'♙',k:'♚',q:'♛',r:'♜',b:'♝',n:'♞',p:'♟'};
const NAMES = {q:'Dama',r:'Torre',b:'Alfil',n:'Caballo'};
let game = null, selected = null, busy = false, thinking = false, flipped = false, activeRun = 0;
let tipTimer;

function isWhite(piece){return piece && piece !== '.' && piece === piece.toUpperCase()}
function pieceIsMine(piece){return piece && piece !== '.' && (isWhite(piece) === (game.player === 'white'))}
function playerTurn(){return game && game.turn === game.player && !game.status.finished}
function cellAt(square){const f=FILES.indexOf(square[0]),r=8-Number(square[1]);return game.board[r]?.[f] || '.'}
function squareFor(row,col){return FILES[col]+(8-row)}
function html(tag,cls,text){const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el}

async function post(path,data){
  const res=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const payload=await res.json();
  if(!res.ok)throw new Error(payload.error || 'No se pudo contactar al servidor');
  return payload;
}
function toast(message){clearTimeout(tipTimer);const el=$('toast');el.textContent=message;el.classList.add('show');tipTimer=setTimeout(()=>el.classList.remove('show'),3300)}
function updateText(id,value){$(id).textContent=value}

function renderBoard(){
  if(!game)return;
  const board=$('board');board.replaceChildren();
  const orientation=flipped?'black':'white';
  const ranks=orientation==='white'?[0,1,2,3,4,5,6,7]:[7,6,5,4,3,2,1,0];
  const files=orientation==='white'?[0,1,2,3,4,5,6,7]:[7,6,5,4,3,2,1,0];
  const lastMove=game.moves.at(-1)?.uci || '';
  const lastFrom=lastMove.slice(0,2),lastTo=lastMove.slice(2,4);
  const legalForSelected=selected?game.legal_moves.filter(x=>x.slice(0,2)===selected):[];
  const kingInCheck = game.status.check ? (game.turn==='white'?'K':'k') : null;
  let kingSquare='';
  if(kingInCheck){for(let r=0;r<8;r++)for(let c=0;c<8;c++)if(game.board[r][c]===kingInCheck)kingSquare=squareFor(r,c)}
  for(const [visualRow,r] of ranks.entries()){
    for(const [visualCol,c] of files.entries()){
      const square=squareFor(r,c),piece=game.board[r][c];
      const light=(r+c)%2===0;
      const el=html('button',`square ${light?'light':'dark'}`);
      el.type='button';el.setAttribute('role','gridcell');el.dataset.square=square;
      el.setAttribute('aria-label',`${square}, ${piece==='.'?'vacía':isWhite(piece)?'pieza blanca':'pieza negra'} ${piece!=='.'?piece.toUpperCase():''}`);
      if(square===selected)el.classList.add('selected');
      if(square===lastFrom || square===lastTo)el.classList.add('last-move');
      if(square===kingSquare)el.classList.add('check-square');
      if(game.hint && [game.hint.uci.slice(0,2),game.hint.uci.slice(2,4)].includes(square))el.classList.add('hint-square');
      const canMove=legalForSelected.some(uci=>uci.slice(2,4)===square);
      if(canMove){el.append(html('span',piece==='.'?'move-dot':'capture-ring'))}
      if(piece!=='.'){
        const token=html('span',`piece ${isWhite(piece)?'white':'black'}`,PIECES[piece]);
        token.setAttribute('aria-hidden','true');el.append(token);
      }
      if(visualCol===0)el.append(html('span','coord rank',String(8-r)));
      if(visualRow===7)el.append(html('span','coord file',FILES[c]));
      el.addEventListener('click',()=>selectSquare(square));
      board.appendChild(el);
    }
  }
}

function renderMoves(){
  const history=$('moveHistory');history.replaceChildren();
  const all=game.moves;
  updateText('count',`${all.length} ${all.length===1?'jugada':'jugadas'}`);
  if(!all.length){history.append(html('p','empty-history','Los movimientos aparecerán aquí.'));return}
  const groups=[];
  for(const move of all){
    let row=groups.find(g=>g.number===move.number);
    if(!row){row={number:move.number};groups.push(row)}
    row[move.side]=move;
  }
  for(const row of groups){
    const line=html('div','move-row');line.append(html('span','num',row.number+'.'));
    for(const side of ['white','black']){
      const move=row[side],isLatest=move===all.at(-1);
      line.append(html('span',`played ${isLatest?'latest':''}`,move?.san || '···'));
    }
    history.append(line);
  }
  history.scrollTop=history.scrollHeight;
}

function renderMetrics(){
  const m=game.last_search;
  updateText('nodes',m?Number(m.nodes).toLocaleString('es-PE'):'—');
  updateText('cuts',m?Number(m.cutoffs).toLocaleString('es-PE'):'—');
  updateText('time',m?`${(m.elapsed_ms/1000).toFixed(2)} s`:'—');
  updateText('depth',m?String(m.depth):'—');
  const evalCp = m?m.score_cp:0;
  const scoreDisplay = Math.abs(evalCp)>=99000?(evalCp>0?'+MATE':'−MATE'):
      `${evalCp>0?'+':''}${(evalCp/100).toFixed(2)}`;
  updateText('score',scoreDisplay);
  $('evalFill').style.width=`${Math.max(2,Math.min(98,50+42*Math.tanh(evalCp/500)))}%`;
  updateText('engineNote',m?(m.depth<game.difficulty?
    'Se alcanzó el límite de tiempo; se muestra la última profundidad completada.':
    `Última búsqueda de la IA: ${m.best_uci.toUpperCase()} · evaluación desde blancas.`):
    'Las estadísticas aparecerán después de la primera jugada de la IA.');
}

function render(){
  if(!game)return;
  renderBoard();renderMoves();renderMetrics();
  const finished=game.status.finished;
  $('undoBtn').disabled=!game.can_undo||busy;
  $('hintBtn').disabled=!playerTurn()||busy;
  $('drawBtn').hidden=!game.status.claimable_draw||finished||!playerTurn();
  $('drawBtn').disabled=busy;
  $('statusPill').classList.toggle('done',finished);
  if(finished){
    updateText('statusPill',game.status.winner?(game.status.winner===game.player?'Ganaste':'Gana la IA'):'Tablas');
    updateText('thinkingLabel','PARTIDA FINALIZADA');
    updateText('feedback',game.status.reason+(game.status.winner?' · Ganan '+(game.status.winner==='white'?'las blancas':'las negras'):'')+'.');
  }else if(thinking){
    updateText('statusPill','Calculando...');updateText('thinkingLabel','PENSANDO...');
    updateText('feedback','La IA evalúa variantes con Minimax y poda alfa-beta.');
  }else if(playerTurn()){
    updateText('statusPill','Tu turno');updateText('thinkingLabel','ESPERANDO...');
    updateText('feedback',game.hint?`Pista: considera ${game.hint.uci.slice(0,2)} → ${game.hint.uci.slice(2,4)}.`:
      game.status.check?'¡Jaque! Protege tu rey.':'Selecciona una pieza y después una casilla marcada.');
  }else{
    updateText('statusPill','Turno IA');updateText('thinkingLabel','PREPARANDO...');
    updateText('feedback','Las blancas siempre empiezan. La IA realizará su jugada.');
  }
  $('thinkingLabel').classList.toggle('is-thinking',thinking);
  $('topSub').textContent=`Motor Python · ${(game.player==='white'?'Negras':'Blancas')} · Minimax`;
  $('bottomSub').textContent=`${game.player==='white'?'Blancas':'Negras'} · ${game.player==='white'?'comienzas tú':'comienza la IA'}`;
}

async function selectSquare(square){
  if(!playerTurn()||busy)return;
  const piece=cellAt(square);
  if(pieceIsMine(piece)){
    selected=selected===square?null:square;renderBoard();return;
  }
  if(!selected)return;
  const options=game.legal_moves.filter(uci=>uci.startsWith(selected+square));
  if(!options.length){toast('Movimiento no permitido. Usa las casillas marcadas.');return}
  if(options.length>1){choosePromotion(options);return}
  await makeHumanMove(options[0]);
}

function choosePromotion(options){
  const dialog=$('promotionDialog'),choices=$('promotionChoices');choices.replaceChildren();
  for(const letter of ['q','r','b','n']){
    const uci=options.find(x=>x.endsWith(letter));
    if(!uci)continue;
    const piece=game.player==='white'?letter.toUpperCase():letter;
    const button=html('button','',PIECES[piece]);button.type='button';button.title=NAMES[letter];
    button.setAttribute('aria-label',NAMES[letter]);
    button.onclick=()=>{dialog.close();void makeHumanMove(uci)};
    choices.append(button);
  }
  dialog.showModal();
}

async function makeHumanMove(uci){
  if(!game||busy)return;
  const run=activeRun;
  busy=true;selected=null;
  try{
    const result=await post('/api/move',{game_id:game.game_id,move:uci});
    if(run!==activeRun)return;
    game=result;busy=false;render();
    if(!game.status.finished)await makeAIMove(run);
  }catch(error){if(run===activeRun){busy=false;toast(error.message);render()}}
}

async function makeAIMove(run=activeRun){
  if(!game || game.status.finished || game.turn===game.player || run!==activeRun)return;
  const id=game.game_id;
  busy=true;thinking=true;render();
  try{
    const result=await post('/api/ai',{game_id:id});
    if(run!==activeRun || !game || game.game_id!==id)return;
    game=result;
  }catch(error){
    if(run===activeRun)toast(error.message);
  }finally{
    if(run===activeRun){thinking=false;busy=false;render()}
  }
}

async function newGame(){
  const run=++activeRun;
  selected=null;busy=true;thinking=false;game=null;
  updateText('feedback','Iniciando partida...');
  const player=$('chooseBlack').classList.contains('active')?'black':'white';
  flipped=player==='black';
  try{
    const data=await post('/api/new',{difficulty:Number($('difficulty').value),player});
    if(run!==activeRun)return;
    game=data;busy=false;render();
    if(player==='black')await makeAIMove(run);
  }catch(error){if(run===activeRun){busy=false;toast(error.message);updateText('feedback','No se pudo iniciar. Ejecuta python app.py.')}}
}

async function undo(){
  if(!game?.can_undo||busy)return;
  busy=true;
  try{game=await post('/api/undo',{game_id:game.game_id});selected=null;render()}
  catch(e){toast(e.message)}
  finally{busy=false;render()}
}

async function getHint(){
  if(!playerTurn()||busy)return;
  const run=activeRun;
  busy=true;updateText('feedback','Calculando una sugerencia...');render();
  try{const answer=await post('/api/hint',{game_id:game.game_id});if(run!==activeRun)return;game=answer;render()}
  catch(e){if(run===activeRun)toast(e.message)}
  finally{if(run===activeRun){busy=false;render()}}
}

function setPlayer(player){
  for(const p of ['White','Black']){$('choose'+p).classList.toggle('active',p.toLowerCase()===player);$('choose'+p).setAttribute('aria-pressed',String(p.toLowerCase()===player))}
  toast('Pulsa «Nueva partida» para aplicar este cambio.');
}
$('chooseWhite').addEventListener('click',()=>setPlayer('white'));
$('chooseBlack').addEventListener('click',()=>setPlayer('black'));
$('newBtn').addEventListener('click',()=>void newGame());
$('undoBtn').addEventListener('click',()=>void undo());
$('hintBtn').addEventListener('click',()=>void getHint());
$('flipBtn').addEventListener('click',()=>{flipped=!flipped;renderBoard()});
$('drawBtn').addEventListener('click',async()=>{
  if(!game||busy)return;busy=true;try{game=await post('/api/claim-draw',{game_id:game.game_id})}catch(e){toast(e.message)}finally{busy=false;render()}
});
$('cancelPromotion').addEventListener('click',()=>$('promotionDialog').close());
$('difficulty').addEventListener('change',()=>{
  updateText('depthText',`${$('difficulty').value} ${$('difficulty').value==='1'?'media jugada':'medias jugadas'}`);
  toast('La nueva dificultad se aplica al iniciar una nueva partida.');
});
$('themeToggle').addEventListener('click',()=>{
  const theme=document.body.dataset.theme==='dark'?'light':'dark';
  document.body.dataset.theme=theme;
  $('themeToggle').textContent=theme==='dark'?'☀':'☾';
  try{localStorage.setItem('neurochess-theme',theme)}catch(e){}
});
try{const theme=localStorage.getItem('neurochess-theme');if(['dark','light'].includes(theme)){document.body.dataset.theme=theme;$('themeToggle').textContent=theme==='dark'?'☀':'☾'}}catch(e){}
window.addEventListener('keydown',ev=>{if(ev.key==='Enter' && ev.target===document.body)void newGame()});
void newGame();
