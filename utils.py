import re

def is_yes(resp: str) -> bool:
    """Comprueba si la respuesta es afirmativa."""
    if resp is None:
        return False
    r = resp.strip().lower()
    # Se añade 'y' (yes) y '1' (true) como afirmativos comunes
    return r in ("sí", "si", "s", "y", "yes", "1")

def is_no(resp: str) -> bool:
    """Comprueba si la respuesta es negativa."""
    if resp is None:
        return False
    r = resp.strip().lower()
    # Se añade '0' (false) como negativo común
    return r in ("no", "n", "0")

def preguntar_si_no(texto: str) -> bool:
    """Realiza una pregunta de Sí/No al usuario y retorna un booleano."""
    while True:
        resp = input(f"{texto} (Sí/No): ").strip()
        if is_yes(resp):
            return True
        if is_no(resp):
            return False
        print("Respuesta no válida. Escribe 'Sí' o 'No'.")

def evaluar_respuesta_confirmatoria(respuesta) -> bool:
    """
    Evalúa si una respuesta dada es confirmatoria (True).
    Dado que todas las preguntas son Sí/No, esto es solo una conversión a booleano.
    """
    return bool(respuesta)

def normalize_text(s: str) -> str:
    """Limpia y normaliza un texto para comparaciones."""
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r'\s+', ' ', s) # Colapsa espacios
    s = re.sub(r'[^a-z0-9áéíóúüñ ]', '', s) # Elimina caracteres no alfanuméricos
    return s.strip()