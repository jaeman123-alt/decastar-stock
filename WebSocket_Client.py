# =====================================
# file: WebSocketClient.py
# =====================================
from __future__ import annotations

import asyncio
import websockets
import json
import requests

from tools import *

class WebSocketClient:
    def __init__(self, uri, access_token):                
        tprint("[WebSocketClient] 시작")

        self.uri = uri   # 연결한 서버의 주소
        self.access_token = access_token
        self.websocket = None  # 실제 웹소켓 연결을 관리하는 변수
        self.connected = False # 연결상태 (True면 연결됨)
        self.keep_running = True
        self.condition_data = []  # 조건식 종목코드 저장용

    async def connect(self):
        try:
            self.websocket = await websockets.connect(self.uri)
            self.connected = True
            print("서버와 연결을 시도 중입니다.")

            # 로그인 패킷
            param = {
                'trnm': 'LOGIN',
                'token': self.access_token
            }
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

                else:
                    print(f'수신 메시지: {response}')

            except websockets.ConnectionClosed:
                print('Connection closed by the server')
                self.connected = False
                await self.websocket.close()


    #웹소켓 실행
    async def run(self):
        print('websocket run.')
        await self.connect()
        await self.receive_messages()
        await asyncio.sleep(2)  # 로그인 완료 대기


    #웹소켓 종료
    async def disconnect(self):
        self.keep_running = False
        if self.connected and self.websocket:
            await self.websocket.close()
            self.connected = False
            print('Disconnected from WebSocket server')

    async def websocket_test(self):
        print('websocket CNSRLST.')
        websocket_task = asyncio.create_task(self.send_message({'trnm': 'CNSRLST'})) 

        # 수신 작업이 종료될 때까지 대기
        await websocket_task

        # websocket 종료
        await self.disconnect()
        await websocket_task



