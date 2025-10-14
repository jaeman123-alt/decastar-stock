# =====================================
# file: kiwoom_client.py
# =====================================
from __future__ import annotations

import time
import json
import requests
import re

from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from tools import *

BASE_PROD = "https://api.kiwoom.com"
BASE_PAPER = "https://mockapi.kiwoom.com"  # (문서 예시: "KRX만 지원가능")


@dataclass
class KiwoomClient:
    access_token: str
    is_paper: bool = True

    def __post_init__(self):                
        tprint(f"KiwoomClient]시작 모의투자 여부 - {self.is_paper}")
        self.session = requests.Session()
        self.base_url = BASE_PAPER if self.is_paper else BASE_PROD
        self.common_headers = {
            "Content-Type": "application/json;charset=UTF-8",
            # 문서: Header.authorization 에 Bearer 토큰
            "authorization": f"Bearer {self.access_token}",
            "cont-yn": "",
            "next-key": "",
        }

    def _post(self, path: str, api_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        url = self.base_url + path
        headers = {**self.common_headers, "api-id": api_id}
        tprint(url)
        tprint(headers)
        tprint(body)
        resp = self.session.post(url, headers=headers, data=json.dumps(body), timeout=10)

        tprint('Code:', resp.status_code)
        tprint('Header:', json.dumps({key: resp.headers.get(key) for key in ['next-key', 'cont-yn', 'api-id']}, indent=4, ensure_ascii=False))
        tprint('Body:', json.dumps(resp.json(), indent=4, ensure_ascii=False))  # JSON 응답을 파싱하여 출력

        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
        try:
            return resp.json()
        except Exception:
            print(f"Invalid JSON: {resp.text[:200]}")
            #raise RuntimeError(f"Invalid JSON: {resp.text[:200]}")

    # -------------- 시세: 체결정보요청(ka10003) --------------
    def get_tick_info(self, stk_cd: str) -> Dict[str, Any]:
        """/api/dostk/stkinfo — 최근 체결 정보 리스트(cntr_infr). 현재가: item['cur_prc']
        반환값 예: {"cntr_infr": [{"tm":..., "cur_prc": "+53500", ...}, ...], ...}
        """
        body = {"stk_cd": stk_cd}        
        return self._post("/api/dostk/stkinfo", api_id="ka10003", body=body)

    def get_last_price(self, stk_cd: str) -> Optional[int]:
        tcode = stk_cd.replace("A", "") 
        """문자형 가격(+부호/패딩) → 정수 KRW 변환."""
        data = self.get_tick_info(tcode)        
        arr = data.get("cntr_infr") or []
        if not arr:
            return None
        time.sleep(1)        

        cur = arr[0].get("cur_prc")  # ex) "+53500"
        if cur is None:
            return None
        
        digits = _to_abs_int(cur)
        #digits = "".join(ch for ch in str(cur) if ch.isdigit())
        return int(digits) if digits else None
    
    def place_buy_limit(self, stk_cd: str, qty: int, price: int) -> str:
        tcode = stk_cd.replace("A", "") 
        body = {
            "dmst_stex_tp": "KRX",
            "stk_cd": tcode,
            "ord_qty": f"{qty}",
            "ord_uv": f"{price}",
            "trde_tp": "0",  # 보통(지정가)
            "cond_uv": "",
        }
        data = self._post("/api/dostk/ordr", api_id="kt10000", body=body)
        ord_no = data.get("ord_no")                
        tprint (f"place_buy_limit : {ord_no}") 
        if not ord_no:
            #raise RuntimeError(f"매수주문 응답에 주문번호가 없습니다: {data}")
            ord_no = "매수주문 응답에 주문번호가 없습니다:"
        return ord_no
    
    def place_buy_market(self, stk_cd: str, qty: int) -> str:
        tcode = stk_cd.replace("A", "") 
        body = {
            "dmst_stex_tp": "KRX",
            "stk_cd": tcode,
            "ord_qty": f"{qty}",
            "ord_uv": "",
            "trde_tp": "3",  # 시장가
            "cond_uv": "",
        }
        data = self._post("/api/dostk/ordr", api_id="kt10000", body=body)
        ord_no = data.get("ord_no")
        tprint (f"place_buy_market : {ord_no}") 
        if not ord_no:            
            #raise RuntimeError(f"시장가 매수 응답에 주문번호가 없습니다: {data}")
            ord_no = "시장가 매수 응답에 주문번호가 없습니다: {data}"
        return ord_no

    def place_sell_limit(self, stk_cd: str, qty: int, price: int) -> str:
        tcode = stk_cd.replace("A", "") 
        body = {
            "dmst_stex_tp": "KRX",
            "stk_cd": tcode,
            "ord_qty": f"{qty}",
            "ord_uv": f"{price}",
            "trde_tp": "0",  # 보통(지정가)
            "cond_uv": "",
        }
        data = self._post("/api/dostk/ordr", api_id="kt10001", body=body)
        ord_no = data.get("ord_no")
        tprint (f"place_sell_limit : {ord_no}") 
        if not ord_no:
            #raise RuntimeError(f"매도주문 응답에 주문번호가 없습니다: {data}")
            ord_no = "매도주문 응답에 주문번호가 없습니다: {data}"
        return ord_no
    
    def place_sell_market(self, stk_cd: str, qty: int) -> str:
        tcode = stk_cd.replace("A", "") 
        #왜 A가 붙어 있나.. 
        body = {
            "dmst_stex_tp": "KRX",
            "stk_cd": tcode,
            "ord_qty": f"{qty}",
            "ord_uv": "",
            "trde_tp": "3",  # 시장가
            "cond_uv": "",
        }

        data = self._post("/api/dostk/ordr", api_id="kt10001", body=body)
        ord_no = data.get("ord_no")        
        tprint (f"place_sell_market : {ord_no}") 
        if not ord_no:
            #raise RuntimeError(f"매도주문 응답에 주문번호가 없습니다: {data}")
            ord_no = "매도주문 응답에 주문번호가 없습니다:"
        return ord_no
    
    def place_sell_order_cancel(self, orig_ord_no: str, stk_cd: str, qty: int = 0) -> str:
        tcode = stk_cd.replace("A", "") 
        #왜 A가 붙어 있나.. 
        body = {
                "dmst_stex_tp": "KRX", # 국내거래소구분 KRX,NXT,SOR
                "orig_ord_no": orig_ord_no, # 원주문번호
                "stk_cd": tcode, # 종목코드
                "cncl_qty": f"{qty}", # 취소수량 '0' 입력시 잔량 전부 취소
        }

        data = self._post("/api/dostk/ordr", api_id="kt10003", body=body)
        ret_no = data.get("return_code")        
        tprint (f"return_code : {ret_no}") 
        if not ret_no:
            #raise RuntimeError(f"매도주문 응답에 주문번호가 없습니다: {data}")
            ret_no = "매도주문 응답에 주문번호가 없습니다:"
        return ret_no
    
    def get_order_List(self) -> List[Dict[str, Any]]:
        body =   {
                'all_stk_tp': '0', # 전체종목구분 0:전체, 1:종목
                'trde_tp': '1', # 매매구분 0:전체, 1:매도, 2:매수
                'stk_cd': '', # 종목코드 #전체
                'stex_tp': '0', # 거래소구분 0 : 통합, 1 : KRX, 2 : NXT
            }

        data = self._post("/api/dostk/acnt", api_id="ka10075", body=body)
        return data.get("oso") or []        

    # -------------- 주문체결현황: 계좌별주문체결현황요청(kt00009) --------------        
    def query_order_fills(self) -> List[Dict[str, Any]]:
        body = {
            "ord_dt": f"{datetime.now().strftime('%Y%m%d')}",  # 당일 기본 # 주문일자 YYYYMMDD
            "stk_bond_tp": "0",   # 전체 # 주식채권구분 0:전체, 1:주식, 2:채권
            "mrkt_tp": "0",       # 전체 # 시장구분 0:전체, 1:코스피, 2:코스닥, 3:OTCBB, 4:ECN
            "sell_tp": "0",       # 전체 # 매도수구분 0:전체, 1:매도, 2:매수
            "qry_tp": "1",        # 전체 # 조회구분 0:전체, 1:체결
            "stk_cd": "",           # 종목코드 전문 조회할 종목코드
            "fr_ord_no": "",        # 시작주문번호
            "dmst_stex_tp": "KRX",  # 국내거래소구분 %:(전체),KRX:한국거래소,NXT:넥스트트레이드,SOR:최선주문집행
        }
        data = self._post("/api/dostk/acnt", api_id="kt00009", body=body)
        return data.get("acnt_ord_cntr_prst_array") or []

    def get_order_fill_summary(self, ord_no: str) -> Dict[str, Any]:
        """해당 주문번호의 누적 체결/주문수량/평균단가 요약.
        반환: {"ord_qty": int|None, "filled_qty": int, "avg_price": int|None}
        """
        rows = self.query_order_fills()
        ord_qty: Optional[int] = None
        filled_qty = 0
        notional = 0
        for r in rows:
            if str(r.get("ord_no")) != str(ord_no):
                continue
            # 수량/가격은 0패딩 문자열로 올 수 있음 → int 변환
            oq = r.get("ord_qty")
            cq = r.get("cntr_qty")
            uv = r.get("cntr_uv")

            tprint (f"get_order_fill_summary :ord_no[{ord_no}] oq {oq} / cq {cq} / uv {uv}") 

            try:
                if oq is not None:
                    ord_qty = int(str(oq))
                if cq is not None:
                    q = int(str(cq))
                    filled_qty += q
                    if uv is not None:
                        p = int(str(uv))
                        notional += p * q
            except ValueError:
                # 형식 이슈 시 스킵
                pass
        avg_price = int(notional // filled_qty) if filled_qty > 0 and notional > 0 else None
        return {"ord_qty": ord_qty, "filled_qty": filled_qty, "avg_price": avg_price}
    
    #계좌 잔고 요청    
    def get_my_all_stock(self) -> List[Dict[str, Any]]:
        # 잔고 조회 데이터
        body = {
            'qry_tp': '1',  # 조회구분 1:합산
            'dmst_stex_tp': 'KRX',  # 국내거래소구분 KRX
        }
        data = self._post("/api/dostk/acnt", api_id="kt00018", body=body)
        return data.get("acnt_evlt_remn_indv_tot") or []
    
    # 현재 계좌 주문가능현금 
    def get_current_entr(self) -> int:
        # 잔고 조회 데이터
        body = {
            'qry_tp': '2',  # 조회구분 2:일반조회            
        }
        data = self._post("/api/dostk/acnt", api_id="kt00001", body=body)

        ret_val = _to_abs_int(data.get("ord_alow_amt"))
        tprint(f"ord_alow_amt : {ret_val}")
        return ret_val

    # 거래량을 보고 종목을 뽑자
    def get_stoke_code(self, tp) -> list[tuple[str, str, str, str]]:

        body = {
            'mrkt_tp': '000', # 시장구분 000:전체, 001:코스피, 101:코스닥
            'sort_tp': '2', # 정렬구분 1:거래량, 2:거래회전율, 3:거래대금
            'mang_stk_incls': '16', # 관리종목포함 0:관리종목 포함, 1:관리종목 미포함, 3:우선주제외, 11:정리매매종목제외, 4:관리종목, 우선주제외, 5:증100제외, 6:증100마나보기, 13:증60만보기, 12:증50만보기, 7:증40만보기, 8:증30만보기, 9:증20만보기, 14:ETF제외, 15:스팩제외, 16:ETF+ETN제외
            'crd_tp': '0', # 신용구분 0:전체조회, 9:신용융자전체, 1:신용융자A군, 2:신용융자B군, 3:신용융자C군, 4:신용융자D군, 8:신용대주
            'trde_qty_tp': '0', # 거래량구분 0:전체조회, 5:5천주이상, 10:1만주이상, 50:5만주이상, 100:10만주이상, 200:20만주이상, 300:30만주이상, 500:500만주이상, 1000:백만주이상
            'pric_tp': '0', # 가격구분 0:전체조회, 1:1천원미만, 2:1천원이상, 3:1천원~2천원, 4:2천원~5천원, 5:5천원이상, 6:5천원~1만원, 10:1만원미만, 7:1만원이상, 8:5만원이상, 9:10만원이상
            'trde_prica_tp': '0', # 거래대금구분 0:전체조회, 1:1천만원이상, 3:3천만원이상, 4:5천만원이상, 10:1억원이상, 30:3억원이상, 50:5억원이상, 100:10억원이상, 300:30억원이상, 500:50억원이상, 1000:100억원이상, 3000:300억원이상, 5000:500억원이상
            'mrkt_open_tp': '0', # 장운영구분 0:전체조회, 1:장중, 2:장전시간외, 3:장후시간외
            'stex_tp': '3', # 거래소구분 1:KRX, 2:NXT 3.통합
        }
        data = self._post("/api/dostk/rkinfo", api_id="ka10030", body=body)

        ret_val: list[tuple[str,str,str,str]] = []
        
        items = data.get("tdy_trde_qty_upper") or []
        for row in items:
            self.rcode = (row.get("stk_cd") or "").replace("_AL", "") 
            self.rname = row.get("stk_nm")
            self.rprice  = row.get("cur_prc")
            self.rflu  = row.get("flu_rt") #등락률
            int_rflu  = _to_abs_int(row.get("flu_rt"))   # 부호 제거
            
            if(int_rflu > (tp*100)): #부호가 제거된 등락률이 상한 포로핏보다 크면 저장하기
                ret_val.append((self.rcode, self.rname, self.rprice, self.rflu))

            #print(f"여긴가? {self.rcode} / {self.rname} / {self.rprice} / {self.rflu}")

        return ret_val    

    #oto 파일에서 이쪽으로 합쳤음. - 실제 행동하는 함수
    def place_limit_buy_then_oto_takeprofit(
        self,
        stk_cd: str,
        buy_price: int,
        qty: int,
        take_profit_add: int,  # "매수 체결단가 + 익절가격" (원 단위)
        poll_sec: float = 1.0,
        timeout_sec: int = 3,
    ) -> dict:
        """
        1) 지정가 매수 → 2) 체결 여부 폴링 → 3) (체결시) 익절 지정가 매도 주문 접수
        반환: {buy_ord_no, buy_avg_price, sell_ord_no}
        """
        # 1) 지정가 매수 접수
        buy_ord_no = self.place_buy_limit(stk_cd=stk_cd, qty=qty, price=buy_price)

        # 2) 체결 대기(누적 체결수량 == 주문수량까지)
        deadline = time.time() + timeout_sec
        buy_avg: Optional[int] = None
        buy_ord_qty: Optional[int] = None
        while time.time() < deadline:
            summ = self.get_order_fill_summary(buy_ord_no)
            buy_ord_qty = summ.get("ord_qty")
            if buy_ord_qty and summ.get("filled_qty") >= buy_ord_qty:
                buy_avg = summ.get("avg_price") or buy_price
                break
            time.sleep(poll_sec)
        if buy_avg is None:
            #raise TimeoutError(f"매수 체결 대기 타임아웃: ord_no={buy_ord_no}")            
            buy_avg = buy_price # 이건 Time Out이 걸려도 그냥 넘어가도록 한 것임 
            print(f"[지정가 매수실패] == Timeout {timeout_sec} Sec ==")
            buy_ord_no = '지정가 매수실패'
            buy_avg = 0
            sell_ord_no = '지정가 매수실패'
            tp_price = 0
        else:
            # 3) 익절 지정가 매도 접수 (매수 체결평단 + 익절가)
            tp_price = floor_to(int(buy_avg + (buy_avg * (take_profit_add/100))), 50)    
            sell_ord_no = self.place_sell_limit(stk_cd=stk_cd, qty=buy_ord_qty, price=tp_price)
        
        return {
            "buy_ord_no": buy_ord_no,
            "buy_avg_price": buy_avg,
            "sell_ord_no": sell_ord_no,
            "sell_price": tp_price,
        }


    def place_market_buy_then_oto_takeprofit(    
        self,    
        stk_cd: str,
        buy_price: int,
        qty: int,
        take_profit_add: float,
        poll_sec: float = 1.0,
        timeout_sec: int = 3,
    ) -> dict:
        """
        1) 시장가 매수 → 2) 체결 여부 폴링 → 3) (체결시) 익절 지정가 매도 주문 접수
        반환: {buy_ord_no, buy_avg_price, sell_ord_no, sell_price}
        """
        buy_ord_no = self.place_buy_market(stk_cd=stk_cd, qty=qty)
        deadline = time.time() + timeout_sec
        buy_avg: Optional[int] = None
        buy_ord_qty: Optional[int] = None
        while time.time() < deadline:
            summ = self.get_order_fill_summary(buy_ord_no)
            buy_ord_qty = summ.get("ord_qty")
            if buy_ord_qty and summ.get("filled_qty") >= buy_ord_qty:
                buy_avg = summ.get("avg_price")
                if buy_avg is None:
                    last_price = self.get_last_price(stk_cd)
                    if last_price is not None:
                        buy_avg = last_price
                break
            time.sleep(poll_sec)
        if buy_avg is None:
            #raise TimeoutError(f"매수 체결 대기 타임아웃: ord_no={buy_ord_no}")
            buy_avg = buy_price # 이건 TEST 용입니다용
            print(f"==시장가 매수 Timeout {timeout_sec} Sec==")
        tp_price = floor_to(int(buy_avg + (buy_avg * (take_profit_add/100))), 50)
        sell_ord_no = self.place_sell_limit(stk_cd=stk_cd, qty=buy_ord_qty, price=tp_price)

        return {
            "buy_ord_no": buy_ord_no,
            "buy_avg_price": buy_avg,
            "sell_ord_no": sell_ord_no,
            "sell_price": tp_price,
        }

    def place_market_sell_all(
        self,    
        poll_sec: float = 1.0,
        timeout_sec: int = 3,
    ) -> str:
        
        # 1) 모두 팔아! 매도 주문 접수
        balance_info = self.get_my_all_stock()
        time.sleep(1)
        tprint(balance_info)
        print(f"보유 종목 수는 {len(balance_info)} 입니다.")
        
        result = self.get_order_List()
        ret_no = None

        for r in result:    
            stk_cd = r.get("stk_cd")
            stk_nm = r.get("stk_nm")
            ord_no = r.get("ord_no")
            tprint(f"get_order_List -> {stk_cd} / {stk_nm} / {ord_no}")
            ret_no = self.place_sell_order_cancel(ord_no, stk_cd)
            tprint(f"place_sell_order_cancel = {ret_no}")
            time.sleep(1)        
    
        # 잔고에서 매도 주문 실행
        for stock in balance_info:
            sell_no = self.place_sell_market(stock['stk_cd'],int(stock['trde_able_qty']))
            tprint(f"sell_no{ret_no}")
            time.sleep(1)

        return ret_no
    
    def place_loss_cut_sell(            
        self,    
        buy_ord_no: str, 
        stk_cd: str, 
        qty: int = 0,        
        ) -> str:
        
        #def place_sell_market(self, stk_cd: str, qty: int) -> str:
        # 1) 모두 팔아! 매도 주문 접수
        ret_no = self.place_sell_order_cancel(buy_ord_no, stk_cd, qty) 
        time.sleep(1)
        tprint(f"place_sell_order_cancel = {ret_no}")

        # 1) 모두 팔아! 매도 주문 접수
        balance_info = self.get_my_all_stock()
        time.sleep(1)
        tprint(balance_info)
        print(f"보유 종목 수는 {len(balance_info)} 입니다.")

        t_qty = 0
        sell_no = None
        # 잔고에서 매도 주문 실행
        for stock in balance_info:
            if int(stock['stk_cd'] == stk_cd):
                t_qty = int(stock['trde_able_qty'])
                break

        if t_qty > 0:  # 매도 가능한 수량이 있는 경우
            sell_no = self.place_sell_market(stk_cd, t_qty)
            tprint(f"sell_no{sell_no}")
            time.sleep(1)

        #여기서 채결 확인을 할지 걍 넘어갈지...일단은 걍 넘어가 보자
        
        return {                    
            "sell_ord_no": sell_no,                
        }
    
#==============================================================
    
    # 전일거래대금 상위요청
    def get_prev_day_top_by_value(self) -> list[tuple[str, str, str, str]]:
    
        body = {
            'mrkt_tp': '000',  # 시장구분 000:전체, 001:코스피, 101:코스닥
            'qry_tp': '2',  # 조회구분 1:전일거래량 상위100종목, 2:전일거래대금 상위100종목
            'rank_strt': '0',  # 순위시작 0 ~ 100 값 중에 조회를 원하는 순위 시작값
            'rank_end': '50',  # 순위끝 0 ~ 100 값 중에 조회를 원하는 순위 끝값
            'stex_tp': '1',  # 거래소구분 1:KRX, 2:NXT 3.통합
        }

        data = self._post("/api/dostk/rkinfo", api_id="ka10031", body=body)

        if data.get("return_code") == 0:
            top_stocks = data.get("pred_trde_qty_upper", [])
            
            print("--- 전일 거래대금 상위 50개 종목 조회 결과 ---")
            
            # stk_cd: 종목코드, stk_nm: 종목명, cur_prc: 현재가, trde_qty: 거래량
            for stock in top_stocks:
                print(
                    f"순위: {top_stocks.index(stock) + 1}, "
                    f"종목명: {stock.get('stk_nm')}, "
                    f"코드: {stock.get('stk_cd')}, "
                    f"거래대금: {stock.get('trde_qty')}"
                )
            
            return top_stocks

        else:
            print(f"API 요청 실패: {data.get('return_msg')}")
            return None



    # 전일거래량 상위요청
    def get_prev_day_top_by_volume(self) -> list[tuple[str, str, str, str]]:
    
        body = {
            'mrkt_tp': '000',  # 시장구분 000:전체, 001:코스피, 101:코스닥
            'qry_tp': '1',  # 조회구분 1:전일거래량 상위100종목, 2:전일거래대금 상위100종목
            'rank_strt': '0',  # 순위시작 0 ~ 100 값 중에 조회를 원하는 순위 시작값
            'rank_end': '50',  # 순위끝 0 ~ 100 값 중에 조회를 원하는 순위 끝값
            'stex_tp': '1',  # 거래소구분 1:KRX, 2:NXT 3.통합
        }

        data = self._post("/api/dostk/rkinfo", api_id="ka10031", body=body)

        if data.get("return_code") == 0:
            top_stocks = data.get("pred_trde_qty_upper", [])
            
            print("--- 전일 거래량 상위 50개 종목 조회 결과 ---")
            
            # stk_cd: 종목코드, stk_nm: 종목명, cur_prc: 현재가, trde_qty: 거래량
            for stock in top_stocks:
                print(
                    f"순위: {top_stocks.index(stock) + 1}, "
                    f"종목명: {stock.get('stk_nm')}, "
                    f"코드: {stock.get('stk_cd')}, "
                    f"거래량: {stock.get('trde_qty')}"
                )
            
            return top_stocks

        else:
            print(f"API 요청 실패: {data.get('return_msg')}")
            return None

#======================================================
#======================================================

    def sanitize_price(self, price_str: str) -> float:
        """API 응답 문자열에서 부호와 쉼표를 제거하고 float으로 변환합니다."""
        if not price_str: return 0.0
        # +/- 기호와 쉼표를 제거하고 float으로 변환 (소스 데이터 형태 고려)
        cleaned = re.sub(r'[+-,\s]', '', price_str)
        return float(cleaned) if cleaned else 0.0
    
    
    #종목의 현재 시세표 정보를 조회.
    def get_stock_market_data(self, stk_cd):
        
        body = {"stk_cd": stk_cd}

        data = self._post("/api/dostk/mrkcond", api_id="ka10007", body=body)
            
        # 필드 값 추출 및 숫자형 변환 (API 응답은 문자열, +/- 부호 포함될 수 있음)
        # 데이터가 없을 경우 0으로 처리 (주의: 실제 API 데이터 형태에 따라 파싱 로직 달라질 수 있음)
        pred_close_pric = float(data.get("pred_close_pric", "0").strip('+-').replace(',', '') or 0) #전일종가
        open_pric = float(data.get("open_pric", "0").strip('+-').replace(',', '') or 0) #시가
        
        return {
            "pred_close_pric": pred_close_pric,
            "open_pric": open_pric,
            "current_time": data.get("tm", "N/A")
        }, True

    # ----------------------------------------------------
    # 2차 검증 기능 2-2: 유의미한 저항선 (최근 신고가) 조회
    # ----------------------------------------------------
    def get_recent_high_price(self, stk_cd: str, period: str = "060") -> float:
        """ka10016 (신고저가요청)을 사용하여 최근 신고가를 저항선으로 사용합니다."""
     
        # 60일 신고가 조회 요청 (기간: 60)
        body = {
            "mrkt_tp": "000", #000:전체, 001:코스피, 101:코스닥
            "ntl_tp": "1", # 1:신고가,2:신저가
            "high_low_close_tp": "1", #1:고저기준, 2:종가기준
            "stk_cnd": "0", #종목조건 : 전체조회
            "trde_qty_tp": "00000", #거래량구분 : 전체조회
            "crd_cnd": "0", #신용조건 : 전체조회
            "updown_incls": "0", #상하한포함 : 미포한
            "dt": period,  # 기간 5:5일, 10:10일, 20:20일, 60:60일, 250:250일
            "stex_tp": "1" # 거래소 : KRX
        }

        data = self._post("/api/dostk/stkinfo", api_id="ka10016", body=body)

        if data.get("return_code") == 0:
            # 신고가 리스트에서 해당 종목의 최고가를 찾음
            target_data = next((item for item in data.get("ntl_pric", []) if item.get("stk_cd") == stk_cd), None)
            if target_data:
                # high_pric가 신고가를 나타낸다고 가정
                return self.sanitize_price(target_data.get("high_pric", "0"))
        return 0.0


    # ----------------------------------------------------
    # 2차 검증 기능 2-1: 체결 강도 확인
    # ----------------------------------------------------
    def check_contract_strength(self, stk_cd: str) -> float:

        body = {"stk_cd": stk_cd}

        data = self._post("/api/dostk/mrkcond", api_id="ka10046", body=body)

        if data.get("return_code") == 0:
            strength_data_list = data.get("cntr_str_tm", [])
            if strength_data_list:
                latest_data = strength_data_list[-1]
                return float(latest_data.get("cntr_str", "0.00"))
        return 0.0
        
    # ----------------------------------------------------
    # 1차 스캐닝 : 고유동성 종목 리스트 획득 
    # ETF + ETN 제외, 거래대금 100억 이상, 거래량 20만주 이상.
    # ----------------------------------------------------
    def get_primary_candidates(self, trde_qty: int) -> List[Dict]:
 
        body = {
            "mrkt_tp": "000",        # 시장구분: 000 (전체)
            "sort_tp": "1",          # 정렬구분: 1 (상승률 순)  1:상승률, 2:상승폭, 3:하락률, 4:하락폭, 5:보합
            "trde_qty_cnd": f"{trde_qty}" ,  # 거래량 조건: 
            #0000:전체조회, 0010:만주이상, 0050:5만주이상,
            #0100:10만주이상, 0150:15만주이상, 0200:20만주이상,
            #0300:30만주이상, 0500:50만주이상, 1000:백만주이상
            "stk_cnd": "16",         # 종목조건: 16 (ETF+ETN제외)
            #0:전체조회, 1:관리종목제외, 4:우선주+관리주제외,
            #3:우선주제외, 5:증100제외, 6:증100만보기, 7:증40만보기,
            #8:증30만보기, 9:증20만보기, 11:정리매매종목제외,
            #12:증50만보기, 13:증60만보기, 14:ETF제외, 15:스펙제외,
            #16:ETF+ETN제외
            "crd_cnd": "0",          # 신용조건: 0 (전체 조회)
            "updown_incls": "1",      # 상하한 포함: 1 (포함)
            "pric_cnd": "0",         # 가격 조건: 0 (전체 조회)
            "trde_prica_cnd": "1000", # 거래대금 조건: 1000 (100억 원 이상)
            #0:전체조회, 3:3천만원이상, 5:5천만원이상, 10:1억원이상,
            #30:3억원이상, 50:5억원이상, 100:10억원이상,
            #300:30억원이상, 500:50억원이상, 1000:100억원이상,
            #3000:300억원이상, 5000:500억원이상
            "stex_tp": "1"           # 거래소 구분: 1 (KRX)
        }

        data = self._post("/api/dostk/rkinfo", api_id="ka10027", body=body)

        if data.get("return_code") == 0:
            top_stocks = data.get("pred_pre_flu_rt_upper", [])
                
            if not top_stocks:
                print("조회된 종목이 없습니다.")
                return []
         
            """
            for stock in top_stocks:
                print(
                    f"순위: {top_stocks.index(stock) + 1}, "
                    f"종목명: {stock.get('stk_nm')}, "
                    f"코드: {stock.get('stk_cd')}, "
                    f"등락률: {stock.get('flu_rt')}, "
                    f"현재가: {stock.get('cur_prc')}"
                )
            """

            return top_stocks

        else:
            print(f"API 요청 실패: {data.get('return_msg')}")
            return None

# ----------------------------------------------------
    # 종목 선정
    # ETF + ETN 제외, 거래대금 100억 이상, 거래량 20~50만주 이상, 갭 상승 돌파 제외
    # ----------------------------------------------------

    def get_stocks_code(self, max_limit) -> list[tuple[str, str, str, str]]:
        
        selected_stocks = []
        
        # 1. 1차 스캐닝: 고유동성 종목 리스트 획득 (거래대금 100억 이상, 거래량 50만주 이상.)
        #0000:전체조회, 0010:만주이상, 0050:5만주이상,
        #0100:10만주이상, 0150:15만주이상, 0200:20만주이상,
        #0300:30만주이상, 0500:50만주이상, 1000:백만주이상
        for trde_qty in 1000, 500, 300, 200:
            candidates = self.get_primary_candidates(trde_qty)
            time.sleep(1)
            if not candidates:
                print("1차 필터링 기준을 충족하는 종목이 없습니다.")
                return []
            print(f"거래량: [{trde_qty}], 종목수 {len(candidates)}개")
            if len(candidates) >= max_limit * 5: # 종목수가 최대수량의 5배가 넘으면 검색 멈춤. 적으면 조건 낮춰 재검색
                break

        print(f"## 1차 필터링 통과 종목 수: {len(candidates)}개. 2차 검증 시작...\n")
        
        for stock in candidates:
            stk_cd = stock.get('stk_cd')
            stk_nm = stock.get('stk_nm')
            
            # 2. 2차 검증: 기술적/심리적 필터 적용
            
            # 2-1. 체결 강도 확인 (실시간 매수세)            
            strength = self.check_contract_strength(stk_cd)
            time.sleep(1)
            if strength < 120.0:                
                clear_prev_lines(1) # 겹쳐 쓰기 1줄 위로
                print(f"제외: [{stk_nm}] 체결 강도 {strength:.2f} (120 미만)")                
                continue # 체결강도 120 이상인 종목만 추적

            # 2-2. 갭 상승 저항 돌파 여부 확인 (리스크 관리)
            
            # A. 시가 및 전일 종가 조회 
            data, success = self.get_stock_market_data(stk_cd)
            time.sleep(1)
        
            if not success or data['open_pric'] == 0:
                return True, "조회 실패 또는 장 시작 전."

            open_pric = data['open_pric']  #시가
            pred_close_pric = data['pred_close_pric']  #전일 종가

            # B. 최근 신고가 (저항선) 조회
            recent_high = self.get_recent_high_price(stk_cd, period="060") # 60일 신고가를 저항선으로 사용
            time.sleep(1)
            resistance_price = max(pred_close_pric, recent_high) # 전일 종가와 60일 신고가 중 높은 것을 저항으로 설정

            # C. 갭 상승 및 저항 돌파 판단
            is_gap_up = open_pric > pred_close_pric
            if is_gap_up and open_pric >= resistance_price * 0.995: # 0.5% 이내 근접하여 돌파했다고 판단
                # 단타 매매 원칙: 갭 상승으로 이미 저항을 돌파한 종목은 매수하지 않는다
                clear_prev_lines(1) # 겹쳐 쓰기 1줄 위로
                print(f"제외: [{stk_nm}] 갭 상승 및 저항 돌파 (시가: {open_pric:,.0f}, 저항: {resistance_price:,.0f})")
                continue 

            # 3. 최종 선정
            selected_stocks.append({
                "stk_cd": stk_cd,
                "stk_nm": stk_nm,
                "strength": strength,
                "resistance": resistance_price
            })

            #if len(selected_stocks) >= max_limit:
            #    break
                
        # 최종 결과 정리 (체결강도 순으로 정렬)
        final_list = sorted(selected_stocks, key=lambda x: x['strength'], reverse=True)
        
        print("\n========= 최종 선정된 단타 주도주 리스트 =========")
        for i, item in enumerate(final_list):
            print(f"순위 {i+1}: {item['stk_nm']} ({item['stk_cd']}) | 체결강도: {item['strength']:.2f} | 저항가격: {item['resistance']:}")

        return [(item['stk_cd'], item['stk_nm'], item['resistance'], item['strength']) for item in final_list[:max_limit]]
        #return [item['stk_cd'] for item in final_list]




