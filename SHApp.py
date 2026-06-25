# 프로그램 시작 시 계좌 주문가능금액을 조회한 뒤
# 삼성전자, SK하이닉스를 각각 50%씩 시장가 매수하고
# 매수 체결가 기준 +12%, -6% 예약/조건 매도를 등록합니다.

from __future__ import annotations

import os
import math
import time
import sys
from datetime import datetime, timedelta
from typing import Any

from auth import KiwoomAuth
from kiwoom_client import KiwoomClient
from tools import *

# 00:00이면 즉시 시작, 예: "09:00"이면 해당 시간까지 대기
start_time: str = "00:00"

# 모의투자 여부. 실전은 False로 변경하세요.
is_paper: bool = True

# 체결 확인 설정
float_poll: float = 1.0
float_timeout: float = 30.0
int_MaxLoop: int = 15

# 매매 대상 및 비중
TARGET_STOCKS: list[dict[str, Any]] = [
    {"code": "005930", "name": "삼성전자", "weight": 0.50},
    {"code": "000660", "name": "SK하이닉스", "weight": 0.50},
]

# 매수 체결가 기준 예약 매도가
TAKE_PROFIT_PCT: float = 12.0
STOP_LOSS_PCT: float = 6.0

# 호가 단위 반올림 기준. 기존 코드의 floor_to(..., 10) 방식 유지
PRICE_UNIT: int = 10

# 디버그 출력 여부
b_Tprint: bool = False
b_Test: bool = False


def wait_until(hhmm: str) -> None:
    if hhmm == "00:00":
        return

    _enable_ansi_on_windows()

    try:
        hh, mm = map(int, hhmm.split(":"))
    except Exception:
        raise SystemExit("start_time은 HH:MM 형식이어야 합니다. 예: 09:00")

    now = datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)

    print(f"예약시간 {target:%Y-%m-%d %H:%M:%S}")
    print(f"현재시각 {datetime.now():%Y-%m-%d %H:%M:%S}")

    try:
        while True:
            now = datetime.now()
            if now >= target:
                sys.stdout.write("\033[1A\033[2K")
                sys.stdout.write(f"현재시각 {now:%Y-%m-%d %H:%M:%S}\n")
                sys.stdout.flush()
                print("시간 도달! 작업을 시작합니다.")
                break

            sys.stdout.write("\033[1A\033[2K")
            sys.stdout.write(f"현재시각 {now:%Y-%m-%d %H:%M:%S}\n")
            sys.stdout.flush()
            time.sleep(1)
    except KeyboardInterrupt:
        print("사용자 중단(Ctrl+C)")
        sys.exit(1)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _pick_first_value(data: Any, keys: tuple[str, ...], default: Any = None) -> Any:
    """KiwoomClient 반환 dict의 키 이름이 조금 달라도 값을 읽기 위한 보조 함수."""
    if not isinstance(data, dict):
        return default
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return default


def _place_market_buy(client: KiwoomClient, stk_cd: str, qty: int) -> dict[str, Any]:
    """
    KiwoomClient에 구현된 시장가 매수 함수명이 프로젝트마다 다를 수 있어
    많이 쓰는 함수명을 순서대로 찾아 호출합니다.

    아래 함수 중 현재 kiwoom_client.py에 실제 존재하는 함수가 호출됩니다.
    - place_market_buy(stk_cd, qty)
    - place_market_buy_order(stk_cd, qty)
    - place_buy_order(stk_cd, qty, 0, "03")
    """
    if hasattr(client, "place_market_buy"):
        return client.place_market_buy(stk_cd=stk_cd, qty=qty)

    if hasattr(client, "place_market_buy_order"):
        return client.place_market_buy_order(stk_cd=stk_cd, qty=qty)

    if hasattr(client, "place_buy_order"):
        # 일반적으로 0원 + 호가구분 03 = 시장가 방식으로 쓰는 구현이 많습니다.
        return client.place_buy_order(stk_cd=stk_cd, qty=qty, price=0, hoga_gb="03")

    raise AttributeError(
        "KiwoomClient에 시장가 매수 함수가 없습니다. "
        "kiwoom_client.py에 place_market_buy(stk_cd, qty)를 추가하거나 "
        "이 함수의 호출부를 실제 매수 함수명에 맞게 수정하세요."
    )


