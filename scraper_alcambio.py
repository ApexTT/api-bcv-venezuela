import requests
import json
from datetime import datetime

url_api = 'https://api.alcambio.app/graphql'

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Content-Type': 'application/json' 
}

query_graphql = """
query getCountryConversions($countryCode: String!) {
  getCountryConversions(payload: {countryCode: $countryCode}) {
    conversionRates {
      type
      baseValue
    }
    dateBcv
  }
}
"""

payload = {
    "query": query_graphql,
    "variables": {"countryCode": "VE"}
}

print("Consultando la API de Al Cambio...\n")

respuesta = requests.post(url_api, json=payload, headers=headers)

if respuesta.status_code == 200:
    datos = respuesta.json()
    
    # 1. Extraemos la lista de tasas y la fecha (viajando por las ramas del diccionario)
    ramas_principales = datos['data']['getCountryConversions']
    lista_tasas = ramas_principales['conversionRates']
    fecha_milisegundos = ramas_principales['dateBcv']
    
    precio_bcv = None
    
    # 2. Buscamos en la lista cuál es la tasa que dice "SECONDARY"
    for tasa in lista_tasas:
        if tasa['type'] == 'SECONDARY':
            # ¡Lo encontramos! Guardamos el valor y redondeamos a 2 decimales
            precio_bcv = round(tasa['baseValue'], 2) 
            break
            
    # 3. Traducimos el Timestamp extraterrestre a una fecha humana
    # Dividimos entre 1000 porque Python lee segundos, no milisegundos
    fecha_real = datetime.fromtimestamp(fecha_milisegundos / 1000.0)
    
    print("¡Extracción exitosa!")
    print(f"Tasa BCV (Al Cambio): {precio_bcv}")
    # Formateamos la fecha para que se vea bonita (Día/Mes/Año Hora:Minutos)
    print(f"Fecha de la tasa: {fecha_real.strftime('%d/%m/%Y %I:%M %p')}")

else:
    print(f"Error: {respuesta.status_code}")