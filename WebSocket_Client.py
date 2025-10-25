# =====================================
# file: WebSocketClient.py
# =====================================
from __future__ import annotations

import asyncio
import websockets
import json

from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from tools import *

SOCKET_URL = 'wss://api.kiwoom.com:10000/api/dostk/websocket'  # 접속할 주소

class WebSocketClient:
    access_token: str

    def __init__(self, uri):                
        tprint("[WebSocketClient] 시작")

        self.uri = SOCKET_URL   # 연결한 서버의 주소
        self.websocket = None  # 실제 웹소켓 연결을 관리하는 변수
        self.connected = False # 연결상태 (True면 연결됨)
        self.keep_running = True



    async def connect(self):
        try:
            self.websocket = await websockets.connect(self.uri)
            self.connected = True
            print("서버와 연결을 시도 중입니다.")

            # 로그인 패킷
            param = {
                'trnm': 'LOGIN',
                'token': access_token
            }

            print('실시간 시세 서버로 로그인 패킷을 전송합니다.')
            # 웹소켓 연결 시 로그인 정보 전달
            await self.send_message(message=param)

        except Exception as e:
            print(f'Connection error: {e}')
            self.connected = False


    async def send_message(self, message):
        if not self.connected:
            await self.connect()  # 연결이 끊어졌다면 재연결
        if self.connected:
            # message가 문자열이 아니면 JSON으로 직렬화
            if not isinstance(message, str):
                message = json.dumps(message)

        await self.websocket.send(message)
        print(f'Message sent: {message}')


    async def receive_messages(self):
        while self.keep_running:
            try:
                # 서버로부터 수신한 메시지를 JSON 형식으로 파싱
                response = json.loads(await self.websocket.recv())

                # 메시지 유형이 LOGIN일 경우 로그인 시도 결과 체크
                if response.get('trnm') == 'LOGIN':
                    if response.get('return_code') != 0:
                        print('로그인 실패하였습니다. : ', response.get('return_msg'))
                        await self.disconnect()
                    else:
                        print('로그인 성공하였습니다.')

                # 메시지 유형이 PING일 경우 수신값 그대로 송신
                elif response.get('trnm') == 'PING':
                    await self.send_message(response)

                if response.get('trnm') != 'PING':
                    print(f'실시간 시세 서버 응답 수신: {response}')

            except websockets.ConnectionClosed:
                print('Connection closed by the server')
                self.connected = False
                await self.websocket.close()


    #웹소켓 실행
    async def run(self):
        await self.connect()
        await self.receive_messages()


    #웹소켓 종료
    async def disconnect(self):
        self.keep_running = False
        if self.connected and self.websocket:
            await self.websocket.close()
            self.connected = False
            print('Disconnected from WebSocket server')