def _wait_buy_filled(
    client: KiwoomClient,
    stk_cd: str,
    order_result: dict[str, Any],
    fallback_price: int,
    timeout_sec: float,
    poll_sec: float,
) -> tuple[int, int, str | None]:
    """매수 체결가/수량/주문번호를 확인합니다. 전용 조회 함수가 없으면 주문 결과와 현재가로 보정합니다."""
    buy_ord_no = _pick_first_value(order_result, ("buy_ord_no", "ord_no", "order_no", "ordNo"))
    filled_qty = int(_pick_first_value(order_result, ("filled_qty", "qty", "ord_qty"), 0) or 0)
    avg_price = int(_pick_first_value(order_result, ("buy_avg_price", "avg_price", "filled_price"), 0) or 0)

    if avg_price > 0 and filled_qty > 0:
        return avg_price, filled_qty, buy_ord_no

    # 프로젝트에 매수 체결 대기 함수가 있으면 사용합니다.
    if hasattr(client, "wait_buy_filled") and buy_ord_no:
        filled = client.wait_buy_filled(buy_ord_no, stk_cd, poll_sec=poll_sec, timeout_sec=timeout_sec)
        avg_price = int(_pick_first_value(filled, ("buy_avg_price", "avg_price", "filled_price"), 0) or 0)
        filled_qty = int(_pick_first_value(filled, ("filled_qty", "qty", "ord_qty"), filled_qty) or 0)
        if avg_price > 0 and filled_qty > 0:
            return avg_price, filled_qty, buy_ord_no

    # 별도 체결 조회 함수가 없는 경우, 시장가 주문은 체결되었다고 보고 현재가를 체결가로 사용합니다.
    if filled_qty <= 0:
        filled_qty = int(_pick_first_value(order_result, ("qty", "ord_qty"), 0) or 0)
    if avg_price <= 0:
        avg_price = fallback_price

    return avg_price, filled_qty, buy_ord_no


def _place_take_profit_sell(client: KiwoomClient, stk_cd: str, qty: int, sell_price: int) -> dict[str, Any]:
    """+12% 지정가 매도 예약."""
    if hasattr(client, "place_limit_sell"):
        return client.place_limit_sell(stk_cd=stk_cd, qty=qty, price=sell_price)

    if hasattr(client, "place_limit_sell_order"):
        return client.place_limit_sell_order(stk_cd=stk_cd, qty=qty, price=sell_price)

    if hasattr(client, "place_sell_order"):
        return client.place_sell_order(stk_cd=stk_cd, qty=qty, price=sell_price, hoga_gb="00")

    raise AttributeError(
        "KiwoomClient에 지정가 매도 함수가 없습니다. "
        "place_limit_sell(stk_cd, qty, price) 또는 실제 함수명에 맞게 수정하세요."
    )


def _place_stop_loss_sell(client: KiwoomClient, stk_cd: str, qty: int, stop_price: int, buy_ord_no: str | None) -> dict[str, Any]:
    """
    -6% 손절 예약/조건 매도 등록.

    프로젝트에 stop/condition 예약 함수가 있으면 우선 사용합니다.
    없으면 기존 SHApp.py에서 쓰던 place_loss_cut_sell을 호출합니다.
    단, place_loss_cut_sell은 기존 코드상 손절가 도달 후 시장가 청산 함수일 수 있으므로
    실제 예약주문 함수가 따로 있다면 이 부분을 해당 함수명으로 맞추는 것이 가장 안전합니다.
    """
    if hasattr(client, "place_stop_loss_sell"):
        return client.place_stop_loss_sell(stk_cd=stk_cd, qty=qty, stop_price=stop_price)

    if hasattr(client, "place_stop_sell_order"):
        return client.place_stop_sell_order(stk_cd=stk_cd, qty=qty, stop_price=stop_price)

    if hasattr(client, "place_loss_cut_sell") and buy_ord_no:
        return client.place_loss_cut_sell(buy_ord_no=buy_ord_no, stk_cd=stk_cd)

    raise AttributeError(
        "KiwoomClient에 손절 예약/조건 매도 함수가 없습니다. "
        "place_stop_loss_sell(stk_cd, qty, stop_price)를 추가하거나 실제 함수명에 맞게 수정하세요."
    )


