import requests
from bs4 import BeautifulSoup

url = 'https://www.dolaraldiavzla.com/'

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

print("Conectando con Dolar Al Día para diagnóstico...")
respuesta = requests.get(url, headers=headers)

if respuesta.status_code == 200:
    sopa = BeautifulSoup(respuesta.text, 'html.parser')
    
    # 1. Imprimimos el título para ver si nos bloqueó un sistema de seguridad
    try:
        titulo = sopa.title.text
        print(f"\n--> El título que vio Python es: '{titulo}'")
    except:
        print("\n--> Python ni siquiera pudo encontrar un título en la página.")
    
    # 2. Guardamos todo el código crudo en un archivo para que lo puedas revisar
    with open("codigo_crudo.html", "w", encoding="utf-8") as archivo:
        archivo.write(respuesta.text)
        
    print("--> He guardado todo el código que me entregaron en un archivo llamado 'codigo_crudo.html'.")

else:
    print(f"Error de conexión: {respuesta.status_code}")