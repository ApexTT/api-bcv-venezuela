import requests
from fastapi import FastAPI
from datetime import datetime

app = FastAPI(title="API BCV Premium (USD/EUR)")

# --- MOTORES ACTUALIZADOS ---

def motor_dolar_al_dia():
    try:
        url = 'https://api.dolaraldiavzla.com/api/v1/dollar?page=bcv'
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5).json()
        monitor = res['monitors']
        
        return {
            "fuente": "Dolar Al Día",
            "usd": monitor['usd']['price'],
            "eur": monitor['eur']['price'],
            "fecha": datetime.strptime(monitor['usd']['last_update'], "%d/%m/%Y, %I:%M %p")
        }
    except: return None

def motor_al_cambio():
    try:
        url = 'https://api.alcambio.app/graphql'
        query = """query { getCountryConversions(payload: {countryCode: "VE"}) { 
            conversionRates { type baseValue rateCurrency { code } } 
            dateBcv } }"""
        res = requests.post(url, json={"query": query}, timeout=5).json()['data']['getCountryConversions']
        
        precios = {t['rateCurrency']['code']: round(t['baseValue'], 2) for t in res['conversionRates']}
        return {
            "fuente": "Al Cambio",
            "usd": precios.get('USD'),
            "eur": precios.get('EUR'),
            "fecha": datetime.fromtimestamp(res['dateBcv'] / 1000.0)
        }
    except: return None

def motor_criptodolar():
    try:
        url = 'https://exchange.vcoud.com/coins/latest?type=bolivar&base=usd'
        res = requests.get(url, timeout=5).json()
        
        # Buscamos en la lista por el "slug"
        usd = next(item for item in res if item['slug'] == 'dolar-bcv')
        eur = next(item for item in res if item['slug'] == 'euro-bcv')
        
        return {
            "fuente": "CriptoDolar",
            "usd": usd['price'],
            "eur": eur['price'],
            "fecha": datetime.strptime(usd['updatedAt'][:19], "%Y-%m-%dT%H:%M:%S")
        }
    except: return None

# --- EL CEREBRO ---

@app.get("/api/v1/tasas")
def obtener_tasas():
    fuentes = [f for f in [motor_dolar_al_dia(), motor_al_cambio(), motor_criptodolar()] if f]
    
    if not fuentes:
        return {"error": "Servidores de origen no disponibles"}

    # Ganador por fecha más reciente
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