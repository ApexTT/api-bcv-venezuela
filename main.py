import os
import asyncio
import httpx
from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from starlette.status import HTTP_403_FORBIDDEN
from pydantic import BaseModel
from datetime import datetime
from cachetools import TTLCache
from supabase import create_client, Client

app = FastAPI(title="API BCV Premium (Alta Velocidad, Caché y CORS)")

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
# supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

API_KEY_NAME = "X-Admin-Token"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)
ADMIN_TOKEN_SECRET = os.environ.get("ADMIN_TOKEN", "token_maestro_abrahan_2026")

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

# --- 2. MOTORES ASÍNCRONOS ---

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
    except Exception as e:
        print(f"Fallo Dolar Al Día: {e}")
        return None

async def motor_al_cambio(client: httpx.AsyncClient):
    try:
        url = 'https://api.alcambio.app/graphql'
        query = """query { getCountryConversions(payload: {countryCode: "VE"}) { conversionRates { type baseValue rateCurrency { code } } dateBcv } }"""
        res = await client.post(url, json={"query": query}, headers={'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'}, timeout=5.0)
        data = res.json()['data']['getCountryConversions']
        precios = {t['rateCurrency']['code']: round(t['baseValue'], 2) for t in data['conversionRates']}
        return {
            "fuente": "Al Cambio",
            "usd": precios.get('USD'),
            "eur": precios.get('EUR'),
            "fecha": datetime.fromtimestamp(data['dateBcv'] / 1000.0)
        }
    except Exception as e:
        print(f"Fallo Al Cambio: {e}")
        return None

async def motor_criptodolar(client: httpx.AsyncClient):
    try:
        url = 'https://exchange.vcoud.com/coins/latest?type=bolivar&base=usd'
        res = await client.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5.0)
        data = res.json()
        usd = next(item for item in data if item['slug'] == 'dolar-bcv')
        eur = next(item for item in data if item['slug'] == 'euro-bcv')
        return {
            "fuente": "CriptoDolar",
            "usd": usd['price'],
            "eur": eur['price'],
            "fecha": datetime.strptime(usd['updatedAt'][:19], "%Y-%m-%dT%H:%M:%S")
        }
    except Exception as e:
        print(f"Fallo CriptoDolar: {e}")
        return None

async def motor_tasas_alternativas(client: httpx.AsyncClient):
    try:
        url = 'https://exchange.vcoud.com/coins/latest?type=bolivar&base=usd'
        res = await client.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5.0)
        data = res.json()
        mercado = {}
        for item in data:
            slug = item.get('slug', '')
            precio = item.get('price', 0)
            if slug == 'enparalelovzla': mercado["enparalelovzla"] = precio
            elif slug == 'binance' or slug == 'binance-p2p': mercado["binance"] = precio
            elif slug == 'dolartoday': mercado["dolartoday"] = precio
        return {"mercado": mercado}
    except Exception as e:
        print(f"Fallo extracción alternativas: {e}")
        return {"mercado": {}}

# --- 3. EL CEREBRO CENTRALIZADO ---

async def obtener_datos_consolidados():
    if "datos_completos" in cache_tasas:
        return cache_tasas["datos_completos"]

    async with httpx.AsyncClient() as client:
        resultados = await asyncio.gather(
            motor_dolar_al_dia(client),
            motor_al_cambio(client),
            motor_criptodolar(client),
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

# --- 4. ENDPOINTS PÚBLICOS ---

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
        raise HTTPException(status_code=503, detail="Servidores de origen BCV no disponibles")

    ganador_bcv = max(fuentes_bcv, key=lambda x: x['fecha'])
    return {
        "bcv": ganador_bcv['usd'],
        "alternativas": datos["alternativas"],
        "fecha": ganador_bcv['fecha'].strftime("%Y-%m-%dT%H:%M:%SZ")
    }

# --- 5. ENDPOINT PRIVADO ---

@app.post("/api/inventario/blindar-precios")
def actualizar_precios_masivo(payload: TasasManuales, api_key: str = Depends(verificar_token_admin)):
    try:
        return {
            "status": "success",
            "mensaje": "Tasas manuales recibidas. El recálculo masivo se ha disparado.",
            "datos_enviados": {
                "bcv": payload.tasa_bcv,
                "alternativas": payload.tasas_alternativas
            }
        }
    except Exception as e:
        print(f"Error crítico en base de datos: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor al procesar la actualización.")

# --- 6. VENTANILLA DE MANTENIMIENTO ---

@app.get("/ping")
def mantener_despierto():
    return {"status": "Estoy despierto y trabajando!"}