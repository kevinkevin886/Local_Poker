from collections import Counter

# 牌面權重
RANK_ORDER = "23456789TJQKA"
SUIT_ORDER = "SHDC"

def get_rank_val(card):
    # 'T' -> 10, 'A' -> 14
    if not card: return 0 # 防呆
    r = card[0]
    return RANK_ORDER.index(r) + 2

def get_suit(card):
    if not card: return ''
    return card[1]

def evaluate_hand(hand_cards, community_cards):
    """
    回傳格式: (牌型等級, [關鍵牌大小列表])
    等級: 8=同花順, 7=四條, 6=葫蘆, 5=同花, 4=順子, 3=三條, 2=兩對, 1=對子, 0=高牌
    """
    all_cards = hand_cards + community_cards
    
    # 如果牌數不足，直接回傳高牌 (避免崩潰)
    if not all_cards:
        return (0, [])

    ranks = sorted([get_rank_val(c) for c in all_cards], reverse=True)
    suits = [get_suit(c) for c in all_cards]
    rank_counts = Counter(ranks)
    suit_counts = Counter(suits)
    
    is_flush = False
    flush_suit = None
    for s, c in suit_counts.items():
        if s and c >= 5: # 確保 suit 不是空字串
            is_flush = True
            flush_suit = s
            break
            
    # 檢查順子
    sorted_unique_ranks = sorted(list(set(ranks)), reverse=True)
    straight_high = -1
    if len(sorted_unique_ranks) >= 5:
        for i in range(len(sorted_unique_ranks) - 4):
            subset = sorted_unique_ranks[i:i+5]
            if subset[0] - subset[4] == 4:
                straight_high = subset[0]
                break
        # 特殊順子 A, 5, 4, 3, 2
        if straight_high == -1 and set([14, 5, 4, 3, 2]).issubset(set(ranks)):
            straight_high = 5

    # 如果是同花
    if is_flush:
        flush_ranks = sorted([get_rank_val(c) for c in all_cards if get_suit(c) == flush_suit], reverse=True)[:5]
        # 檢查同花順
        flush_unique = sorted(list(set(flush_ranks)), reverse=True)
        if len(flush_unique) >= 5:
            for i in range(len(flush_unique) - 4):
                if flush_unique[i] - flush_unique[4] == 4:
                    return (8, [flush_unique[0]]) # 同花順
            if set([14, 5, 4, 3, 2]).issubset(set(flush_ranks)):
                 return (8, [5]) # A-5 同花順
        return (5, flush_ranks)

    if straight_high != -1:
        return (4, [straight_high])

    # 檢查四條、葫蘆、三條、兩對、對子
    counts_items = sorted(rank_counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
    
    # 確保 counts_items 至少有足夠的元素，避免 index error
    if not counts_items:
        return (0, [])

    if counts_items[0][1] == 4:
        # 四條
        kickers = [r for r in ranks if r != counts_items[0][0]]
        kicker = kickers[0] if kickers else 0
        return (7, [counts_items[0][0], kicker])
        
    if len(counts_items) >= 2 and counts_items[0][1] == 3 and counts_items[1][1] >= 2:
        # 葫蘆
        return (6, [counts_items[0][0], counts_items[1][0]])
        
    if counts_items[0][1] == 3:
        # 三條
        kickers = [r for r in ranks if r != counts_items[0][0]]
        # 取前兩張踢腳，不足補0
        k1 = kickers[0] if len(kickers) > 0 else 0
        k2 = kickers[1] if len(kickers) > 1 else 0
        return (3, [counts_items[0][0], k1, k2])
        
    if len(counts_items) >= 2 and counts_items[0][1] == 2 and counts_items[1][1] == 2:
        # 兩對 ★ 這裡就是原本報錯的地方
        kickers = [r for r in ranks if r != counts_items[0][0] and r != counts_items[1][0]]
        # ★ 修正：如果沒有踢腳 (總共只有4張牌)，回傳 0，不要崩潰
        kicker = kickers[0] if kickers else 0
        return (2, [counts_items[0][0], counts_items[1][0], kicker])
        
    if counts_items[0][1] == 2:
        # 一對
        kickers = [r for r in ranks if r != counts_items[0][0]]
        # 取前三張踢腳
        final_kickers = []
        for i in range(3):
            final_kickers.append(kickers[i] if i < len(kickers) else 0)
        return (1, [counts_items[0][0]] + final_kickers)
        
    # 高牌
    return (0, ranks[:5])