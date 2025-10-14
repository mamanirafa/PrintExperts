import re

def is_yes(resp: str) -> bool:
    if resp is None:
        return False
    r = resp.strip().lower()
    return r in ("sí", "si", "s", "y", "yes", "1")

def is_no(resp: str) -> bool:
    if resp is None:
        return False
    r = resp.strip().lower()
    return r in ("no", "n", "0")

def preguntar_si_no(texto: str) -> bool:
    while True:
        resp = input(f"{texto} (Sí/No): ").strip()
        if is_yes(resp):
            return True
        if is_no(resp):
            return False
        print("Respuesta no válida. Escribe 'Sí' o 'No'.")

def preguntar_opcion_multiple(texto: str, opciones: list) -> str:
    print(texto)
    for i, opt in enumerate(opciones, start=1):
        print(f"  {i}) {opt}")
    while True:
        resp = input("Elige el número o escribe la opción tal cual: ").strip()
        if resp.isdigit():
            idx = int(resp) - 1
            if 0 <= idx < len(opciones):
                return opciones[idx]
        for opt in opciones:
            if resp.lower() == opt.lower():
                return opt
        print("Respuesta no válida. Introduce el número de la opción o el texto exacto.")

def evaluar_respuesta_confirmatoria(q: dict, respuesta) -> bool:
    t = q.get("tipo", "si_no")
    if t == "si_no":
        return bool(respuesta)
    if t == "opcion_multiple":
        if isinstance(respuesta, str):
            low = respuesta.lower()
            if "no" in low or "vacía" in low or "vacia" in low:
                return False
            return True
        return False
    if t == "entrada_texto":
        return bool(respuesta and str(respuesta).strip())
    # fallback
    return bool(respuesta)

def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[^a-z0-9áéíóúüñ ]', '', s)
    return s.strip()