def main() -> None:
    global float_timeout

    set_test_mode(b_Tprint)
    print(f"TEST Mode - {b_Test} - [MAIN] 삼성전자/SK하이닉스 50:50 자동매수 APP 시작")

    BaseURL = os.getenv("KIWOOM_URL", "https://mockapi.kiwoom.com")
    app_key = os.getenv("KIWOOM_APP_KEY")
    app_secret = os.getenv("KIWOOM_APP_SECRET")

    if not app_key or not app_secret:
        raise SystemExit("KIWOOM_APP_KEY, KIWOOM_APP_SECRET 환경변수를 설정하세요.")

    auth = KiwoomAuth(app_key, app_secret, BaseURL)
    access_token = auth.token() if hasattr(auth, "token") else auth._access_token
    time.sleep(1)

    client = KiwoomClient(access_token, is_paper=is_paper)
    time.sleep(1)

    if b_Test:
        print(f"[TEST MODE] 장시작 예약시간 {start_time} PASS")
        float_timeout = 1
    else:
        wait_until(start_time)

    cur_entr = client.get_current_entr()
    print(f"[{_now()}] 계좌 주문가능금액: {format(cur_entr, ',')}원")

    results: list[dict[str, Any]] = []

    for target in TARGET_STOCKS:
        stk_cd = target["code"]
        stk_nm = target["name"]
        budget = math.floor(cur_entr * float(target["weight"]))

        now_price = int(client.get_last_price(stk_cd))
        time.sleep(1)

        qty = int(budget // now_price) if now_price > 0 else 0
        print(f"[{_now()}] {stk_nm}[{stk_cd}] 배정금액 {format(budget, ',')}원 / 현재가 {format(now_price, ',')}원 / 매수수량 {qty}주")

        if qty < 1:
            print(f"[{_now()}] {stk_nm}[{stk_cd}] 매수 가능 수량이 0주라서 건너뜁니다.")
            continue

        if b_Test:
            buy_avg_price = now_price
            buy_ord_no = "TEST_BUY"
            filled_qty = qty
            buy_result: dict[str, Any] = {"buy_ord_no": buy_ord_no, "qty": qty}
        else:
            buy_result = _place_market_buy(client, stk_cd, qty)
            buy_avg_price, filled_qty, buy_ord_no = _wait_buy_filled(
                client=client,
                stk_cd=stk_cd,
                order_result=buy_result,
                fallback_price=now_price,
                timeout_sec=float_timeout,
                poll_sec=float_poll,
            )

        if buy_avg_price <= 0 or filled_qty <= 0:
            print(f"[{_now()}] {stk_nm}[{stk_cd}] 시장가 매수 체결 확인 실패: {buy_result}")
            continue

        take_profit_price = floor_to(buy_avg_price * (1 + TAKE_PROFIT_PCT / 100.0), PRICE_UNIT)
        stop_loss_price = floor_to(buy_avg_price * (1 - STOP_LOSS_PCT / 100.0), PRICE_UNIT)

        if b_Test:
            tp_result = {"sell_ord_no": "TEST_TP"}
            sl_result = {"sell_ord_no": "TEST_SL"}
        else:
            tp_result = _place_take_profit_sell(client, stk_cd, filled_qty, take_profit_price)
            time.sleep(1)
            sl_result = _place_stop_loss_sell(client, stk_cd, filled_qty, stop_loss_price, buy_ord_no)

        result = {
            "stk_nm": stk_nm,
            "stk_cd": stk_cd,
            "qty": filled_qty,
            "buy_avg_price": buy_avg_price,
            "take_profit_price": take_profit_price,
            "stop_loss_price": stop_loss_price,
            "buy_ord_no": buy_ord_no,
            "tp_result": tp_result,
            "sl_result": sl_result,
        }
        results.append(result)

        print(
            f"[{_now()}] {stk_nm}[{stk_cd}] 매수완료 "
            f"체결가 {format(buy_avg_price, ',')}원 / 수량 {filled_qty}주 / "
            f"익절예약 {format(take_profit_price, ',')}원(+{TAKE_PROFIT_PCT}%) / "
            f"손절예약 {format(stop_loss_price, ',')}원(-{STOP_LOSS_PCT}%)"
        )

    print(f"\n[{_now()}] 주문 등록 결과")
    for item in results:
        print(
            f"- {item['stk_nm']}[{item['stk_cd']}] "
            f"{item['qty']}주 / 매수가 {format(item['buy_avg_price'], ',')}원 / "
            f"+12% {format(item['take_profit_price'], ',')}원 / "
            f"-6% {format(item['stop_loss_price'], ',')}원"
        )

    cur_entr_after = client.get_current_entr()
    print(f"[{_now()}] 주문 후 계좌 주문가능금액: {format(cur_entr_after, ',')}원")
    print(f"[{_now()}] 완료")


if __name__ == "__main__":
    main()
