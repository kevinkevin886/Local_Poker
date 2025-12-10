from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import random
import threading
import time
import uuid
from poker_utils import evaluate_hand 

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

SUITS = ['S', 'H', 'D', 'C']
RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A']
TURN_TIME_LIMIT = 30  # ★ 設定思考時間 (秒)

class GameState:
    def __init__(self):
        self.players = {} 
        self.seats = [None] * 8
        self.deck = []
        self.community_cards = []
        self.pot = 0 
        self.current_bet = 0 
        self.phase = "WAITING" 
        self.turn_seat = 0
        self.dealer_seat = 0
        self.game_started = False
        self.winner_msg = ""
        
        self.last_aggressor = None 
        self.active_players_count = 0 
        self.min_raise = 0   
        self.big_blind = 20  
        
        # ★ 新增：計時器相關
        self.timer_thread = None
        self.turn_start_time = 0
        self.current_turn_id = None # 用來驗證計時器是否過期

    def reset_round(self):
        self.deck = [f"{r}{s}" for s in SUITS for r in RANKS]
        random.shuffle(self.deck)
        self.community_cards = []
        self.pot = 0
        self.current_bet = 0
        self.phase = "PREFLOP"
        self.winner_msg = ""
        self.min_raise = 0 
        
        for sid, p in self.players.items():
            if p['seat_id'] != -1:
                p['folded'] = False
                p['bet_round'] = 0      
                p['total_wagered'] = 0  
                p['hand'] = [self.deck.pop(), self.deck.pop()]
                p['hand_strength'] = ""

    def get_public_state(self, my_sid):
        players_data = []
        # 計算剩餘時間
        time_left = 0
        if self.game_started and self.turn_start_time > 0:
            elapsed = time.time() - self.turn_start_time
            time_left = max(0, int(TURN_TIME_LIMIT - elapsed))

        for i in range(8):
            sid = self.seats[i]
            if sid:
                p = self.players[sid]
                to_call = self.current_bet - p['bet_round']
                if p['folded'] or p['chips'] == 0: to_call = 0
                
                players_data.append({
                    "seat": i,
                    "name": p['name'],
                    "avatar": p.get('avatar'), 
                    "chips": p['chips'],
                    "bet": p['bet_round'], 
                    "folded": p['folded'],
                    "disconnected": p.get('disconnected', False),
                    "is_turn": (i == self.turn_seat and self.game_started and self.phase != "SHOWDOWN" and "DEALING" not in self.phase), 
                    "to_call": max(0, to_call)
                })
            else:
                players_data.append(None)

        return {
            "phase": self.phase,
            "pot": self.pot,
            "community_cards": self.community_cards,
            "current_bet": self.current_bet, 
            "players": players_data,
            "dealer_seat": self.dealer_seat,
            "winner_msg": self.winner_msg,
            "min_raise_amount": self.current_bet + self.min_raise,
            "time_left": time_left # ★ 傳送剩餘時間給前端
        }

game = GameState()

# ★ 核心：啟動倒數計時器
def start_turn_timer():
    # 產生一個新的回合 ID，防止舊的計時器干擾新回合
    turn_id = str(uuid.uuid4())
    game.current_turn_id = turn_id
    game.turn_start_time = time.time()
    
    def timer_task(tid):
        # 等待指定秒數
        socketio.sleep(TURN_TIME_LIMIT)
        
        # 檢查是否還是同一個回合 (如果玩家提早操作了，tid 就不會匹配，這行就不執行)
        if game.current_turn_id == tid and game.game_started:
            with app.app_context():
                handle_timeout(tid)

    # 使用 socketio 的背景任務
    socketio.start_background_task(timer_task, turn_id)

# ★ 核心：處理超時棄牌
def handle_timeout(tid):
    # 再次確認狀態
    if game.current_turn_id != tid: return
    
    current_sid = game.seats[game.turn_seat]
    if current_sid and current_sid in game.players:
        player = game.players[current_sid]
        
        if not player['folded']:
            print(f"[系統] {player['name']} 超時，自動棄牌。")
            broadcast_system_msg(f"⏳ {player['name']} 超時棄牌！")
            
            # 執行棄牌邏輯
            player['folded'] = True
            check_round_progress() # 進到下一位

