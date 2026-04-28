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

app = FastAPI(title="API BCV Premium (Redundancia Total + Euro + Respaldos)")

# --- 0. CONFIGURACIÓN CORS (BLINDADA MULTI-SITIO) ---

# Lista de dominios autorizados para consumir la API
ORIGINES_PERMITIDOS = [
    "https://monitor-tasas.alblizfranco92.workers.dev",  # Monitor principal
    "https://repuestos-mga.vercel.app",                 # Catálogo de repuestos
    "https://aq-abrahanburguer.netlify.app",            # Página de Abrahan
    "http://localhost:5500",                            # Entorno de desarrollo local
    "http://127.0.0.1:5500"                             # Variante local
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINES_PERMITIDOS, 
    allow_credentials=True,
    allow_methods=["GET", "POST"], 
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
# FASE 1: MOTORES DE REDUNDANCIA BCV (Con EURO)
# ==========================================

async def motor_dolar_al_dia(client: httpx.AsyncClient):
    try:
        url = 'https://api.dolaraldiavzla.com/api/v1/dollar?page=bcv'
        res = await client.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5.0)
        monitor = res.json()['monitors']
        return {
            "fuente": "Dolar Al Día",
            "usd": monitor['usd']['price'],
            "eur": monitor['eur']['price'],
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
            "eur": precios.get('EUR'),
            "fecha": datetime.fromtimestamp(data['dateBcv'] / 1000.0)
        }
    except: return None

async def motor_criptodolar_bcv(client: httpx.AsyncClient):
    try:
        url = 'https://exchange.vcoud.com/coins/latest?type=bolivar&base=usd'
        res = await client.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5.0)
        datos = res.json()
        usd = next(item for item in datos if item['slug'] == 'dolar-bcv')
        eur = next(item for item in datos if item['slug'] == 'euro-bcv')
        return {
            "fuente": "CriptoDolar",
            "usd": usd['price'],
            "eur": eur['price'],
            "fecha": datetime.strptime(usd['updatedAt'][:19], "%Y-%m-%dT%H:%M:%S")
        }
    except: return None

# ==========================================
# FASE 2: MOTORES DE MERCADO ALTERNATIVO (Triple Respaldo)
# ==========================================

async def motor_tasas_alternativas(client: httpx.AsyncClient):
    mercado = {"binance": None, "enparalelovzla": None}
    
    # --- 1. BLOQUE BINANCE ---
    try:
        url_bin = "https://p2p.binance.com/bapi/c2c/v2/public/c2c/adv/search"
        payload = {"asset": "USDT", "fiat": "VES", "tradeType": "BUY", "publisherType": "merchant", "rows": 5, "page": 1}
        res_bin = await client.post(url_bin, json=payload, timeout=5.0)
        if res_bin.status_code == 200:
            precios = [float(adv['adv']['price']) for adv in res_bin.json().get('data', [])]
            if precios: mercado["binance"] = round(sum(precios) / len(precios), 2)
    except: pass

    if not mercado.get("binance"):
        try:
            res_vc_bin = await client.get('https://exchange.vcoud.com/coins/latest?type=bolivar&base=usd', headers={'User-Agent': 'Mozilla/5.0'}, timeout=5.0)
            if res_vc_bin.status_code == 200:
                binance_data = next((item for item in res_vc_bin.json() if item.get('slug') in ['binance', 'binance-p2p']), None)
                if binance_data: mercado["binance"] = binance_data.get('price')
        except: pass

    if not mercado.get("binance"):
        try:
            res_dad_bin = await client.get('https://api.dolaraldiavzla.com/api/v1/dollar?page=binance', headers={'User-Agent': 'Mozilla/5.0'}, timeout=5.0)
            if res_dad_bin.status_code == 200:
                monitores = res_dad_bin.json().get('monitors', {})
                if 'binance' in monitores:
                    mercado["binance"] = monitores['binance']['price']
                elif 'usd' in monitores:
                    mercado["binance"] = monitores['usd']['price']
        except: pass

    # --- 2. BLOQUE PARALELO ---
    try:
        url_ex = 'https://exchangemonitor.net/calculadora/venezuela/dolar-enparalelovzla'
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
        res_ex = await client.get(url_ex, headers=headers, timeout=5.0)
        if res_ex.status_code == 200:
            soup = BeautifulSoup(res_ex.text, 'html.parser')
            precio_tag = soup.find("h2", string=re.compile(r'\d+,\d+')) or soup.find(class_=re.compile("precio"))
            if precio_tag:
                mercado["enparalelovzla"] = float(re.search(r'(\d+,\d+)', precio_tag.get_text()).group(1).replace(',', '.'))
    except: pass
    
    if not mercado.get("enparalelovzla"):
        try:
            res_da = await client.get('https://ve.dolarapi.com/v1/dolares/paralelo', timeout=5.0)
            if res_da.status_code == 200:
                mercado["enparalelovzla"] = res_da.json().get('promedio', None)
        except: pass

    if not mercado.get("enparalelovzla"):
        try:
            res_py = await client.get('https://pydolarvenezuela-api.vercel.app/api/v1/dollar?page=enparalelovzla', timeout=5.0)
            if res_py.status_code == 200:
                mercado["enparalelovzla"] = res_py.json()['monitors']['enparalelovzla']['price']
        except: pass

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

    mercado_final = alt["mercado"] if alt else {}
    if not mercado_final.get("binance"):
        mercado_final["binance"] = fuentes_bcv[0]['usd'] if fuentes_bcv else 0
    if not mercado_final.get("enparalelovzla"):
        mercado_final["enparalelovzla"] = fuentes_bcv[0]['usd'] if fuentes_bcv else 0

    datos = {
        "fuentes_bcv": fuentes_bcv,
        "alternativas": mercado_final
    }

    if fuentes_bcv:
        cache_tasas["datos_completos"] = datos

    return datos

@app.get("/api/v1/tasas")
async def obtener_tasas():
    datos = await obtener_datos_consolidados()
    fuentes = datos["fuentes_bcv"]
    
    if not fuentes:
        return {"error": "Servidores de origen no disponibles"}

    ganador = max(fuentes, key=lambda x: x['fecha'])
    return {
        "status": "success",
        "fecha_actualizacion": ganador['fecha'].strftime("%d/%m/%Y %I:%M %p"),
        "fuente_oficial": ganador['fuente'],
        "tasas": {
            "USD": ganador['usd'],
            "EUR": ganador['eur']
        },
        "motores_online": len(fuentes)
    }

@app.get("/api/v2/tasas")
async def obtener_tasas_v2():
    datos = await obtener_datos_consolidados()
    fuentes_bcv = datos["fuentes_bcv"]
    
    if not fuentes_bcv:
        raise HTTPException(status_code=503, detail="Servidores BCV no disponibles")

    ganador_bcv = max(fuentes_bcv, key=lambda x: x['fecha'])
    return {
        "bcv": ganador_bcv['usd'],
        "eur": ganador_bcv['eur'],
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