import requests

url_api = 'https://api.dolaraldiavzla.com/api/v1/dollar?page=bcv'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
}

print("Consultando la API secreta de Dolar Al Día...\n")

respuesta = requests.get(url_api, headers=headers)

if respuesta.status_code == 200:
    # 1. Guardamos el diccionario completo
    datos = respuesta.json()
    
    # 2. Viajamos por las ramas hasta llegar al precio y la fecha
    # Ruta: datos -> 'monitors' -> 'usd' -> 'price'
    precio_bcv = datos['monitors']['usd']['price']
    fecha_bcv = datos['monitors']['usd']['last_update']
    
    print("¡Extracción exitosa!")
    print(f"Tasa BCV: {precio_bcv}")
    print(f"Fecha de la tasa: {fecha_bcv}")
    
else:
    print(f"Error de conexión: {respuesta.status_code}")