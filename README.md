# Buscador Jurídico Yucatán — versión 0.2

## Objetivo
Buscar un nombre o número de expediente en las publicaciones PDF del Diario Oficial del Gobierno del Estado de Yucatán.

## Qué hace esta versión
- Permite buscar varios nombres y/o expedientes.
- Consulta las páginas diarias oficiales de los últimos 7, 15, 30, 60 o 90 días.
- Descubre enlaces a PDF en cada página y elimina duplicados.
- Extrae texto de PDF y busca términos sin distinguir mayúsculas/minúsculas ni acentos.
- Presenta fecha, documento, número de página, fragmento coincidente y enlaces al PDF original y a la página oficial.
- Muestra páginas y PDF que no se pudieron consultar o leer.
- Permite guardar términos localmente para reutilizarlos.

## Limitaciones
- No incluye OCR para PDF escaneados. Si una edición no tiene texto extraíble, puede no detectar la coincidencia.
- Depende de que las ediciones y PDF estén enlazados en la página oficial.
- El programa no envía notificaciones automáticas ni se ejecuta en segundo plano todavía. La vigilancia diaria es una siguiente etapa.
- No garantiza la integridad de todas las publicaciones; abre y verifica siempre la fuente oficial.
- La búsqueda sin resultados no prueba que no haya publicación.

## Requisitos
Python 3.10 o posterior e internet.

## Instalar y ejecutar
1. Descarga y descomprime el archivo ZIP.
2. Abre una terminal dentro de la carpeta del proyecto.
3. Crea un entorno virtual:

   `python -m venv .venv`

4. Actívalo:

   Windows: `.venv\Scripts\activate`

   macOS/Linux: `source .venv/bin/activate`

5. Instala las dependencias:

   `pip install -r requirements.txt`

6. Ejecuta la aplicación:

   `streamlit run app.py`

Se abrirá una pestaña del navegador con el buscador.

## Próxima etapa
Una vez comprobado que descarga y busca correctamente en las ediciones diarias:
1. Añadir OCR para páginas escaneadas.
2. Automatizar una búsqueda diaria.
3. Avisar por correo de nuevas coincidencias.
4. Añadir un historial de búsquedas con fecha, URL, página y términos coincidentes.

## Privacidad
Los nombres y expedientes se procesan localmente en la computadora donde se ejecuta la aplicación. El programa consulta las páginas públicas del sitio oficial. No introduzcas datos personales que no necesites para la búsqueda.
