import requests
import traceback
from fastapi import FastAPI, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from starlette.status import HTTP_403_FORBIDDEN, HTTP_429_TOO_MANY_REQUESTS
from datetime import datetime, date

app = FastAPI(title="API BCV Premium")

# ==========================================
# 1. BASE DE DATOS DE CLIENTES (Facturación)
# ==========================================
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

# Usamos números enteros para los límites individuales
CLIENTES_AUTORIZADOS = {
    "admin_master_123": {"nombre": "Administrador Principal", "limite": 100000}, 
    "burger_vip_456": {"nombre": "A Q' Abrahan Burguer VIP", "limite": 1000},
    "burger_vip_4567": {"nombre": "A Q' Abrahan Burguer Básico", "limite": 100},
    "cliente_prueba_789": {"nombre": "Cliente Básico 1", "limite": 100},
}

# ==========================================
# 2. MOTOR DE LÍMITES ESTABLE (Hecho a medida, sin SlowAPI)
# ==========================================
REGISTRO_CONSULTAS = {}

async def verificar_api_key_y_limite(api_key: str = Security(api_key_header)):
    # 1. Verificar si la llave existe en la base de datos
    if not api_key or api_key not in CLIENTES_AUTORIZADOS:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN, 
            detail="Acceso denegado. Adquiere tu plan contactando a ApexTT."
        )
    
    # 2. Control del límite diario por cliente
    hoy = date.today().isoformat()
    
    # Si es su primera consulta del día, iniciamos su contador
    if api_key not in REGISTRO_CONSULTAS or REGISTRO_CONSULTAS[api_key]["fecha"] != hoy:
        REGISTRO_CONSULTAS[api_key] = {"fecha": hoy, "contador": 0}
        
    limite_diario = CLIENTES_AUTORIZADOS[api_key]["limite"]
    
    # 3. Bloqueo automático si se pasó de su plan (Error 429)
    if REGISTRO_CONSULTAS[api_key]["contador"] >= limite_diario:
        raise HTTPException(
            status_code=HTTP_429_TOO_MANY_REQUESTS, 
            detail=f"Límite diario de {limite_diario} consultas agotado."
        )
        
    # 4. Sumamos 1 a su consumo y lo dejamos pasar
    REGISTRO_CONSULTAS[api_key]["contador"] += 1
    
    return api_key

# ==========================================
# 3. MOTORES DE EXTRACCIÓN 
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
# 4. RUTA PRINCIPAL 
# ==========================================
# Inyectamos nuestra función personalizada en Depends
@app.get("/api/v1/tasas")
def obtener_tasas(api_key: str = Depends(verificar_api_key_y_limite)): 
    try:
        cliente = CLIENTES_AUTORIZADOS[api_key]
        
        fuentes = [f for f in [motor_dolar_al_dia(), motor_al_cambio(), motor_criptodolar()] if f]
        if not fuentes:
            raise HTTPException(status_code=503, detail="Servidores de origen no disponibles.")

        ganador = max(fuentes, key=lambda x: x['fecha'])
        
        return {
            "status": "success",
            "cliente": cliente["nombre"],
            "plan_limite": cliente["limite"], 
            "consultas_usadas": REGISTRO_CONSULTAS[api_key]["contador"], 
            "fecha_actualizacion": ganador['fecha'].strftime("%d/%m/%Y %I:%M %p"),
            "fuente_oficial": ganador['fuente'],
            "tasas": {
                "USD": ganador['usd'],
                "EUR": ganador['eur']
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print("ERROR INTERNO:", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Falla interna: {str(e)}")

# ==========================================
# 5. VENTANILLA PÚBLICA (UptimeRobot)
# ==========================================
@app.get("/ping")
def mantener_despierto():
    return {"status": "¡El servidor está despierto y trabajando!"}