# 輔助函式
def broadcast_system_msg(msg):
    socketio.emit('new_chat', {'name': 'SYSTEM', 'msg': msg})

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('join_game')
def handle_join(data):
    name = data.get('nickname')
    avatar = data.get('avatar') 
    sid = request.sid
    
    if sid in game.players and game.players[sid]['seat_id'] != -1:
        return

    seat_index = -1
    for i in range(8):
        if game.seats[i] is None:
            seat_index = i
            game.seats[i] = sid
            break
    
    is_mid_game = game.game_started
            
    game.players[sid] = {
        "name": name, 
        "avatar": avatar, 
        "chips": 1000, 
        "hand": [], 
        "folded": is_mid_game, 
        "bet_round": 0, 
        "total_wagered": 0, 
        "seat_id": seat_index,
        "disconnected": False
    }
    
    if seat_index == -1:
        emit('error_msg', {'msg': '房間已滿，進入觀戰模式'})
    else:
        emit('player_joined', {'seat': seat_index, 'name': name}, broadcast=True)
        broadcast_system_msg(f"{name} 加入了遊戲！")
        if is_mid_game:
            emit('error_msg', {'msg': '遊戲進行中，請等待下一局開始'}, room=sid)
    
    broadcast_state()

@socketio.on('send_chat')
def handle_chat(data):
    sid = request.sid
    msg = data.get('msg')
    if sid in game.players and msg:
        player = game.players[sid]
        msg_id = str(uuid.uuid4())
        emit('new_chat', {
            'id': msg_id, 
            'name': player['name'], 
            'avatar': player.get('avatar'), 
            'msg': msg,
            'reactions': {} 
        }, broadcast=True)

