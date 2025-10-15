# ===============================
# file: PApp.py
# version : 5.0.0
# ===============================
# python PApp.py --ea 10 --tp 4.0 --sl 2.0 --poll 1 --timeout 30
# 이름 바꿀까?

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

b_Tprint: bool = False # 요건 tprint 도 출력되도록 설정
b_Test: bool = False # 요건 TEST 모드 장마감 후 에도 진행 test 설정

b_JMMode: bool = False #True # 오건 매매 없이 JM 을 위해 종목선정까지만 동작하도록
b_MeMe: bool = True #False #True # 오건 매매 대상을 표시 해줌

int_resol_code: int = 5 #예비로 더 읽어 올 종목수

lim_price: int = 150000 # 비싼 건 넘기자고 
start_time: str = "09:11"
#전체 잔고 매도 주문 시도 시간
sell_all_time1: str = "11:00"
sell_all_time2: str = "14:00"
sell_all_time3: str = "15:20"

#예약 기다리는 함수
def wait_until(hhmm: str) -> None:
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
    set_test_mode(b_Tprint)  # <- b_Test tprint 사용할건가
    print(f"TEST Mode - {b_Test} - [MAIN] 시작합니다.") # b_Test = True 에만 출력됨

    ap = argparse.ArgumentParser(description="Kiwoom REST — DecaStar 실행기")
    ap.add_argument("--ea", type=int, required=True, help="대상 종목수 (잔액 자동 사용)")
    ap.add_argument("--tp", type=float, required=True, help="익절 % (매수가 대비)")
    ap.add_argument("--sl", type=float, required=True, help="손절 % (매수가 대비)")    
    ap.add_argument("--poll", type=float, default=1.0, help="체결 폴링 간격(초)")
    ap.add_argument("--timeout", type=int, default=30, help="매수 체결 대기 타임아웃(초)")        
    ap.add_argument("--check", action="store_true", help="있으면 대상 종목확인 / 없으면 실행")
    args = ap.parse_args()

    # 구성 읽기 (환경변수에서 키/계좌)
    #81126449 25-10-10~26-01-08 김창연 1000만원
    BaseURL = os.getenv("KIWOOM_URL", "https://mockapi.kiwoom.com")
    app_key = os.getenv("KIWOOM_APP_KEY", "NTxi_Z9RZJ69MpW79ALrHKB6aUHp1O51gD1Oz3HCZfk")
    app_secret = os.getenv("KIWOOM_APP_SECRET", "G0XgpAdbuW5CxmemgCb_OC_FrKEG2fBLnsj3kKQsRs8")

    # jake.lee #만료일 2026-01-10
    #app_key = os.getenv("KIWOOM_APPKEY", "akK1r91hQ51_NfENx7BCfIk4YVyDG1NTqIEXgdi5mII")
    #app_secret = os.getenv("KIWOOM_SECRETKEY", "Lu9byXdkRDG7lo5VitPpP83T9NaoSR_X0XLspqIMW5s")
    #print("account : jm.lee...")

        
    auth = KiwoomAuth(app_key, app_secret, BaseURL)    
    client = KiwoomClient(access_token=auth._access_token, is_paper=True) #is_paper 실전에서는 False로 변경 할 것

    #cur_entr = api.get_current_entr(auth._access_token)  
    cur_entr = client.get_current_entr()  

    target_ea = args.ea
    target_entr = math.floor(cur_entr/target_ea)
    print(f"1. 니 계좌에서 구매 가능한 돈 : {format(cur_entr, ',')}원 / 해야 할 종목 수 {target_ea} 개")   
    print(f"2. 1개 종목당 {format(target_entr,',')} 원 실행 예정") 

    #예약시간기다리기    
    if(b_Test): 
        print(f"[TEST MODE]장시작 예약시간 {start_time} PASS")   
    else:
        wait_until(start_time)

    #시도 할 code 가져오기 
    #251013@JM
    #251013 1. 1차 검색에서 종목수가 최대수량의 5배가 넘으면 검색 멈춤. 적으면 거래량 낮춰 재검색 하도록 적용
    #251012 1. ETF + ETN 제외, 거래대금 100억 이상, 거래량 20만주 이상
    #251013 2. 체결강도 120 이상
    #251013 3. 시가, 전일 종가, 60일 신고가 기준으로 갭 상승 돌파 제외
    rows = client.get_stocks_code(args.ea + int_resol_code) # 요청 보다 int_resol_code개 더 뽑아 옴
    if(b_JMMode == True):
        return

    #code 시장가로 구매하고 구매금 + 익절가 에 예약 매도 넣기
    loop_su = 0
    old_price = []
    go_or_stop = []
    
    target_rows: list[tuple[str, str, str, str]] = []   

    for stk_cd, stk_nm, resistance, strength in rows:           
        loop_su = loop_su + 1

        if len(target_rows) >= target_ea:
            break  # 10개 모이면 종료
        else:
            go_or_stop.append(1)
            time.sleep(1)

        print(f"go_or_stop - {len(go_or_stop)}")

        store_code = stk_cd

        # 1) 종목코드 현재가 확인        
        now_price = client.get_last_price(store_code)
        old_price.append(now_price)
        
        # 2) 구매 가능 수량 
        qty = int(target_entr // now_price)
        if qty < 1:
            print(f"사용금액 {format(target_entr,',')}원 으로 구매 가능 수량이 0이여. 이 종목의 매수는 못혀. (현재가 {format(now_price,',')})")
            loop_su = loop_su -1
            continue
        elif now_price > lim_price: #10만원 넘는건 PASS혀
            print(f"가격 리미트가 {format(lim_price,',')}원 임으로  이 종목의 매수는 못혀. (현재가 {format(now_price,',')})")
            loop_su = loop_su -1
            continue
        
        print(f"[대상 종목 {loop_su}. : {stk_nm}] 현재가 {format(now_price,',')} / 구매가능수량 {qty}")
        
        # 3) 지정가 매수 후 익절 예약 까지 
        result = client.place_limit_buy_then_oto_takeprofit(            
            stk_cd=store_code,            
            buy_price=now_price, 
            qty=qty,
            take_profit_add=args.tp,
            poll_sec=args.poll,
            timeout_sec=args.timeout,
        )

        if(result['buy_ord_no'] != "지정가 매수실패" or b_Test == True):            
            print(f" No{loop_su}.종목 [{store_code}] : [{stk_nm}] / 채결가 {result['buy_avg_price']:,} 익절예약가 {result['sell_price']:,}")
            target_rows.append((store_code, stk_nm, result['buy_avg_price'], result['buy_ord_no'])) # 조건 통과 → 채택
        else:
            print(f" No{loop_su}.종목 [{store_code}] : [{stk_nm}] - 지정가 매수 실패 종목 PASS")
            loop_su = loop_su -1
            continue
        
        #매수 실패 했을경우 어떻게 하징?
        #매수는 성공하고 예약은 실패하면?
        #일단 하면서 생각해보자

        '''
        # 3) 시장가 매수 후 익절 예약 까지        
        result = place_market_buy_then_oto_takeprofit(
            client,
            stk_cd=store_code,            
            buy_price=now_price, #TEST용
            qty=qty,
            take_profit_add=args.tp,
            poll_sec=args.poll,
            timeout_sec=args.timeout,
        )
        '''
    
    if(b_MeMe == True): #Target_rows 를 출력합니다.
        loop_su = 0
        for stk_cd, stk_nm, resistance, strength in target_rows:  # strength 주문번호로 사용
            loop_su = loop_su + 1
            cur_p = format(_to_abs_int(resistance),',')            
            print(f"target_rows - No{loop_su}. 대상 종목 [{stk_cd}] : [{stk_nm}] / 주문번호 [{strength}] / 평균매수가격 {cur_p}")     

    #손절을 위한 모니터링 시작하기
    print(f"+++++++++ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 모니터링 시작")

    # 5) 가격 감시 루프 → 전량 손절가 매도
    loopcnt = 0    
    tpcnt = 0 #익절 카운트
    slcnt = 0 #손절 카운트

    #첫번째 일괄 매도 시간까지만 해라
    try:
        tz = ZoneInfo("Asia/Seoul")
    except Exception:
        tz = ZoneInfo("ROK")

    if(b_Test == True):
        base = datetime.now(tz)
        target_dt = base + timedelta(minutes=5)    
    else:
        # 루프 들어가기 전에 'sell_all_time1 - 5분' 목표시각을 한 번만 계산
        base = datetime.now(tz).replace(hour=int(sell_all_time1[:2]), minute=int(sell_all_time1[3:]), second=0, microsecond=0)
        target_dt = base + timedelta(minutes=-5)

    while True:        
        now = datetime.now(tz)
        if now >= target_dt:
            print(f"[{now:%H:%M:%S}] 목표시각 도달 → 모니터링 종료")
            break
        all_zero = all(v == 0 for v in go_or_stop)        
        if (all_zero is True):            
            print(f"--------- [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 모니터링 종료")            
            break

        loopcnt = loopcnt + 1
        # 1) 종목코드 해석 & 현재가
        loop_su = 0

        for stk_cd, stk_nm, resistance, strength in target_rows:
            loop_su = loop_su + 1           
            if target_ea < loop_su:
                break            

            if(go_or_stop[loop_su - 1] == 1):
                store_code = stk_cd
                # 1) 종목코드 현재가 확인
                last = client.get_last_price(store_code)                
                tp = floor_to(old_price[loop_su-1] * (1 + args.tp / 100.0),10)
                sl = floor_to(old_price[loop_su-1] * (1 - args.sl / 100.0),10)

                #TEST 모드에서는 1000원 씩 떨어져..ㅠㅠ  그래야 루프를 TEST 할 수 있어
                if b_Test is True:                    
                    last = floor_to(tp - (loopcnt * 1000),10)

                #프린트용으로 , 넣고 보여주자
                p_last = format(_to_abs_int(last),',') 
                p_old_p = format(_to_abs_int(old_price[loop_su-1]),',')  
                p_tp = format(_to_abs_int(tp),',')
                p_sl = format(_to_abs_int(sl),',') 

                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] No{loop_su}.종목 [{store_code}] : [{stk_nm}] ")
                print(f"모니터링 {loopcnt}회] 대상 종목 {loop_su}.  : {stk_nm}] 지금 가격: {p_last} / 구매 금액 {p_old_p} 익절 : {p_tp} 손절 : {p_sl}")                
                
                if last == 0 :
                    print(f"대상 종목 {loop_su}. : {stk_nm}]가격 읽기 오류 loop = {loopcnt} 못 넘어가는겨 나간다")
                    continue

                elif last >= tp or last <= sl:
                    if last >= tp :
                        tpcnt = tpcnt + 1
                        print(f"대상 종목 {loop_su}. : {stk_nm}]목표가 도달({p_last} ≥ {p_tp}) → 전량 시장가 익절 매도")                        
                    else :
                        slcnt = slcnt + 1
                        print(f"대상 종목 {loop_su}. : {stk_nm}]목표가 도달({p_last} ≥ {p_tp}) → 전량 시장가 손절 매도")
                    
                    sell_No = client.place_loss_cut_sell(buy_ord_no = strength, stk_cd = store_code)           

                    if sell_No is None:
                        print(f"대상 종목 {loop_su}. : {stk_nm}]주문 실패 했어요 잔고 확인해봐요!! \r\n 종료합니다!")                
                    else:
                        print(f"대상 종목 {loop_su}. : {stk_nm}]매도 완료 종료!\r\n주문번호 {sell_No} / 매도수량 {qty}")    
                    go_or_stop[loop_su - 1] = 0
                    continue #겹쳐 하지 않고 다음으로

                clear_prev_lines(2) # 겹쳐 쓰기 2줄 위로
    
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]매매 루프를 다 돌았다. \n전체 {target_ea} 개 중 [익절 {tpcnt}개] <> [손절 {slcnt}개]")

    #이부분은 나중에 다시 확인하기

    #남은 잔고 종목 일괄 시장가 매도 하기 오전 후
    #예약시간기다리기
    if(b_Test): 
        print(f"[TEST MODE]매도 하기 예약시간 {sell_all_time1} PASS")   
    else:
        wait_until(sell_all_time1)  

    result = client.place_market_sell_all(            
            poll_sec=args.poll,
            timeout_sec=args.timeout,
    )
    print(f"place_market_sell_all1 - {result}")    
          
    #남은 잔고 종목 일괄 시장가 매도 하기2 점심 후
    
    if(b_Test): 
        print(f"[TEST MODE]매도 하기 예약시간 {sell_all_time2} PASS")   
    else:
        wait_until(sell_all_time2)  

    result = client.place_market_sell_all(            
            poll_sec=args.poll,
            timeout_sec=args.timeout,
    )
    print(f"place_market_sell_all2 - {result}")
          
    #남은 잔고 종목 일괄 시장가 매도 하기3 장마감 전
    if(b_Test): 
        print(f"[TEST MODE]매도 하기 예약시간 {sell_all_time3} PASS")   
    else:
        wait_until(sell_all_time3)  

    result = client.place_market_sell_all(            
            poll_sec=args.poll,
            timeout_sec=args.timeout,
    )
    print(f"place_market_sell_all3 - {result}")

    #결과 보여주기
    #print(f"모두 끝났습니다.")
    # 그날 결과 보여주는 함수도 만들어야..
    # 다시 시작하는 루프로 만들던가
    # 뭔가 더 해야 할것 같으나 차차 생각해 보자

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]몽땅완료!")

if __name__ == "__main__":
    main()