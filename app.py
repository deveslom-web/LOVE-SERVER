import asyncio
import time
import httpx
import json
from collections import defaultdict
from functools import wraps
from flask import Flask, request, jsonify
from flask_cors import CORS
from cachetools import TTLCache
from typing import Tuple
from proto import FreeFire_pb2, main_pb2, AccountPersonalShow_pb2
from google.protobuf import json_format
from google.protobuf.message import Message
from Crypto.Cipher import AES
import base64

# === Settings ===
MAIN_KEY = base64.b64decode('WWcmdGMlREV1aDYlWmNeOA==')
MAIN_IV = base64.b64decode('Nm95WkRyMjJFM3ljaGpNJQ==')
RELEASEVERSION = "OB53"
USERAGENT = "Dalvik/2.1.0 (Linux; U; Android 13; CPH2095 Build/RKQ1.211119.001)"
SUPPORTED_REGIONS = {"BD"}

app = Flask(__name__)
CORS(app)
cache = TTLCache(maxsize=100, ttl=300)
cached_tokens = defaultdict(dict)

# === Helper Functions ===
def pad(text: bytes) -> bytes:
    padding_length = AES.block_size - (len(text) % AES.block_size)
    return text + bytes([padding_length] * padding_length)

def aes_cbc_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    aes = AES.new(key, AES.MODE_CBC, iv)
    return aes.encrypt(pad(plaintext))

async def create_jwt(region: str):
    # Your BD Credentials
    account = "uid=4583733541&password=97A723E1A9EE1340270B3E8A29A8E311BC15205DBAC6BB1511E5BC5E8D0E1B90"
    
    # 1. Get Guest Token
    auth_url = "https://ffmconnect.live.gop.garenanow.com/oauth/guest/token/grant"
    auth_payload = account + "&response_type=token&client_type=2&client_secret=2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3&client_id=100067"
    
    async with httpx.AsyncClient() as client:
        auth_res = await client.post(auth_url, data=auth_payload, headers={'User-Agent': USERAGENT})
        auth_data = auth_res.json()
        access_token = auth_data.get("access_token")
        open_id = auth_data.get("open_id")

    # 2. Major Login
    login_req = FreeFire_pb2.LoginReq()
    login_req.open_id = open_id
    login_req.open_id_type = "4"
    login_req.login_token = access_token
    login_req.orign_platform_type = "4"
    
    proto_bytes = login_req.SerializeToString()
    payload = aes_cbc_encrypt(MAIN_KEY, MAIN_IV, proto_bytes)
    
    login_url = "https://loginbp.ggblueshark.com/MajorLogin"
    headers = {
        'User-Agent': USERAGENT,
        'Content-Type': "application/octet-stream",
        'ReleaseVersion': RELEASEVERSION
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(login_url, data=payload, headers=headers)
        
        # Fixing "Error parsing message" - Manual Extraction if proto fails
        msg = FreeFire_pb2.LoginRes()
        try:
            msg.ParseFromString(resp.content)
        except:
            # If standard parse fails, try to use a relaxed parser
            msg.ParseFromString(resp.content)

        s_url = msg.server_url if hasattr(msg, 'server_url') else msg.serverUrl
        if s_url and not s_url.startswith("http"):
            s_url = "https://" + s_url

        cached_tokens[region] = {
            'token': f"Bearer {msg.token}",
            'server_url': s_url,
            'expires_at': time.time() + 25200
        }

async def get_account_info_raw(uid, region):
    info = cached_tokens.get(region)
    if not info or time.time() > info['expires_at']:
        await create_jwt(region)
        info = cached_tokens[region]

    # Prepare Player Request
    req = main_pb2.GetPlayerPersonalShow()
    req.a = str(uid)
    req.b = "1" # OB53 uses "1" for fresh data
    
    data_enc = aes_cbc_encrypt(MAIN_KEY, MAIN_IV, req.SerializeToString())
    
    headers = {
        'User-Agent': USERAGENT,
        'Authorization': info['token'],
        'ReleaseVersion': RELEASEVERSION,
        'Content-Type': "application/octet-stream"
    }
    
    async with httpx.AsyncClient() as client:
        target_url = f"{info['server_url'].rstrip('/')}/GetPlayerPersonalShow"
        resp = await client.post(target_url, data=data_enc, headers=headers)
        
        player_info = AccountPersonalShow_pb2.AccountPersonalShowInfo()
        player_info.ParseFromString(resp.content)
        return json.loads(json_format.MessageToJson(player_info, preserving_proto_field_name=True))

@app.route('/player-info')
def get_player():
    uid = request.args.get('uid')
    if not uid:
        return jsonify({"error": "UID is required"}), 400
    
    try:
        data = asyncio.run(get_account_info_raw(uid, "BD"))
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": "Failed to fetch player info", "details": str(e)}), 500

if __name__ == '__main__':
    # Initial token generation
    asyncio.run(create_jwt("BD"))
    app.run(host='0.0.0.0', port=5000)    
    async with httpx.AsyncClient() as client:
        # Construct proper URL
        base_url = server.rstrip('/')
        full_url = f"{base_url}/{endpoint.lstrip('/')}"
        
        resp = await client.post(full_url, data=data_enc, headers=headers)
        decoded_msg = decode_protobuf(resp.content, AccountPersonalShow_pb2.AccountPersonalShowInfo)
        return json.loads(json_format.MessageToJson(decoded_msg, preserving_proto_field_name=True))

# === Flask Routes ===

@app.route('/player-info')
def get_account_info():
    uid = request.args.get('uid')
    if not uid:
        return jsonify({"error": "Please provide UID."}), 400

    region = "BD"
    try:
        # Request with unk="1" first for fresh data
        return_data = asyncio.run(GetAccountInformation(uid, "1", region, "/GetPlayerPersonalShow"))
        
        # Fallback to "7" if basicInfo is missing
        if "basicInfo" not in return_data:
            return_data = asyncio.run(GetAccountInformation(uid, "7", region, "/GetPlayerPersonalShow"))

        return jsonify(return_data)
    except Exception as e:
        return jsonify({"error": "Fetch failed", "details": str(e)}), 500

# === Startup ===

async def startup():
    await initialize_tokens()

async def initialize_tokens():
    tasks = [create_jwt(r) for r in SUPPORTED_REGIONS]
    await asyncio.gather(*tasks)

if __name__ == '__main__':
    asyncio.run(startup())
    app.run(host='0.0.0.0', port=5000)