@socketio.on('send_reaction')
def handle_reaction(data):
    msg_id = data.get('msg_id')
    emoji = data.get('emoji')
    if msg_id and emoji:
        emit('update_reaction', {
            'msg_id': msg_id,
            'emoji': emoji,
            'from_user': request.sid 
        }, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in game.players:
        p = game.players[sid]
        seat = p['seat_id']
        name = p['name']
        
        p['disconnected'] = True
        p['folded'] = True
        
        if seat != -1:
            if game.game_started and game.phase != "SHOWDOWN" and game.phase != "WAITING":
                print(f"[系統] {name} 斷線，已標記為棄牌。") 
                check_round_progress()
            else:
                game.seats[seat] = None
                p['seat_id'] = -1
        
        broadcast_state()

@socketio.on('start_game')
def handle_start():
    # 1. 遊戲進行中防呆
    if game.game_started and game.phase not in ["WAITING", "SHOWDOWN"]:
        return

    # 2. 清理斷線玩家 (保持不變)
    for i in range(8):
        sid = game.seats[i]
        if sid:
            if game.players[sid].get('disconnected'):
                game.seats[i] = None
                game.players[sid]['seat_id'] = -1

    # 3. 取得有效座位列表 (例如: [0, 1, 4, 6])
    active_seats = [i for i, s in enumerate(game.seats) if s is not None]
    
    if len(active_seats) < 2: 
        game.winner_msg = "人數不足 (至少2人)，無法開始"
        broadcast_state()
        return

    game.game_started = True
    game.reset_round()
    
    # ★★★ 核心修正：正確移動莊家 (跳過空位) ★★★
    # 如果這是第一局 (current_dealer 可能不在 active_seats 中)，隨機或選第一個
    if game.dealer_seat not in active_seats:
        game.dealer_seat = active_seats[0]
    else:
        # 找到當前莊家在 active_seats 列表中的索引
        current_idx = active_seats.index(game.dealer_seat)
        # 移動到下一個索引 (循環)
        next_idx = (current_idx + 1) % len(active_seats)
        game.dealer_seat = active_seats[next_idx]

    # --- 以下盲注分配邏輯保持不變 ---
    
    # 重新計算 dealer_idx (因為 dealer_seat 剛換了)
    dealer_idx = active_seats.index(game.dealer_seat)
    
    # 標準規則：多人局 Dealer 下一家是小盲
    # Heads-up (2人) 特例：Dealer 是小盲
    if len(active_seats) == 2:
        sb_seat = game.dealer_seat
        bb_seat = active_seats[(dealer_idx + 1) % len(active_seats)]
        utg_seat = sb_seat # Heads-up 翻牌前小盲先動
    else:
        sb_seat = active_seats[(dealer_idx + 1) % len(active_seats)]
        bb_seat = active_seats[(dealer_idx + 2) % len(active_seats)]
        utg_seat = active_seats[(dealer_idx + 3) % len(active_seats)]

    sb_player = game.players[game.seats[sb_seat]]
    bb_player = game.players[game.seats[bb_seat]]
    
    sb_val = 10
    bb_val = 20
    game.big_blind = bb_val 
    game.min_raise = bb_val 

    # 扣款邏輯 (保持不變)
    sb_real = min(sb_val, sb_player['chips'])
    sb_player['chips'] -= sb_real
    sb_player['bet_round'] = sb_real
    sb_player['total_wagered'] += sb_real 
    
    bb_real = min(bb_val, bb_player['chips'])
    bb_player['chips'] -= bb_real
    bb_player['bet_round'] = bb_real
    bb_player['total_wagered'] += bb_real 
    
    game.pot = sb_real + bb_real
    game.current_bet = bb_val
    
    game.last_aggressor = bb_seat 
    game.turn_seat = utg_seat
    
    # 啟動計時
    start_turn_timer() 

    broadcast_state()
    for sid, p in game.players.items():
        if p['seat_id'] != -1:
            socketio.emit('my_hand', {'hand': p['hand']}, room=sid)

@socketio.on('action')
def handle_action(data):
    sid = request.sid
    if sid not in game.players: return
    p = game.players[sid]
    seat = p['seat_id']
    
    if seat == -1 or seat != game.turn_seat or "DEALING" in game.phase: return

    act = data['type']
    
    # ★ 玩家有動作，重置/停止當前計時 (這會在 check_round_progress 中重新啟動新的)
    game.current_turn_id = None 
    
    if act == 'fold':
        p['folded'] = True
        broadcast_system_msg(f"{p['name']} 棄牌 (Fold)") 
    
    elif act == 'call':
        amount_needed = game.current_bet - p['bet_round']
        if p['chips'] >= amount_needed:
            p['chips'] -= amount_needed
            p['bet_round'] += amount_needed
            p['total_wagered'] += amount_needed 
            game.pot += amount_needed
            if amount_needed == 0:
                broadcast_system_msg(f"{p['name']} 過牌 (Check)") 
            else:
                broadcast_system_msg(f"{p['name']} 跟注 (Call)") 
        else:
            actual_bet = p['chips']
            p['bet_round'] += actual_bet
            p['total_wagered'] += actual_bet 
            game.pot += actual_bet
            p['chips'] = 0
            broadcast_system_msg(f"{p['name']} All-in!") 

    elif act == 'raise':
        raise_total = int(data.get('amount'))
        
        max_capacity = p['chips'] + p['bet_round']
        if raise_total >= max_capacity:
            raise_total = max_capacity
            is_all_in = True
        else:
            is_all_in = False
            
        added = raise_total - p['bet_round'] 
        
        if raise_total <= game.current_bet:
            p['chips'] = 0 
            p['bet_round'] = raise_total
            p['total_wagered'] += added 
            game.pot += added
            broadcast_system_msg(f"{p['name']} All-in (Call)!") 
        else:
            bet_diff = raise_total - game.current_bet 
            if bet_diff >= game.min_raise or is_all_in:
                p['chips'] -= added
                p['bet_round'] = raise_total
                p['total_wagered'] += added 
                game.pot += added
                if bet_diff > game.min_raise:
                    game.min_raise = bet_diff
                game.current_bet = raise_total
                game.last_aggressor = seat 
                broadcast_system_msg(f"{p['name']} 加注到 {raise_total}") 
            else:
                return 

    check_round_progress()

def check_round_progress():
    active_sids = [s for s in game.seats if s and not game.players[s]['folded']]
    
    if len(active_sids) == 1:
        winner_sid = active_sids[0]
        msg = f"{game.players[winner_sid]['name']} 獲勝! (其他人棄牌)"
        game.winner_msg = msg
        broadcast_system_msg(msg) 
        
        game.players[winner_sid]['chips'] += game.pot
        game.phase = "SHOWDOWN"
        game.current_turn_id = None # 停止計時
        resolve_bankruptcy()
        broadcast_state()
        return
    
    if len(active_sids) == 0:
        game.phase = "WAITING"
        game.game_started = False
        game.current_turn_id = None # 停止計時
        broadcast_state()
        return

    all_matched = True
    for sid in active_sids:
        p = game.players[sid]
        if p['chips'] > 0 and p['bet_round'] != game.current_bet:
            all_matched = False
            break
            
    next_seat = (game.turn_seat + 1) % 8
    while game.seats[next_seat] is None or game.players[game.seats[next_seat]]['folded']:
        next_seat = (next_seat + 1) % 8
        if next_seat == game.turn_seat: break

    active_with_chips = [s for s in active_sids if game.players[s]['chips'] > 0]
    
    phase_complete = False
    
    if len(active_with_chips) == 0:
        phase_complete = True
    elif all_matched:
        p_next = game.players[game.seats[next_seat]]
        aggressor_sid = game.seats[game.last_aggressor]
        aggressor_gone = (aggressor_sid is None) or game.players[aggressor_sid]['folded']
        
        if aggressor_gone:
            phase_complete = True
        elif next_seat == game.last_aggressor:
            phase_complete = True
        elif p_next['bet_round'] == game.current_bet:
             if game.phase == "PREFLOP" and p_next['bet_round'] == game.big_blind and game.current_bet == game.big_blind and next_seat == game.last_aggressor:
                 phase_complete = False 
             elif next_seat == game.last_aggressor:
                 phase_complete = True

    if all_matched and (phase_complete or len(active_with_chips) == 0):
        next_phase()
    else:
        while game.seats[next_seat] is None or game.players[game.seats[next_seat]]['folded'] or game.players[game.seats[next_seat]]['chips'] == 0:
            check_sids = [s for s in game.seats if s and not game.players[s]['folded'] and game.players[s]['chips'] > 0]
            if len(check_sids) == 0:
                next_phase()
                return
            next_seat = (next_seat + 1) % 8
            if next_seat == game.turn_seat:
                next_phase()
                return

        game.turn_seat = next_seat
        
        # ★ 輪到下一位，啟動計時器
        start_turn_timer()
        
        broadcast_state()

def next_phase():
    # 換階段時停止計時
    game.current_turn_id = None
    socketio.start_background_task(process_phase_transition)

def process_phase_transition():
    for sid in game.players:
        if game.players[sid]['seat_id'] != -1:
            game.players[sid]['bet_round'] = 0
    game.current_bet = 0
    game.min_raise = game.big_blind
    
    game.phase = f"DEALING..." 
    broadcast_state()
    
    socketio.sleep(1.5)
    
    current_cards_count = len(game.community_cards)
    
    if current_cards_count == 0:
        game.phase = "FLOP"
        game.community_cards = [game.deck.pop() for _ in range(3)]
    elif current_cards_count == 3:
        game.phase = "TURN"
        game.community_cards.append(game.deck.pop())
    elif current_cards_count == 4:
        game.phase = "RIVER"
        game.community_cards.append(game.deck.pop())
    elif current_cards_count >= 5:
        game.phase = "SHOWDOWN"
        resolve_winner()
        return 

    broadcast_state()

    active_seat_indices = [i for i, s in enumerate(game.seats) if s is not None and not game.players[s]['folded']]
    players_with_chips = [i for i in active_seat_indices if game.players[game.seats[i]]['chips'] > 0]
    
    if len(players_with_chips) > 0:
        start_node = -1
        for seat_idx in active_seat_indices:
            if seat_idx > game.dealer_seat:
                start_node = seat_idx
                break
        if start_node == -1: start_node = active_seat_indices[0]
        
        game.turn_seat = start_node
        game.last_aggressor = start_node
        
        # ★ 發牌結束，輪到下一位，啟動計時
        start_turn_timer()
        
        broadcast_state()
        
    else:
        socketio.sleep(1.5)
        process_phase_transition()

def resolve_winner():
    game.current_turn_id = None # 結算時停止計時
    all_bets = {}
    active_sids = [] 
    
    for sid, p in game.players.items():
        if not p['folded']:
            all_bets[sid] = p['total_wagered']
            active_sids.append(sid)
        elif p['total_wagered'] > 0:
            all_bets[sid] = p['total_wagered']

    result_text = "【攤牌結果】\n"
    player_scores = {}
    
    for sid in active_sids:
        p = game.players[sid]
        score_tuple = evaluate_hand(p['hand'], game.community_cards)
        hand_types = ["高牌", "一對", "兩對", "三條", "順子", "同花", "葫蘆", "四條", "同花順"]
        p_type = hand_types[score_tuple[0]]
        result_text += f"{p['name']}: {p_type}\n"
        player_scores[sid] = score_tuple

    sorted_bets = sorted(list(set([v for v in all_bets.values() if v > 0])))
    pots = [] 
    
    prev_bet = 0
    for bet_level in sorted_bets:
        marginal_bet = bet_level - prev_bet
        pot_amount = 0
        eligible_players = []
        
        for sid, amount in all_bets.items():
            if amount >= bet_level:
                pot_amount += marginal_bet
                if sid in active_sids:
                    eligible_players.append(sid)
            elif amount > prev_bet:
                diff = amount - prev_bet
                pot_amount += diff
        
        if pot_amount > 0:
            pots.append({'amount': pot_amount, 'eligible': eligible_players})
        prev_bet = bet_level

    winnings = {sid: 0 for sid in game.players}
    
    for pot in pots:
        if not pot['eligible']: continue
        best_score = (-1, [])
        winners = []
        for sid in pot['eligible']:
            score = player_scores[sid]
            if score > best_score:
                best_score = score
                winners = [sid]
            elif score == best_score:
                winners.append(sid)
        
        share = pot['amount'] // len(winners)
        remainder = pot['amount'] % len(winners)
        for idx, sid in enumerate(winners):
            win_amt = share + (1 if idx < remainder else 0)
            winnings[sid] += win_amt
    
    winner_names = []
    for sid, amount in winnings.items():
        if amount > 0:
            game.players[sid]['chips'] += amount
            winner_names.append(f"{game.players[sid]['name']}(+${amount})")

    win_str = f"贏家: {', '.join(winner_names)} 贏得 ${game.pot}"
    game.winner_msg = f"{result_text}\n{win_str}"
    broadcast_system_msg(win_str) 
    
    resolve_bankruptcy()

    broadcast_state()

def resolve_bankruptcy():
    bankrupt_names = []
    current_seats = list(game.seats)
    for i in range(8):
        sid = current_seats[i]
        if sid:
            p = game.players[sid]
            if (p['chips'] <= 0 or p.get('disconnected')) and p['seat_id'] != -1:
                game.seats[i] = None
                p['seat_id'] = -1
                reason = "破產" if p['chips'] <= 0 else "斷線"
                bankrupt_names.append(f"{p['name']}({reason})")
                
    if bankrupt_names:
        msg = f"{', '.join(bankrupt_names)} 已離開座位。"
        game.winner_msg += f"\n\n⚠ {msg}"
        broadcast_system_msg(msg) 

def broadcast_state():
    for sid in game.players:
        socketio.emit('state_update', game.get_public_state(sid), room=sid)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)