# ===============================
# file: trun.py
# version : 1.0.0
# ===============================
# python trun.py
# TEST 용 파일

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

start_time: str = "09:24"

#전체 잔고 매도 주문 시도 시간
sell_all_time1: str = "11:00"
sell_all_time2: str = "14:00"
sell_all_time3: str = "15:20"

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
    global sell_all_time2
    global sell_all_time3
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

    balance_info = client.get_my_all_stock()
    time.sleep(1)
    tprint(balance_info)
    print(f"보유 종목 수는 {len(balance_info)} 입니다.")
    
    loop_su = 0
    while True:        
        loop_su = loop_su + 1
        result = client.place_market_sell_all(            
                poll_sec=float_poll,
                timeout_sec=float_timeout,
        )        
        print(f"[{loop_su}]place_market_sell_all3 - {result}")

        balance_info = client.get_my_all_stock()
        time.sleep(1)
        print(balance_info)
        print(f"[{loop_su}]보유 종목 수는 {len(balance_info)} 입니다.")

        for gval in balance_info :
            print(f"[{loop_su}]보유 종목 수는 {len(balance_info)} 입니다.")
            print(f"[{loop_su}]{gval.get("stk_cd")} / {gval.get("stk_nm")} / {gval.get("rmnd_qty")} / {gval.get("trde_able_qty")} / {gval.get("cur_prc")}")            

        if(len(balance_info) == 0): 
            break

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]몽땅완료!")

if __name__ == "__main__":
    main()