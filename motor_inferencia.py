import json
from utils import is_yes, normalize_text, preguntar_si_no, preguntar_opcion_multiple, evaluar_respuesta_confirmatoria, is_no
from config import KnowledgeBase

# Funciones de carga
def cargar_base_conocimiento():
    """Carga y retorna la Base de Conocimiento (BC) desde el archivo JSON."""
    try:
        with open(KnowledgeBase, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Archivo de Base de Conocimiento no encontrado: {KnowledgeBase}")
        return None
    except json.JSONDecodeError:
        print(f"Error: Formato JSON inválido en {KnowledgeBase}")
        return None
    
def seleccionar_categoria(bc: dict, cat_choice: str) -> str | None:
    """Busca y retorna el nombre de la categoría seleccionada."""
    categorias = bc.get("categorias", {})
    cat_keys = list(categorias.keys())
    
    if cat_choice.isdigit():
        idx = int(cat_choice) - 1
        if 0 <= idx < len(cat_keys):
            return cat_keys[idx]
    
    for c in cat_keys:
        if cat_choice.lower() == c.lower():
            return c
    return None

def seleccionar_observable(bc: dict, selected_cat: str, obs_choice: str) -> str | None:
    """Busca y retorna el nombre del síntoma observable seleccionado en la categoría."""
    obs_list = bc.get("categorias", {}).get(selected_cat, [])
    
    if obs_choice.isdigit():
        idx = int(obs_choice) - 1
        if 0 <= idx < len(obs_list):
            return obs_list[idx]
    
    for o in obs_list:
        if obs_choice.lower() == o.lower():
            return o
    return None

def obtener_preguntas_candidatas(bc: dict, selected_obs: str) -> tuple[list, list]:
    """
    1. Filtra las reglas candidatas por el observable.
    2. Unifica las preguntas de estas reglas.
    Retorna (reglas_candidatas, preguntas_unificadas).
    """
    reglas = bc.get("reglas", [])
    preguntas_categoria = bc.get("preguntas_categoria", {})
    
    # 1) Filtrar reglas candidatas
    reglas_candidatas = [r for r in reglas if r.get("sintoma_observable", "").lower() == selected_obs.lower()]

    # 2) Unificar preguntas (de las reglas candidatas)
    pregunta_items = []
    seen_keys = set()
    seen_texts = set()

    for regla in reglas_candidatas:
        for q in regla.get("preguntas", []):
            clave = q.get("clave")
            texto = q.get("texto", "")
            tnorm = normalize_text(texto)
            
            if clave and clave not in seen_keys:
                seen_keys.add(clave)
                pregunta_items.append({"clave": clave, "texto": texto, "tipo": q.get("tipo", "si_no"), "opciones": q.get("opciones")})
            elif not clave and tnorm and tnorm not in seen_texts:
                seen_texts.add(tnorm)
                pregunta_items.append({"clave": None, "texto": texto, "tipo": q.get("tipo", "si_no"), "opciones": q.get("opciones")})

    return reglas_candidatas, pregunta_items

def ejecutar_diagnostico(bc: dict, selected_cat: str, selected_obs: str, answers: dict) -> dict:
    """
    Ejecuta el proceso de inferencia para obtener el diagnóstico.
    A diferencia del original, no pregunta, solo evalúa las respuestas pre-existentes.
    """
    reglas = bc.get("reglas", [])
    
    # 1. Obtener reglas candidatas (como se hizo en el paso 3 del código original)
    reglas_candidatas = [r for r in reglas if r.get("sintoma_observable", "").lower() == selected_obs.lower()]

    trazas = []
    diagnostico = None

    for regla in reglas_candidatas:
        hipotesis = regla.get("hipotesis")
        dominio = regla.get("dominio")
        premisas = regla.get("premisas", [])
        preguntas = regla.get("preguntas", [])

        # Comprobar premisas
        premisas_result = {}
        all_premisas_satisfied = True
        
        for p in premisas:
            clave = p.get("clave")
            val = answers.get(clave) # Buscamos por clave
            
            if val is None:
                # Si no encontramos por clave, buscamos la pregunta asociada
                # para intentar encontrar la respuesta por texto normalizado
                for q in preguntas:
                    if q.get("clave") == clave:
                        qtexto = q.get("texto", "")
                        keytxt = normalize_text(qtexto)
                        val = answers.get(keytxt)
                        break
            
            # Normalizar valor de respuesta a boolean/valor para premisa
            p_res = None
            if val is not None:
                if isinstance(val, bool):
                    p_res = bool(val)
                elif isinstance(val, str):
                    low = val.strip().lower()
                    if low in ("sí", "si", "s", "yes", "true", "1"):
                        p_res = True
                    elif low in ("no", "n", "false", "0") or "vacía" in low or "vacia" in low:
                        p_res = False
                    else:
                        # Opciones de texto que indican presencia de algo -> True si no vacío
                        p_res = True if val.strip() != "" else False
                else:
                    p_res = bool(val)

            premisas_result[clave] = p_res
            if p_res is not True:
                all_premisas_satisfied = False

        # Comprobar confirmaciones por respuestas a preguntas de regla
        confirmaciones = []
        respuestas_regla = []
        any_confirmation = False
        
        for q in preguntas:
            qclave = q.get("clave")
            qtexto = q.get("texto", "")
            key = qclave if qclave else normalize_text(qtexto)
            
            resp = answers.get(key)
            used = resp is not None
            conf = False
            
            if used:
                conf = evaluar_respuesta_confirmatoria(q, resp)
                confirmaciones.append(conf)
                if conf:
                    any_confirmation = True
            
            respuestas_regla.append({"pregunta": qtexto, "respuesta": resp, "usada": used, "confirmada": conf})

        # Lógica de aceptación
        acepta = False
        razon = "No hay confirmaciones suficientes."
        
        if premisas and all_premisas_satisfied:
            acepta = True
            razon = "Todas las premisas respondidas y verdaderas."
        elif not premisas and any_confirmation:
            acepta = True
            razon = "Alguna pregunta específica del observable confirmó la hipótesis (no hay premisas)."
        elif any_confirmation and not all_premisas_satisfied:
            # Si hay alguna confirmación y no todas las premisas son True
            acepta = True
            razon = "Alguna pregunta específica del observable confirmó la hipótesis."
        
        trazas.append({
            "hipotesis": hipotesis,
            "dominio": dominio,
            "premisas_evaluadas": premisas_result,
            "respuestas_regla": respuestas_regla,
            "confirmaciones": confirmaciones,
            "aceptada": acepta,
            "razon": razon
        })

        if acepta:
            diagnostico = {
                "causa_probable": hipotesis,
                "acciones": regla.get("acciones", []),
                "dominio": dominio,
                "recomendada_para_usuario": regla.get("recomendada_para_usuario"),
                "traza": trazas # Incluimos las trazas hasta este punto
            }
            break

    # Si ninguna regla fue aceptada
    if diagnostico is None:
        diagnostico = {
            "causa_probable": "No determinada",
            "acciones": ["Revisar otras hipótesis; compartir respuestas y trazabilidad con soporte técnico."],
            "dominio": selected_cat,
            "traza": trazas # Incluimos todas las trazas de las reglas candidatas
        }
    
    return diagnostico


