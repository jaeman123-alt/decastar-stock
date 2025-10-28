# =====================================
# file: get_code_list.py
# =====================================

"""
책의 조언.
1. 당일 가장 인기 있는 테마 찾기  -> 거래대금 상위  - 거래량은 쓰지마라!
2. 이슈 파악하기 -> 신문
3. 비슷한 종목들은 1등주만 노려라.
4. 시가총액 3천억 ~ 10조 사이. (3천억 미만은 잡주, 10조 이상은 너무 느림)
5. 공매도 잔고수량 비율이 높은 주식은 제외 -> KRX 정보 데이터 시스템
6. 역사적 저점 종목 X -> 6개월 전고점 돌파 종목
7. 전일 종가 대비 시가가 1%이상 하락 종목 제외
8. 신고가 돌파주 good.

종목찾기-2
A. 시가총액 3천억 ~ 10조 사이 종목들 리스트 만들고 (json)
B. 리스트에서 공매도 잔고수량 비율이 높은 주식 제외
C. 현재 거래대금 상위 종목들과 연동
D. 신고가 돌파주는 별도 표시
"""

import os
import json
import requests
import time
from auth import KiwoomAuth

short_sell_ratio_threshold=5.0
start_date= '20250601',  # 임의 시작일 (실제 오늘 날짜로 변경 권장)
end_date= '20251029',    # 임의 종료일 (실제 오늘 날짜로 변경 권장)

b_JMKEY: bool = True #True # JM 계좌 사용
host = 'https://mockapi.kiwoom.com'  

def fn_ka10099(token, params, cont_yn='N', next_key=''):
    endpoint = '/api/dostk/stkinfo'
    url = host + endpoint

    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'cont-yn': cont_yn,
        'next-key': next_key,
        'api-id': 'ka10099',
    }

    response = requests.post(url, headers=headers, json=params)
    if response.status_code != 200:
        raise Exception(f"API 요청 실패: {response.status_code}")
    return response.json(), response.headers

def get_market_stocks(token, market_code):
    all_stocks = []
    cont_yn = 'N'
    next_key = ''
    while True:
        params = {'mrkt_tp': market_code}
        data, headers = fn_ka10099(token, params, cont_yn, next_key)
        time.sleep(1)
        stocks = data.get('list', [])
        all_stocks.extend(stocks)
        cont_yn = headers.get('cont-yn', 'N')
        next_key = headers.get('next-key', '')
        if cont_yn != 'Y':
            break
    return all_stocks

def filter_by_market_cap(stocks, min_cap, max_cap):
    filtered = []
    for stock in stocks:
        try:
            list_count = int(stock.get('listCount', '0'))
            last_price = int(stock.get('lastPrice', '0'))
            market_cap = list_count * last_price
            if min_cap <= market_cap <= max_cap:
                filtered.append({
                    'code': stock.get('code'),
                    'name': stock.get('name'),
                    'market_cap': str(market_cap),
                    'lastPrice': stock.get('lastPrice'),
                    'listCount': stock.get('listCount'),
                    'marketName': stock.get('marketName')
                })
        except ValueError:
            continue
    return filtered




# 공매도추이요청 함수
def fn_ka10014(token, stk_cd, cont_yn='N', next_key=''):
    endpoint = '/api/dostk/shsa'
    url = host + endpoint

    headers = {
        'Content-Type': 'application/json;charset=UTF-8',
        'authorization': f'Bearer {token}',
        'cont-yn': cont_yn,
        'next-key': next_key,
        'api-id': 'ka10014',
    }

    params = {
        'stk_cd': stk_cd,
        'tm_tp': '1',  # 기간 조회
        'strt_dt': start_date,
        'end_dt': end_date,
    }

    response = requests.post(url, headers=headers, json=params)
    if response.status_code != 200:
        raise Exception(f"API 요청 실패: {response.status_code}")
    return response.json()



# 국내주식 중 시가총액이 3천억에서 10조 사이인 종목을 조회하여 JSON 파일로 저장하는 파이썬 코드
if __name__ == '__main__':

    filtered_codes = []

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
    ACCESS_TOKEN = auth._access_token

    kospi_stocks = get_market_stocks(ACCESS_TOKEN, '0')
    kosdaq_stocks = get_market_stocks(ACCESS_TOKEN, '10')

    all_stocks = kospi_stocks + kosdaq_stocks

    # 시가총액 범위: 3천억 ~ 10조 (단위: 원)
    min_market_cap = 3_000_000_000_000 // 10  # 3천억 = 3000억 원 (단위 맞춤)
    max_market_cap = 10_000_000_000_000  # 10조 원

    # 시가총액 단위 맞춤 (listCount * lastPrice는 주식수 * 가격, 단위는 원)
    # 참고로 listCount는 상장주식수(주), lastPrice는 전일종가(원)

    filtered_stocks = filter_by_market_cap(all_stocks, 300000000000, 10000000000000)

    # 'ETF'제외
    filtered = [stock for stock in filtered_stocks if 'ETF' not in stock.get('marketName', '')]

    #for stock in filtered.get('list', []):
    for stock in filtered:
        stk_cd = stock.get('code')
        #  공매도 잔고 비율 확인 
        short_data, _ = fn_ka10014(ACCESS_TOKEN, stk_cd)
        shrts_trnsn = short_data.get('shrts_trnsn', [])
        if shrts_trnsn:
            # 가장 최근 데이터 기준으로 공매도량 비율 계산
            recent = shrts_trnsn[0]
            trde_qty = int(recent.get('trde_qty', '0').replace(',', ''))
            shrts_qty = int(recent.get('shrts_qty', '0').replace(',', ''))
            if trde_qty > 0:
                short_ratio = (shrts_qty / trde_qty) * 100
            else:
                short_ratio = 0.0

            # 공매도 잔고 비율이 threshold 이하인 종목만 추가
            if short_ratio <= short_sell_ratio_threshold:
                filtered_codes.append(stk_cd)
        else:
            # 공매도 데이터 없으면 포함
            filtered_codes.append(stk_cd)


    # JSON 파일로 저장
    with open('filtered_market_cap_stocks.json', 'w', encoding='utf-8') as f:
        json.dump(filtered_codes, f, ensure_ascii=False, indent=4)

    print(f"총 {len(filtered_codes)}개 종목이 시가총액 조건에 맞아 저장되었습니다.")



