import io
import re
import json
import time
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urljoin

import requests
import streamlit as st
from bs4 import BeautifulSoup
import pdfplumber

APP_TITLE = "Pasante Web"
BASE_URL = "https://www.yucatan.gob.mx/gobierno/diario_oficial.php"
HEADERS = {
    "User-Agent": "BuscadorJuridicoYucatan/0.3 (consulta de publicaciones oficiales; uso personal)"
}
STATE_FILE = "vigilancia.json"
TIMEOUT = 30

st.set_page_config(page_title=APP_TITLE, page_icon="⚖️", layout="wide")
st.markdown("""
<style>
.stButton > button {
   background-color: #D4AF62;
   color: #101010;
   border: 1px solid #D4AF62;
   border-radius: 10px;
   font-weight: 700;
   transition: all 0.2s ease;
}
.stButton > button:hover {
   background-color: #E8CB83;
   color: #101010;
   border-color: #E8CB83;
}
div[data-testid="stAlert"] {
   border-radius: 10px;
}
div[data-testid="stExpander"] {
   border: 1px solid #66532D;
   border-radius: 10px;
}
</style>
""", unsafe_allow_html=True)
st.markdown("""<div style="background:linear-gradient(135deg,#101010,#242424);
border:1px solid #D4AF62;border-radius:16px;padding:25px 20px;
margin-bottom:24px;">
<div style="display:flex;align-items:center;gap:16px;">
<div style="font-size:46px;color:#D4AF62;">⚖</div>
<div>
<div style="color:#D4AF62;font-size:29px;font-weight:800;
letter-spacing:2px;">PASANTE WEB</div>
<div style="color:#D0D0D0;font-size:12px;letter-spacing:2px;">
BUSCADOR JURÍDICO · YUCATÁN · ABOGADOS Y PASANTES.
</div>
</div>
</div>
<div style="border-top:1px solid #66532D;margin-top:20px;
padding-top:15px;color:#F4F4F4;font-size:17px;">
Sistema Único de Revisión del Diario Oficial del Estado de Yucatán.
</div>
<div style="color:#BBBBBB;font-size:13px;margin-top:6px;">
Sistematización de búsqueda</div>
</div>
""", unsafe_allow_html=True)
st.write("Revisa el Diario Oficial del Estado de Yucatán de una manera mas sencilla. Busca por nombre o número de expediente. Puedes revisar simultáneamente todos los expedientes que necesites.")

st.info(
    "Fuente única: Diario Oficial de Yucatán. El programa consulta las páginas oficiales de las fechas seleccionadas, "
    "identifica PDF enlazados y busca coincidencias en el texto extraíble. No consulta boletines judiciales ni otras fuentes. Esta página no es oficial y esta sujetas a errores de red."
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

def get_selected_dates(period):
    today = datetime.now (ZoneInfo("America/Merida")).date()
    if period == "Diario Oficial de hoy":
        return [today]
    if period == "Diario Oficial del día anterior":
        return [today - timedelta(days=1)]
    if period == "Diario Oficial de los últimos 3 días":
        return [today - timedelta(days=i) for i in (2, 1, 0)]
    days = int(period.replace("Últimos ", "").replace(" días", ""))
    start = today - timedelta(days=days - 1)
    return [start + timedelta(days=i) for i in range(days)]

state = read_state()

with st.sidebar:
    st.header("Parámetros de búsqueda")
    names = st.text_area("Nombres de las partes (uno por línea)", placeholder="Juan Pérez López\nMaría del Carmen Gómez")
    cases = st.text_area("Números de expediente (uno por línea)", placeholder="509/2024\n452/2025")
    period = st.selectbox(
        "Periodo de publicación",
        [
            "Diario Oficial de hoy",
            "Diario Oficial del día anterior",
            "Diario Oficial de los últimos 3 días",
            "Últimos 7 días",
            "Últimos 15 días",
            "Últimos 30 días",
            "Últimos 60 días",
            "Últimos 90 días",
        ],
        index=5,
    )
    search_clicked = st.button("Buscar en Diario Oficial", type="primary", use_container_width=True)
    st.divider()
    st.subheader("Vigilancia")
    st.caption("Guarda los términos para reutilizarlos en próximas búsquedas. La revisión automática diaria es una mejora posterior.")
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
        selected_dates = get_selected_dates(period)
        discovered = []
        page_errors = []
        pdf_errors = []
        pages_checked = 0
        unique_pdf_urls = set()
        progress = st.progress(0, text="Preparando búsqueda…")

        for idx, day in enumerate(selected_dates):
            try:
                page_url, html = get_html_for_day(day)
                pages_checked += 1
                pdfs, _ = extract_pdf_links(day, html, page_url)
                for item in pdfs:
                    if item["url"] not in unique_pdf_urls:
                        unique_pdf_urls.add(item["url"])
                        discovered.append(item)
            except requests.RequestException as exc:
                page_errors.append({"date": day.isoformat(), "url": f"{BASE_URL}?f={day.isoformat()}", "error": str(exc)[:220]})
            progress.progress((idx + 1) / len(selected_dates), text=f"Revisando página del {day.strftime('%d/%m/%Y')}…")
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

        now = datetime.now(ZoneInfo("America/Merida")).isoformat(timespec="seconds")
        old_seen = set(state.get("seen_matches", []))
        for result in results:
            for hit in result["hits"]:
                old_seen.add(f"{result['url']}|{hit['term']}|{hit['page']}")
        state["terms"] = list(dict.fromkeys(terms))
        state["seen_matches"] = list(old_seen)
        state["last_scan"] = now
        write_state(state)

        st.subheader("Resultados")
        st.write(f"**Periodo seleccionado:** {period}")
        st.write(f"**Fechas consultadas:** {selected_dates[0].strftime('%d/%m/%Y')} — {selected_dates[-1].strftime('%d/%m/%Y')}")
        st.write(f"**Páginas diarias consultadas correctamente:** {pages_checked}/{len(selected_dates)}")
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

        st.caption(f"Última búsqueda ejecutada: {now}.")
        st.caption("La búsqueda localiza coincidencias textuales; verifica siempre el documento oficial.")

st.divider()
st.subheader("Fuente consultada")
st.markdown(f"- [Diario Oficial del Gobierno del Estado de Yucatán]({BASE_URL})")
st.caption("Esta versión consulta exclusivamente el Diario Oficial de Yucatán.")
