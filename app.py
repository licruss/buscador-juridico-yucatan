import io
import re
import json
import time
import unicodedata
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

import requests
import streamlit as st
from bs4 import BeautifulSoup
import pdfplumber

APP_TITLE = "Buscador Jurídico Yucatán"
BASE_URL = "https://www.yucatan.gob.mx/gobierno/diario_oficial.php"
HEADERS = {
    "User-Agent": "BuscadorJuridicoYucatan/0.2 (consulta de publicaciones oficiales; uso personal)"
}
STATE_FILE = "vigilancia.json"
TIMEOUT = 30

st.set_page_config(page_title=APP_TITLE, page_icon="⚖️", layout="wide")
st.title("⚖️ Buscador Jurídico Yucatán")
st.write("Busca nombres de personas o números de expediente dentro de las ediciones PDF del Diario Oficial del Gobierno del Estado de Yucatán.")

st.info(
    "Fuente única de esta versión: Diario Oficial de Yucatán. El programa consulta las páginas diarias "
    "del periodo elegido, identifica PDF enlazados y busca coincidencias en el texto extraíble. "
    "No consulta boletines judiciales ni otras fuentes."
)

def normalize(value):
    value = unicodedata.normalize("NFD", value or "")
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = value.casefold()
    value = re.sub(r"[^a-z0-9/.-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def read_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("terms", [])
                data.setdefault("seen_matches", [])
                data.setdefault("last_scan", None)
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"terms": [], "seen_matches": [], "last_scan": None}

def write_state(data):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_html_for_day(day):
    url = f"{BASE_URL}?f={day.isoformat()}"
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    return url, response.text

