import requests
import json
from fastapi import FastAPI
from datetime import datetime

# 1. Creamos nuestro servidor API
app = FastAPI(title="API BCV Inteligente")

# --- MOTORES DE EXTRACCIÓN ---

def motor_dolar_al_dia():
    try:
        url = 'https://api.dolaraldiavzla.com/api/v1/dollar?page=bcv'
        headers = {'User-Agent': 'Mozilla/5.0'}
        # timeout=5 significa que si la página tarda más de 5 segundos, abortamos y seguimos
        res = requests.get(url, headers=headers, timeout=5) 
        datos = res.json()
        
        precio = datos['monitors']['usd']['price']
        # La fecha viene así: '20/03/2026, 12:00 AM'
        fecha_str = datos['monitors']['usd']['last_update']
        fecha_obj = datetime.strptime(fecha_str, "%d/%m/%Y, %I:%M %p")
        
        return {"fuente": "Dolar Al Día", "precio": precio, "fecha": fecha_obj}
    except Exception as e:
        print(f"Fallo Dolar Al Día: {e}")
        return None

def motor_al_cambio():
    try:
        url = 'https://api.alcambio.app/graphql'
        headers = {'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'}
        query = """query getCountryConversions($countryCode: String!) { getCountryConversions(payload: {countryCode: $countryCode}) { conversionRates { type baseValue } dateBcv } }"""
        
        res = requests.post(url, json={"query": query, "variables": {"countryCode": "VE"}}, headers=headers, timeout=5)
        datos = res.json()['data']['getCountryConversions']
        
        # Buscamos el SECONDARY
        precio = 0
        for tasa in datos['conversionRates']:
            if tasa['type'] == 'SECONDARY':
                precio = round(tasa['baseValue'], 2)
                break
                
        fecha_obj = datetime.fromtimestamp(datos['dateBcv'] / 1000.0)
        
        return {"fuente": "Al Cambio", "precio": precio, "fecha": fecha_obj}
    except Exception as e:
        print(f"Fallo Al Cambio: {e}")
        return None

def motor_criptodolar():
    try:
        url = 'https://exchange.vcoud.com/coins/latest?type=bolivar&base=usd'
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        datos = res.json()[0]
        
        precio = datos['price']
        # La fecha viene así: '2026-03-19T00:13:30.183Z' (Cortamos los primeros 19 caracteres)
        fecha_obj = datetime.strptime(datos['updatedAt'][:19], "%Y-%m-%dT%H:%M:%S")
        
        return {"fuente": "CriptoDolar", "precio": precio, "fecha": fecha_obj}
    except Exception as e:
        print(f"Fallo CriptoDolar: {e}")
        return None

# --- EL CEREBRO DE LA API ---

@app.get("/api/v1/bcv")
def obtener_tasa_inteligente():
    resultados = []
    
    # Encendemos los 3 motores
    dato1 = motor_dolar_al_dia()
    if dato1 is not None: resultados.append(dato1)
        
    dato2 = motor_al_cambio()
    if dato2 is not None: resultados.append(dato2)
        
    dato3 = motor_criptodolar()
    if dato3 is not None: resultados.append(dato3)
    
    # Verificamos si todos fallaron (casi imposible, pero hay que preverlo)
    if len(resultados) == 0:
        return {"error": "Todos los servidores de origen están caídos."}
        
    # La magia: Comparamos las fechas para elegir al ganador
    tasa_ganadora = resultados[0] # Asumimos temporalmente que el primero ganó
    
    for dato in resultados:
        # Si la fecha de este dato es mayor (más reciente) que la del ganador actual, lo reemplazamos
        if dato["fecha"] > tasa_ganadora["fecha"]:
            tasa_ganadora = dato
            
    # Entregamos el paquete final limpio y formateado a tu aplicación
    return {
        "moneda": "USD_BCV",
        "precio": tasa_ganadora["precio"],
        "fuente_ganadora": tasa_ganadora["fuente"],
        # Convertimos la fecha ganadora a texto normal para enviarla por internet
        "fecha_actualizacion": tasa_ganadora["fecha"].strftime("%Y-%m-%d %I:%M %p"),
        "motores_activos": len(resultados)
    }