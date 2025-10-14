# ===============================
# file: auth.py
# ===============================
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import requests


@dataclass
class KiwoomAuth:    
    _access_token : str = "토근을 발급하쇼!" 
    # """키움 REST API 액세스 토큰 발급/갱신 및 공통 헤더 제공."""
    def __init__(self, akey,apsec, burl):

        self.app_key = akey
        self.app_secret = apsec
        self.base_url = burl
        self._access_token = self._issue_token()        

    # ---------------- private ----------------    
    def _issue_token(self):
        url = self.base_url + "/oauth2/token"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.app_secret,
        }

        resp = requests.post(url, headers = {"Content-Type": "application/json;charset=UTF-8"}, json = payload, timeout=(5,30))
        if resp.status_code >= 400:
            raise RuntimeError(f"토큰 발급 실패 HTTP {resp.status_code}: {resp.text}")
        else:
            data = resp.json()            
            return data.get("token")

            
            
        
        