def extract_pdf_links(day, html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(page_url, a["href"].strip())
        label = " ".join(a.get_text(" ", strip=True).split()) or "Abrir PDF"
        if ".pdf" in href.lower() and href not in seen:
            seen.add(href)
            links.append({"date": day.isoformat(), "label": label, "url": href, "page_url": page_url})
    # Some editions expose a PDF URL in an embedded object or iframe.
    for tag in soup.find_all(["iframe", "embed", "object"]):
        candidate = tag.get("src") or tag.get("data")
        if candidate:
            href = urljoin(page_url, candidate)
            if ".pdf" in href.lower() and href not in seen:
                seen.add(href)
                links.append({"date": day.isoformat(), "label": "PDF incrustado", "url": href, "page_url": page_url})
    return links, soup.get_text(" ", strip=True)

def extract_pdf_pages(pdf_url):
    response = requests.get(pdf_url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    with pdfplumber.open(io.BytesIO(response.content)) as pdf:
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(pdf.pages)]

def find_matches(pages, terms):
    matches = []
    normalized_terms = [(term, normalize(term)) for term in terms if normalize(term)]
    for page_no, text in pages:
        normalized_text = normalize(text)
        for original, term in normalized_terms:
            if not term or term not in normalized_text:
                continue
            # Find a readable contextual excerpt; accent/case-insensitive detection is authoritative.
            plain = re.sub(r"\s+", " ", text).strip()
            low_plain = plain.casefold()
            low_term = original.casefold()
            pos = low_plain.find(low_term)
            if pos >= 0:
                excerpt = plain[max(0, pos - 180): min(len(plain), pos + len(original) + 260)]
            else:
                excerpt = plain[:420]
            matches.append({"term": original, "page": page_no, "excerpt": excerpt})
    return matches

def day_range(days):
    today = date.today()
    start = today - timedelta(days=days - 1)
    current = start
    while current <= today:
        yield current
        current += timedelta(days=1)

state = read_state()

with st.sidebar:
    st.header("Parámetros de búsqueda")
    names = st.text_area("Nombres de las partes (uno por línea)", placeholder="Juan Pérez López\nMaría del Carmen Gómez")
    cases = st.text_area("Números de expediente (uno por línea)", placeholder="509/2024\n452/2025")
    days = st.selectbox("Periodo", [7, 15, 30, 60, 90], index=2, format_func=lambda x: f"Últimos {x} días")
    search_clicked = st.button("Buscar en Diario Oficial", type="primary", use_container_width=True)
    st.divider()
    st.subheader("Vigilancia")
    st.caption("Guarda los términos para reutilizarlos en próximas búsquedas. Para revisar automáticamente cada día, consulta las instrucciones del README.")
    save_clicked = st.button("Guardar términos", use_container_width=True)
    load_clicked = st.button("Cargar términos guardados", use_container_width=True)

terms = [line.strip() for line in (names + "\n" + cases).splitlines() if line.strip()]
if load_clicked:
    st.session_state["loaded_terms"] = state.get("terms", [])
    st.rerun()
if "loaded_terms" in st.session_state and not terms:
    terms = st.session_state["loaded_terms"]

if save_clicked:
    if not terms:
        st.warning("Escribe al menos un nombre o número de expediente antes de guardar.")
    else:
        state["terms"] = list(dict.fromkeys(terms))
        write_state(state)
        st.success(f"Se guardaron {len(state['terms'])} términos en este equipo.")

if state.get("terms"):
    st.caption("Términos guardados: " + " · ".join(state["terms"]))

if search_clicked:
    if not terms:
        st.error("Escribe al menos un nombre o número de expediente.")
    else:
        discovered = []
        page_errors = []
        pdf_errors = []
        pages_checked = 0
        unique_pdf_urls = set()
        dates = list(day_range(days))
        progress = st.progress(0, text="Preparando búsqueda…")
        status = st.empty()

        for idx, day in enumerate(dates):
            try:
                page_url, html = get_html_for_day(day)
                pages_checked += 1
                pdfs, page_text = extract_pdf_links(day, html, page_url)
                for item in pdfs:
                    if item["url"] not in unique_pdf_urls:
                        unique_pdf_urls.add(item["url"])
                        discovered.append(item)
            except requests.RequestException as exc:
                page_errors.append({"date": day.isoformat(), "url": f"{BASE_URL}?f={day.isoformat()}", "error": str(exc)[:220]})
            progress.progress((idx + 1) / len(dates), text=f"Revisando página del {day.strftime('%d/%m/%Y')}…")
            time.sleep(0.12)

        results = []
        pdf_progress = st.progress(0, text="Leyendo PDF encontrados…")
        for idx, item in enumerate(discovered):
            try:
                pdf_pages = extract_pdf_pages(item["url"])
                hits = find_matches(pdf_pages, terms)
                if hits:
                    results.append({**item, "hits": hits, "page_count": len(pdf_pages)})
            except Exception as exc:
                pdf_errors.append({"date": item["date"], "url": item["url"], "error": str(exc)[:220]})
            pdf_progress.progress((idx + 1) / max(1, len(discovered)), text=f"Leyendo documento {idx + 1} de {len(discovered)}…")
            time.sleep(0.12)

        now = datetime.now().isoformat(timespec="seconds")
        old_seen = set(state.get("seen_matches", []))
        new_matches = []
        for result in results:
            for hit in result["hits"]:
                key = f"{result['url']}|{hit['term']}|{hit['page']}"
                if key not in old_seen:
                    new_matches.append(key)
                    old_seen.add(key)
        state["terms"] = list(dict.fromkeys(terms))
        state["seen_matches"] = list(old_seen)
        state["last_scan"] = now
        write_state(state)

        st.subheader("Resultados")
        st.write(f"**Periodo:** {dates[0].strftime('%d/%m/%Y')} al {dates[-1].strftime('%d/%m/%Y')}")
        st.write(f"**Páginas diarias consultadas:** {pages_checked}/{len(dates)}")
        st.write(f"**PDF únicos detectados:** {len(discovered)}")
        st.write(f"**Documentos con coincidencias:** {len(results)}")

        if results:
            st.success(f"Se encontraron coincidencias en {len(results)} documento(s).")
            for result in results:
                with st.expander(f"{result['date']} · {result['label']} · {len(result['hits'])} coincidencia(s)", expanded=True):
                    st.markdown(f"[Abrir PDF original]({result['url']})")
                    st.markdown(f"[Abrir página de esa edición]({result['page_url']})")
                    for hit in result["hits"]:
                        st.markdown(f"**Término:** `{hit['term']}` · **Página PDF:** {hit['page']}")
                        st.write(hit["excerpt"] or "Se detectó la coincidencia, pero no se pudo preparar el fragmento.")
        else:
            st.warning(
                "No se encontraron coincidencias en los documentos que pudieron descargarse y cuyo texto pudo extraerse. "
                "Esto no acredita que no exista publicación: algunos PDF pueden ser imágenes escaneadas, no haberse podido "
                "descargar o no estar enlazados en la página diaria."
            )

        if page_errors:
            with st.expander(f"Páginas diarias no consultadas correctamente ({len(page_errors)})"):
                for err in page_errors:
                    st.markdown(f"- [{err['date']}]({err['url']}) — {err['error']}")
        if pdf_errors:
            with st.expander(f"PDF no procesados ({len(pdf_errors)})"):
                for err in pdf_errors:
                    st.markdown(f"- [{err['date']} · PDF]({err['url']}) — {err['error']}")

        st.caption(f"Última búsqueda ejecutada: {now}. Términos guardados para la siguiente sesión.")
        st.caption("El sistema busca coincidencias textuales; no determina por sí solo la validez o el efecto procesal de una publicación.")

st.divider()
st.subheader("Fuente consultada")
st.markdown(f"- [Diario Oficial del Gobierno del Estado de Yucatán]({BASE_URL})")
st.caption("No se consulta ninguna otra fuente en esta versión. La página oficial permite abrir ediciones por fecha mediante el parámetro de fecha.")
