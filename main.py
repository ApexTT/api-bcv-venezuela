import requests
from fastapi import FastAPI, Depends, HTTPException, Security, Request
from fastapi.security.api_key import APIKeyHeader
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.status import HTTP_403_FORBIDDEN
from datetime import datetime

app = FastAPI(title="API BCV Premium (Protegida y Limitada)")

# ==========================================
# 1. BASE DE DATOS DE CLIENTES Y PLANES
# ==========================================
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

# Ahora guardamos el nombre Y el límite de consultas por día
CLIENTES_AUTORIZADOS = {
    # Llave Maestra (Para ti)
    "admin_master_123": {"nombre": "Administrador", "limite": "100000/day"}, 
    
    # Plan Profesional ($15/mes)
    "burger_vip_456": {"nombre": "A Q' Abrahan Burguer", "limite": "1000/day"},
    
    # Plan Básico ($5/mes)
    "cliente_prueba_789": {"nombre": "Cliente Básico 1", "limite": "100/day"},
    "farmacia_salud_001": {"nombre": "Farmacia La Salud", "limite": "100/day"},
    "burger_vip_4567": {"nombre": "A Q' Abrahan Burguer", "limite": "100/day"},
}

# ==========================================
# 2. SISTEMA DE CONTEO Y LÍMITES (SLOWAPI)
# ==========================================
# Función para saber con qué llave están entrando y contar sus visitas
def obtener_llave_para_limite(request: Request):
    return request.headers.get("X-API-Key", get_remote_address(request))

# Función que revisa el diccionario y aplica el límite exacto del plan
def obtener_limite_del_plan(request: Request):
    api_key = request.headers.get("X-API-Key")
    cliente = CLIENTES_AUTORIZADOS.get(api_key)
    if cliente:
        return cliente["limite"]
    return "1/minute" # Si no tiene llave válida, lo bloqueamos rápido

# Iniciamos el contador
limiter = Limiter(key_func=obtener_llave_para_limite)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# El Guardia que verifica si la llave existe
async def verificar_api_key(api_key: str = Security(api_key_header)):
    if api_key in CLIENTES_AUTORIZADOS:
        return api_key 
    raise HTTPException(
        status_code=HTTP_403_FORBIDDEN, 
        detail="Acceso denegado. Adquiere tu plan mensual contactando a ApexTT al WhatsApp: +58 424-6821872"
    )

# ==========================================
# 3. MOTORES DE EXTRACCIÓN (Igual que antes)
# ==========================================
def motor_dolar_al_dia():
    try:
        url = 'https://api.dolaraldiavzla.com/api/v1/dollar?page=bcv'
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5).json()
        monitor = res['monitors']
        return {"fuente": "Dolar Al Día", "usd": monitor['usd']['price'], "eur": monitor['eur']['price'], "fecha": datetime.strptime(monitor['usd']['last_update'], "%d/%m/%Y, %I:%M %p")}
    except: return None

def motor_al_cambio():
    try:
        url = 'https://api.alcambio.app/graphql'
        query = """query { getCountryConversions(payload: {countryCode: "VE"}) { conversionRates { type baseValue rateCurrency { code } } dateBcv } }"""
        res = requests.post(url, json={"query": query}, timeout=5).json()['data']['getCountryConversions']
        precios = {t['rateCurrency']['code']: round(t['baseValue'], 2) for t in res['conversionRates']}
        return {"fuente": "Al Cambio", "usd": precios.get('USD'), "eur": precios.get('EUR'), "fecha": datetime.fromtimestamp(res['dateBcv'] / 1000.0)}
    except: return None

def motor_criptodolar():
    try:
        url = 'https://exchange.vcoud.com/coins/latest?type=bolivar&base=usd'
        res = requests.get(url, timeout=5).json()
        usd = next(item for item in res if item['slug'] == 'dolar-bcv')
        eur = next(item for item in res if item['slug'] == 'euro-bcv')
        return {"fuente": "CriptoDolar", "usd": usd['price'], "eur": eur['price'], "fecha": datetime.strptime(usd['updatedAt'][:19], "%Y-%m-%dT%H:%M:%S")}
    except: return None

# ==========================================
# 4. RUTA PRINCIPAL (CON CANDADO Y CONTADOR)
# ==========================================
@app.get("/api/v1/tasas")
@limiter.limit(obtener_limite_del_plan) # <--- Aquí entra en acción el contador
def obtener_tasas(request: Request, api_key: str = Depends(verificar_api_key)):
    cliente = CLIENTES_AUTORIZADOS[api_key]
    
    fuentes = [f for f in [motor_dolar_al_dia(), motor_al_cambio(), motor_criptodolar()] if f]
    if not fuentes:
        return {"error": "Servidores de origen no disponibles"}

    ganador = max(fuentes, key=lambda x: x['fecha'])
    
    return {
        "status": "success",
        "cliente": cliente["nombre"],
        "plan_limite": cliente["limite"], # Le recordamos su plan en la respuesta
        "fecha_actualizacion": ganador['fecha'].strftime("%d/%m/%Y %I:%M %p"),
        "fuente_oficial": ganador['fuente'],
        "tasas": {
            "USD": ganador['usd'],
            "EUR": ganador['eur']
        }
    }

# ==========================================
# 5. VENTANILLA PÚBLICA (Para UptimeRobot)
# ==========================================
@app.get("/ping")
def mantener_despierto():
    return {"status": "¡El servidor está despierto y trabajando al 100%!"}