import requests
from datetime import datetime

url_api = 'https://exchange.vcoud.com/coins/latest?type=bolivar&base=usd'

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
}

print("Consultando la API de CriptoDolar...\n")

respuesta = requests.get(url_api, headers=headers)

if respuesta.status_code == 200:
    datos = respuesta.json()
    
    # 1. Sacamos el diccionario de la lista y extraemos el precio
    precio_bcv = datos[0]['price']
    
    # 2. Extraemos el texto de la fecha
    fecha_texto = datos[0]['updatedAt'] # Se ve así: "2026-03-19T00:13:30.183Z"
    
    # 3. Limpiamos la fecha (cortamos la 'Z' y los milisegundos para que sea fácil de leer)
    # Nos quedamos con los primeros 19 caracteres: "2026-03-19T00:13:30"
    fecha_corta = fecha_texto[:19] 
    
    # 4. Traducimos ese texto a un objeto de tiempo en Python
    fecha_real = datetime.strptime(fecha_corta, "%Y-%m-%dT%H:%M:%S")
    
    print("¡Extracción exitosa!")
    print(f"Tasa BCV (CriptoDolar): {precio_bcv}")
    print(f"Fecha de la tasa: {fecha_real.strftime('%d/%m/%Y %I:%M %p')}")
    
else:
    print(f"Error de conexión: {respuesta.status_code}")