# ===============================
# file: PApp.py
# version : 5.0.0
# ===============================
# python PApp.py
# 밑에 상수를 고쳐서 사용하시요.

from __future__ import annotations
import os
import math
import time
import sys
import argparse
from typing import Any
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from auth import KiwoomAuth #요건 인증 
from kiwoom_client import KiwoomClient #요건 관련 함수
from tools import * #요건 공통 함수

start_time: str = "00:00" # 00:00 일 경우 바로 시작

#전체 잔고 매도 주문 시도 시간
sell_all_time1: str = "15:25"

lim_price: int = 150000 # 비싼 건 넘기자고 

int_ea: int = 10            #    ap.add_argument("--ea", type=int, required=True, help="대상 종목수 (잔액 자동 사용)")
float_tp: float = 4.0       #    ap.add_argument("--tp", type=float, required=True, help="익절 % (매수가 대비)")
float_sl: float = 2.0       #    ap.add_argument("--sl", type=float, required=True, help="손절 % (매수가 대비)")    
float_poll: float = 1       #    ap.add_argument("--poll", type=float, default=1.0, help="체결 폴링 간격(초)")
float_timeout: float = 30   #    ap.add_argument("--timeout", type=int, default=30, help="매수 체결 대기 타임아웃(초)")        
bool_check: bool = False     #    ap.add_argument("--check", action="store_true", help="있으면 대상 종목확인 / 없으면 실행")

b_Tprint: bool = False # 요건 tprint 도 출력되도록 설정
b_Test: bool = False # 요건 TEST 모드 장마감 후 에도 진행 test 설정

b_JMKEY: bool = False #True # JM 계좌 사용
b_JMMode: bool = False #True # 매매 없이 JM 을 위해 종목선정까지만 동작하도록

b_MeMe: bool = True #False #True # 매매 대상을 표시 해줌

int_resol_code: int = 10 #예비로 더 읽어 올 종목수
int_pick_code: int = 2 #1:JM 2:CY1 3:CY2

