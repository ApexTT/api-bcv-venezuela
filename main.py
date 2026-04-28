import os
import asyncio
import httpx
import re
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from starlette.status import HTTP_403_FORBIDDEN
from pydantic import BaseModel
from datetime import datetime
from cachetools import TTLCache
from supabase import create_client, Client
from bs4 import BeautifulSoup

app = FastAPI(title="API BCV Premium (Redundancia Total + Binance P2P)")

# --- 0. CONFIGURACIÓN CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"], 
)

# --- 1. CONFIGURACIÓN DE SEGURIDAD Y MEMORIA ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://tu-proyecto.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "tu-anon-key-aqui")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

API_KEY_NAME = "X-Admin-Token"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)
ADMIN_TOKEN_SECRET = os.environ.get("ADMIN_TOKEN", "S29F040RCA2018#")

cache_tasas = TTLCache(maxsize=1, ttl=600)

async def verificar_token_admin(api_key_header: str = Security(api_key_header)):
    if api_key_header == ADMIN_TOKEN_SECRET:
        return api_key_header
    raise HTTPException(
        status_code=HTTP_403_FORBIDDEN, 
        detail="Acceso denegado. Credenciales de administrador inválidas."
    )

class TasasManuales(BaseModel):
    tasa_bcv: float
    tasas_alternativas: dict

# ==========================================
# FASE 1: MOTORES DE REDUNDANCIA BCV (Los 3 originales)
# ==========================================

async def motor_dolar_al_dia(client: httpx.AsyncClient):
    try:
        url = 'https://api.dolaraldiavzla.com/api/v1/dollar?page=bcv'
        res = await client.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5.0)
        monitor = res.json()['monitors']
        return {
            "fuente": "Dolar Al Día",
            "usd": monitor['usd']['price'],
            "fecha": datetime.strptime(monitor['usd']['last_update'], "%d/%m/%Y, %I:%M %p")
        }
    except: return None

async def motor_al_cambio_bcv(client: httpx.AsyncClient):
    try:
        url = 'https://api.alcambio.app/graphql'
        query = """query { getCountryConversions(payload: {countryCode: "VE"}) { conversionRates { type baseValue rateCurrency { code } } dateBcv } }"""
        res = await client.post(url, json={"query": query}, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5.0)
        data = res.json()['data']['getCountryConversions']
        precios = {t['rateCurrency']['code']: round(t['baseValue'], 2) for t in data['conversionRates']}
        return {
            "fuente": "Al Cambio",
            "usd": precios.get('USD'),
            "fecha": datetime.fromtimestamp(data['dateBcv'] / 1000.0)
        }
    except: return None

async def motor_criptodolar_bcv(client: httpx.AsyncClient):
    try:
        url = 'https://exchange.vcoud.com/coins/latest?type=bolivar&base=usd'
        res = await client.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5.0)
        usd = next(item for item in res.json() if item['slug'] == 'dolar-bcv')
        return {
            "fuente": "CriptoDolar",
            "usd": usd['price'],
            "fecha": datetime.strptime(usd['updatedAt'][:19], "%Y-%m-%dT%H:%M:%S")
        }
    except: return None

# ==========================================
# FASE 2: MOTORES DE MERCADO ALTERNATIVO (Binance + Scraping)
# ==========================================

async def motor_binance_p2p(client: httpx.AsyncClient):
    try:
        url = "https://p2p.binance.com/bapi/c2c/v2/public/c2c/adv/search"
        payload = {
            "asset": "USDT", "fiat": "VES", "tradeType": "BUY",
            "publisherType": "merchant", "rows": 5, "page": 1
        }
        res = await client.post(url, json=payload, timeout=5.0)
        if res.status_code == 200:
            precios = [float(adv['adv']['price']) for adv in res.json().get('data', [])]
            if precios: return round(sum(precios) / len(precios), 2)
    except: return None

async def motor_exchange_monitor(client: httpx.AsyncClient):
    try:
        url = 'https://exchangemonitor.net/calculadora/venezuela/dolar-enparalelovzla'
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
        res = await client.get(url, headers=headers, timeout=5.0)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            precio_tag = soup.find("h2", string=re.compile(r'\d+,\d+')) or soup.find(class_=re.compile("precio"))
            if precio_tag:
                return float(re.search(r'(\d+,\d+)', precio_tag.get_text()).group(1).replace(',', '.'))
    except: return None

async def motor_tasas_alternativas(client: httpx.AsyncClient):
    mercado = {}
    
    # 1. Binance P2P Directo
    mercado["binance"] = await motor_binance_p2p(client)

    # 2. Paralelo vía Scraping
    paralelo = await motor_exchange_monitor(client)
    
    # 3. Respaldo Paralelo si falla el Scraping
    if not paralelo:
        try:
            url_al = 'https://api.alcambio.app/graphql'
            query = """query { getCountryConversions(payload: {countryCode: "VE"}) { conversionRates { type baseValue rateCurrency { code } } } }"""
            res_al = await client.post(url_al, json={"query": query}, timeout=5.0)
            tasas = res_al.json()['data']['getCountryConversions']['conversionRates']
            paralelo = next((t['baseValue'] for t in tasas if t['type'] == 'PARALLEL'), None)
        except: pass

    mercado["enparalelovzla"] = paralelo
    return {"mercado": mercado}

# ==========================================
# FASE 3: EL CEREBRO CENTRALIZADO Y ENDPOINTS
# ==========================================

async def obtener_datos_consolidados():
    if "datos_completos" in cache_tasas:
        return cache_tasas["datos_completos"]

    async with httpx.AsyncClient() as client:
        resultados = await asyncio.gather(
            motor_dolar_al_dia(client),
            motor_al_cambio_bcv(client),
            motor_criptodolar_bcv(client),
            motor_tasas_alternativas(client)
        )

    bcv1, bcv2, bcv3, alt = resultados
    fuentes_bcv = [f for f in [bcv1, bcv2, bcv3] if f]

    datos = {
        "fuentes_bcv": fuentes_bcv,
        "alternativas": alt["mercado"] if alt else {}
    }

    if fuentes_bcv:
        cache_tasas["datos_completos"] = datos

    return datos

@app.get("/api/v2/tasas")
async def obtener_tasas_v2():
    datos = await obtener_datos_consolidados()
    fuentes_bcv = datos["fuentes_bcv"]
    
    if not fuentes_bcv:
        raise HTTPException(status_code=503, detail="Servidores BCV no disponibles")

    ganador_bcv = max(fuentes_bcv, key=lambda x: x['fecha'])
    return {
        "bcv": ganador_bcv['usd'],
        "alternativas": datos["alternativas"],
        "fecha": ganador_bcv['fecha'].strftime("%Y-%m-%dT%H:%M:%SZ")
    }

@app.post("/api/inventario/blindar-precios")
def actualizar_precios_masivo(payload: TasasManuales, api_key: str = Depends(verificar_token_admin)):
    try:
        tasa_paralelo = payload.tasas_alternativas.get("enparalelovzla", payload.tasa_bcv)
        respuesta = supabase.rpc(
            "ejecutar_blindaje_financiero", 
            {"nueva_tasa_bcv": payload.tasa_bcv, "nueva_tasa_paralelo": tasa_paralelo}
        ).execute()
        return {"status": "success", "mensaje": "Recálculo masivo ejecutado."}
    except Exception as e:
        print(f"Error base de datos: {e}")
        raise HTTPException(status_code=500, detail="Error en base de datos.")

@app.get("/ping")
def mantener_despierto():
    return {"status": "Online"}