#예약 기다리는 함수
def wait_until(hhmm: str) -> None:

    if(hhmm == "00:00"):
        return

    """현재 시간을 1줄, 예약 시간을 그 아래 1줄로 표시.
    현재 시간 줄만 매초 갱신되며 화면이 스크롤되지 않습니다.
    예) "09:05" — 오늘 시간이 지났으면 내일 09:05로 예약.
    """
    _enable_ansi_on_windows()

    try:
        hh, mm = map(int, hhmm.split(":"))
    except Exception:
        raise SystemExit("--at 인자는 HH:MM 형식이어야 합니다. 예: --at 09:05")

    now = datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)

    # 최초 2줄 출력 (현재/예약)    
    print(f"예약시간 {target.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"현재시각 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        while True:
            now = datetime.now()
            if now >= target:
                # 현재 시각 줄 갱신 후 종료
                sys.stdout.write("[1A[2K")  # 한 줄 위로 + 줄 지우기
                sys.stdout.write(f"현재시각 {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
                sys.stdout.flush()
                print("시간 도달! 작업을 시작합니다.")
                break

            # 현재 시각 줄만 갱신 (커서를 한 줄 위로 올려 지우고 다시 출력)
            sys.stdout.write("[1A[2K")  # move up 1, clear line
            sys.stdout.write(f"현재시각 {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
            sys.stdout.flush()
            # 커서는 자동으로 '예약시간' 줄로 내려가 있음
            time.sleep(1)
    except KeyboardInterrupt:
        print("사용자 중단(Ctrl+C)")
        sys.exit(1)


def main():    
    
    #로컬로 인식하는 오류가 있어!
    global start_time
    global sell_all_time1    
    global lim_price
    global int_ea
    global float_tp
    global float_sl
    global float_poll
    global float_timeout
    global bool_check
    global b_Tprint
    global b_Test
    global b_JMKEY
    global b_JMMode
    global b_MeMe
    global int_resol_code
    global int_pick_code

    set_test_mode(b_Tprint)  # <- b_Test tprint 사용할건가
    print(f"TEST Mode - {b_Test} - [MAIN] 시작합니다.") # b_Test = True 에만 출력됨

#    ap = argparse.ArgumentParser(description="Kiwoom REST — DecaStar 실행기")
#    ap.add_argument("--ea", type=int, required=True, help="대상 종목수 (잔액 자동 사용)")
#    ap.add_argument("--tp", type=float, required=True, help="익절 % (매수가 대비)")
#    ap.add_argument("--sl", type=float, required=True, help="손절 % (매수가 대비)")    
#    ap.add_argument("--poll", type=float, default=1.0, help="체결 폴링 간격(초)")
#    ap.add_argument("--timeout", type=int, default=30, help="매수 체결 대기 타임아웃(초)")        
#    ap.add_argument("--check", action="store_true", help="있으면 대상 종목확인 / 없으면 실행")
#    args = ap.parse_args()

    # 구성 읽기 (환경변수에서 키/계좌)
    BaseURL = os.getenv("KIWOOM_URL", "https://mockapi.kiwoom.com")
    
    if(b_JMKEY == True): 
        app_key = os.getenv("KIWOOM_APPKEY", "akK1r91hQ51_NfENx7BCfIk4YVyDG1NTqIEXgdi5mII")
        app_secret = os.getenv("KIWOOM_SECRETKEY", "Lu9byXdkRDG7lo5VitPpP83T9NaoSR_X0XLspqIMW5s")
        print("account : jm.lee...# jake.lee #만료일 2026-01-10")
    else:        
        app_key = os.getenv("KIWOOM_APP_KEY", "NTxi_Z9RZJ69MpW79ALrHKB6aUHp1O51gD1Oz3HCZfk")
        app_secret = os.getenv("KIWOOM_APP_SECRET", "G0XgpAdbuW5CxmemgCb_OC_FrKEG2fBLnsj3kKQsRs8")
        print("account : cyKim...#81126449 25-10-10 ~ 26-01-08 김창연 1000만원 #")
        
    auth = KiwoomAuth(app_key, app_secret, BaseURL)    
    time.sleep(1)    
    client = KiwoomClient(access_token=auth._access_token, is_paper=True) #is_paper 실전에서는 False로 변경 할 것
    time.sleep(1)

    #예약시간기다리기    
    if(b_Test): 
        print(f"[TEST MODE]장시작 예약시간 {start_time} PASS")   
        float_timeout = 1
        int_ea = 3        
    else:
        wait_until(start_time)

    #보유 주식 정리 ( TEST 에서 시작하기전에 비우고 시작하기 위해 )
    balance_info = client.get_my_all_stock()  
    time.sleep(1)  
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]보유 종목 수는 {len(balance_info)} 입니다.")
    
    loop_su = 0    
    while True:
        loop_su = loop_su + 1
        result = client.place_market_sell_all(            
                poll_sec=float_poll,
                timeout_sec=float_timeout,
        )        
        time.sleep(1)
        
        balance_info = client.get_my_all_stock()   
        time.sleep(1)            
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][{loop_su}]보유 종목 수는 {len(balance_info)} 입니다.")

        if(len(balance_info) == 0): 
            break

        for gval in balance_info :            
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][{loop_su}][{gval.get("stk_cd")} / {gval.get("stk_nm")}] / rmnd_qty = {format(_to_abs_int(gval.get("rmnd_qty")),',') } / trde_able_qty = {format(_to_abs_int(gval.get("trde_able_qty")),',')} / cur_prc = {format(_to_abs_int(gval.get("cur_prc")),',')}")            

        if(b_Test == True):
            break
        
        time.sleep(float_timeout)

    cur_entr = client.get_current_entr()  

    target_ea = int_ea
    target_entr = math.floor(cur_entr/target_ea)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]1. 니 계좌에서 구매 가능한 돈 : {format(cur_entr, ',')}원 / 해야 할 종목 수 {target_ea} 개")   
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]2. 1개 종목당 {format(target_entr,',')} 원 실행 예정") 
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]3. 뽑아오는 방법 -> {int_pick_code} 번 (# 1:JM 2:CY1 3:CY2) 실행!") 

    match (int_pick_code):
        case 1:
            #시도 할 code 가져오기 
            #251013@JM
            #251013 1. 1차 검색에서 종목수가 최대수량의 5배가 넘으면 검색 멈춤. 적으면 거래량 낮춰 재검색 하도록 적용
            #251012 1. ETF + ETN 제외, 거래대금 100억 이상, 거래량 20만주 이상
            #251013 2. 체결강도 120 이상
            #251013 3. 시가, 전일 종가, 60일 신고가 기준으로 갭 상승 돌파 제외
            rows = client.get_stocks_code(int_ea + int_resol_code) # 요청 보다 int_resol_code개 더 뽑아 옴     
        case 2:
            rows = client.get_stoke_code(float_tp) # 요청 보다 등락율이 익절 값보다 커야 뽑아 옴
        case 3:
            rows = client.get_stoke_code_yesterday(float_tp) # 요청 보다 등락율이 익절 값보다 커야 뽑아 옴

    
    #code 시장가로 구매하고 구매금 + 익절가 에 예약 매도 넣기
    loop_su = 0
    old_price = []
    go_or_stop = []
    mystock = []    
    
    #row 후보 종목은 일단 다 보여주자
    for stk_cd, stk_nm, resistance, strength in rows:           
        loop_su = loop_su + 1
        print(f"[후보 종목 {loop_su}. : {stk_nm}][{stk_cd}] 기준1 = {resistance} / 기준2 = {strength}")
            
    if(b_JMMode == True):
        return
    
    target_rows: list[tuple[str, str, str, str]] = []   

    loop_su = 0
    for stk_cd, stk_nm, resistance, strength in rows:           
        loop_su = loop_su + 1

        if len(target_rows) >= target_ea:
            break  # 10개 모이면 종료
        else:
            go_or_stop.append(1)
            time.sleep(1)

        store_code = stk_cd

        # 1) 종목코드 현재가 확인        
        now_price = client.get_last_price(store_code)        
        time.sleep(1)
        
        # 2) 구매 가능 수량 
        qty = int(target_entr // now_price)
        if qty < 1:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][대상 종목 {loop_su}. : {stk_nm}][{store_code}] 현재가 {format(now_price,',')} / 구매가능수량 0 이 종목의 매수는 못혀.")
            loop_su = loop_su -1
            continue
        elif now_price > lim_price: #10만원 넘는건 PASS혀
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][대상 종목 {loop_su}. : {stk_nm}][{store_code}] 현재가 {format(now_price,',')} / 가격 리미트가 {format(lim_price,',')}원 임으로  이 종목의 매수는 못혀")            
            loop_su = loop_su -1
            continue
        
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][대상 종목 {loop_su}. : {stk_nm}][{store_code}] 현재가 {format(now_price,',')} / 구매가능수량 {qty}")
        
        # 3) 지정가 매수 후 익절 예약 까지 
        result = client.place_limit_buy_then_oto_takeprofit(            
            stk_cd=store_code,            
            buy_price=now_price, 
            qty=qty,
            take_profit_add=float_tp,
            poll_sec=float_poll,
            timeout_sec=float_timeout,
        )

        #sell_price -> tp_price = 0 이기 때문에 실패로 보고 buy_avg_price 가 None이 아니라면 buy_avg 가 있으면 실제 구매가 발생 취소해야함.
        if(result['sell_price'] != 0 or b_Test == True):            
            if(b_Test == True) :
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] No{loop_su}.종목 [{stk_nm}][{store_code}] / 채결가 {now_price} 익절예약가 {(now_price + (now_price * (float_tp/100)))}  / 주문번호 [{result['buy_ord_no']}] TEST")
                target_rows.append((store_code, stk_nm, now_price, result['sell_ord_no'])) # 조건 통과 → 채택
                old_price.append(now_price)
            else:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] No{loop_su}.종목 [{stk_nm}][{store_code}] / 채결가 {result['buy_avg_price']:,} 익절예약가 {result['sell_price']:,} / 주문번호 [{result['buy_ord_no']}]")
                target_rows.append((store_code, stk_nm, result['buy_avg_price'], result['sell_ord_no'])) # 조건 통과 → 채택
                old_price.append(result['buy_avg_price'])
        else:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] No{loop_su}.종목 [{stk_nm}][{store_code}] - 지정가 매수 실패 종목 PASS / 주문번호 [{result['buy_ord_no']}]")
            ret_val = client.place_sell_order_cancel(result['buy_ord_no'], store_code, 0) 
            time.sleep(1)
            tprint(f"지정가 구매 취소 오더 = {ret_val}")
            #실패 했으면 주문 삭제            
            ret_val = client.place_loss_cut_sell(result['sell_ord_no'], store_code)            
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] No{loop_su}.종목 [{stk_nm}][{store_code}] - 지정가 매수 실패 종목 시장가 청산 주문번호 [{ret_val['sell_ord_no']}]")
            loop_su = loop_su -1
            continue
        
    
    mystock = [] 
    loop_su = 0
    for stk_cd, stk_nm, resistance, strength in target_rows:  # strength 주문번호로 사용
        store_code = stk_cd
        loop_su = loop_su + 1
        cur_p = format(_to_abs_int(resistance),',')            
        mystock.append(store_code)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]target_rows - No{loop_su}. 대상 종목 : [{stk_nm}][{store_code}] / 주문번호 [{strength}] / 평균매수가격 {cur_p}")     

    #손절을 위한 모니터링 시작하기
    print(f"\n+++++++++ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 모니터링 시작\n")

    # 5) 가격 감시 루프 → 전량 손절가 매도
    loopcnt = 0    
    tpcnt = 0 #익절 카운트
    slcnt = 0 #손절 카운트
    uncnt = 0 #모름 카운트

    #첫번째 일괄 매도 시간까지만 해라
    try:
        tz = ZoneInfo("Asia/Seoul")
    except Exception:
        tz = ZoneInfo("ROK")

    base = datetime.now(tz).replace(hour=int(sell_all_time1[:2]), minute=int(sell_all_time1[3:]), second=0, microsecond=0)
    target_dt = base # + timedelta(minutes=-5)

    my_stock_cnt = 0
    
    if(b_Test == True):
        my_stock_cnt = int_ea
    
    while True:        
        now = datetime.now(tz)
        if now >= target_dt and b_Test != True:
            print(f"[{now:%H:%M:%S}] 목표시각 도달 → 모니터링 종료\n")
            break    

        all_zero = all(v == 0 for v in go_or_stop)        
        if (all_zero is True):            
            print(f"--------- [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 모니터링 종료\n")            
            break

        loopcnt = loopcnt + 1
        # 1) 종목코드 해석 & 현재가
        loop_su = 0

        for stk_cd, stk_nm, resistance, strength in target_rows:
            loop_su = loop_su + 1           
            tprint(f"target_ea = {target_ea} / loop_su = {loop_su} / go_or_stop = {go_or_stop[loop_su - 1]}")
            if target_ea < loop_su:
                break            

            if(go_or_stop[loop_su - 1] == 1):
                store_code = stk_cd
                #내 계좌랑 확인하기
                for mcode in mystock :
                    tprint(f"mcode = {mcode} / mystock = {mystock} / store_code = {store_code}")                    
                    if( mcode == store_code):
                        tprint(f"break - mcode = {mcode} / mystock = {mystock} / store_code = {store_code}")                    
                        break
                else:
                    #이미 리스트에서 삭제 되었음으로 삭제
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]모니터링 {loopcnt}회] 대상 종목 {loop_su}.  : [{stk_nm}][{store_code}] 이미 리스트에서 삭제 되었음으로 삭제\n")  
                    uncnt = uncnt + 1 #상태를 모르니 모름 카운트
                    go_or_stop[loop_su - 1] = 0 
                    break

                # 1) 종목코드 현재가 확인
                last = client.get_last_price(store_code)                
                tp = floor_to(old_price[loop_su-1] * (1 + float_tp / 100.0),10)
                sl = floor_to(old_price[loop_su-1] * (1 - float_sl / 100.0),10)

                #TEST 모드에서는 1000원 씩 떨어져..ㅠㅠ  그래야 루프를 TEST 할 수 있어
                if b_Test is True:                    
                    last = floor_to(tp - (loopcnt * 1000),10)

                #프린트용으로 , 넣고 보여주자
                p_last = format(_to_abs_int(last),',') 
                p_old_p = format(_to_abs_int(old_price[loop_su-1]),',')  
                p_tp = format(_to_abs_int(tp),',')
                p_sl = format(_to_abs_int(sl),',') 

                #print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] No{loop_su}.종목 [{store_code}] : [{stk_nm}] ")
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]모니터링 {loopcnt}회] 대상 종목 {loop_su}.  : [{stk_nm}][{store_code}] 지금 가격: {p_last} / 구매 금액 {p_old_p} 익절 : {p_tp} 까지 {int(tp-last)} 손절 : {p_sl} 까지 {int(sl-last)}") 
                if last == 0 :
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]대상 종목 {loop_su}. : [{stk_nm}][{store_code}] 가격 읽기 오류 [모니터링 {loopcnt}회]\n")
                    continue

                elif last >= tp or last <= sl:
                    if last >= tp :
                        tpcnt = tpcnt + 1
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]대상 종목 {loop_su}. : [{stk_nm}][{store_code}] 목표가 도달({p_last} ≥ {p_tp}) → 전량 시장가 익절 매도 / 보유 종목수 {my_stock_cnt}\n")                        
                        go_or_stop[loop_su - 1] = 0   

                    else :                        
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]대상 종목 {loop_su}. : [{stk_nm}][{store_code}] 목표가 도달({p_last} ≥ {p_tp}) → 전량 시장가 손절 매도 시도 / 보유 종목수 {my_stock_cnt}\n")

                        ret_val = client.place_loss_cut_sell(buy_ord_no = strength, stk_cd = store_code)   
                        
                        if(b_Test == True):
                            my_stock_cnt = my_stock_cnt - 1
                        else:
                            my_stock_cnt = ret_val['stock_cnt']

                        tprint(f"ret_val = {ret_val} / stock_cnt = {ret_val['stock_cnt']} / sell_ord_no = {ret_val['sell_ord_no']}")
                        if ret_val['sell_ord_no'] is None:
                            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]대상 종목 {loop_su}. : [{stk_nm}][{store_code}] 주문 실패 했어요 잔고 확인해봐요! 재 시도 해볼께요 / 보유 종목수 {my_stock_cnt}\n")
                        else:
                            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]대상 종목 {loop_su}. : [{stk_nm}][{store_code}] 매도 주문 완료 모니터링 종료! 주문번호 {ret_val['sell_ord_no']} / 매도수량 {qty} / 보유 종목수 {my_stock_cnt}\n")    
                            slcnt = slcnt + 1
                            go_or_stop[loop_su - 1] = 0   

                #clear_prev_lines(1) # 겹쳐 쓰기 위로       

        # 1) 나의 계좌를 보자 / 계좌에 없으면서 go_or_stop 가 1 이면 0 으로 바꿔서 더이상 모니터링 하지 않도록 해 주자
        balance_info = client.get_my_all_stock()
        time.sleep(1)
        tprint(balance_info)
        my_stock_cnt = len(balance_info)

        mystock = [] 
        for gval in balance_info :     
            mystock.append(gval.get("stk_cd").replace("A", ""))            
            tprint(f"{mystock}")

        tprint(f"M get_my_all_stock -> {my_stock_cnt}")
        if(my_stock_cnt <= 0):
            break        

        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]모니터링 {loopcnt}회] 완료. 모니터링 종목 수 {my_stock_cnt} \n")

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]매매 루프를 다 돌았다. \n전체 {target_ea} 개 = [익절 {tpcnt}개] + [손절 {slcnt}개] + [모름 {uncnt}]개 + [모니터링중 {my_stock_cnt}]\n")

    #모니터링중인 종목들 정리
    if(my_stock_cnt > 0):
        loop_su = 0    
        while True:
            loop_su = loop_su + 1
            result = client.place_market_sell_all(            
                    poll_sec=float_poll,
                    timeout_sec=float_timeout,
            )        
            time.sleep(1)
            
            balance_info = client.get_my_all_stock()   
            time.sleep(1)            
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][{loop_su}]보유 종목 수는 {len(balance_info)} 입니다.")

            if(len(balance_info) == 0): 
                break

            for gval in balance_info :            
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][{loop_su}][{gval.get("stk_cd")} / {gval.get("stk_nm")}] / rmnd_qty = {format(_to_abs_int(gval.get("rmnd_qty")),',') } / trde_able_qty = {format(_to_abs_int(gval.get("trde_able_qty")),',')} / cur_prc = {format(_to_abs_int(gval.get("cur_prc")),',')}")            

            if(b_Test == True):
                break
            time.sleep(float_timeout)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]몽땅완료!")       

if __name__ == "__main__":
    main()