# app.py
from flask import Flask, render_template, request, redirect, url_for, session,jsonify
from urllib.parse import unquote
import json
import os
from config import KnowledgeBase, UserKnowledgeBase
from motor_inferencia import (
    cargar_base_conocimiento,
    seleccionar_categoria,
    seleccionar_observable,
    obtener_preguntas_candidatas,
    ejecutar_diagnostico
)
# 'is_yes' es necesario para la lógica del motor, 'normalize_text' para las claves
from utils import normalize_text, is_yes

app = Flask(__name__)
# ¡IMPORTANTE! Genera una clave segura y única para la producción
app.secret_key = 'super_clave_secreta_!23456' 


def get_active_kb():
    """
    Determina qué base de conocimiento cargar basado en la sesión.
    Retorna (datos_bc, nombre_bc)
    """
    kb_name = session.get('kb_name', 'base')
    
    if kb_name == 'user' and os.path.exists(UserKnowledgeBase):
        # Cargar la base de usuario si existe
        bc = cargar_base_conocimiento(UserKnowledgeBase)
        if bc:
            return bc, 'user'
            
    # Fallback: Cargar la base estándar
    bc_base = cargar_base_conocimiento(KnowledgeBase)
    if kb_name == 'user':
        # Si queríamos 'user' pero no existía, lo indicamos en la sesión
        session['kb_name'] = 'base'
        
    return bc_base, 'base'

def check_logical_duplicate(bc, sintoma, claves_premisas: list) -> tuple[bool, str]:
    """
    Verifica si ya existe una regla con el mismo síntoma y
    exactamente el mismo conjunto de premisas.
    Retorna (True, "Mensaje de duplicado") o (False, "").
    """
    nuevas_premisas_set = set(k for k in claves_premisas if k)
    
    if not nuevas_premisas_set:
        # No permitir reglas sin premisas
        return True, "No se pueden agregar reglas sin al menos una premisa."
    
    for regla in bc.get("reglas", []):
        if regla.get("sintoma_observable") == sintoma:
            premisas_actuales = regla.get("premisas", [])
            premisas_actuales_set = set(p.get("clave") for p in premisas_actuales)
            
            if premisas_actuales_set == nuevas_premisas_set:
                hipotesis_existente = regla.get('hipotesis', 'N/A')
                return True, f"Error: La hipótesis '{hipotesis_existente}' ya utiliza exactamente este conjunto de premisas para ese síntoma."
    
    return False, ""

def find_questions_for_keys(bc_data, keys_to_find: list) -> list:
    """Busca en TODAS las reglas las preguntas asociadas a las claves dadas."""
    found_questions = []
    found_keys = set()
    
    for regla in bc_data.get("reglas", []):
        for q in regla.get("preguntas", []):
            clave = q.get("clave")
            if clave in keys_to_find and clave not in found_keys:
                found_questions.append(q)
                found_keys.add(clave)
                
    return found_questions

@app.route('/', methods=['GET', 'POST'])
def select_category():
    """Paso 1: Selección de Categoría."""
    
    # 1. Determinar qué KB usar (del query ?kb= o de la sesión)
    kb_choice = request.args.get('kb', session.get('kb_name', 'base'))
    
    # 2. Validar que 'user' solo se use si el archivo existe
    if kb_choice == 'user' and not os.path.exists(UserKnowledgeBase):
        kb_choice = 'base'
        
    # 3. Guardar la elección en la sesión
    session['kb_name'] = kb_choice
    
    # 4. Cargar la BC correcta
    BC, kb_name = get_active_kb()
    user_kb_exists = os.path.exists(UserKnowledgeBase)
    
    # 5. IMPORTANTE: Reiniciar SOLO las respuestas, NO la sesión completa.
    #    (Este era el bug, no debe decir session.clear())
    session['answers'] = {}

    categorias = BC.get("categorias", {})
    cat_keys = list(categorias.keys())
    
    if request.method == 'POST':
        # La sesión 'kb_name' ya está seteada, así que BC es el correcto
        cat_choice = request.form.get('category_choice')
        selected_cat = seleccionar_categoria(BC, cat_choice)
        
        if selected_cat:
            session['selected_cat'] = selected_cat
            return redirect(url_for('select_observable'))
        else:
            error = "Categoría no válida."
            return render_template('index.html', step=1, categories=cat_keys, error=error, kb_name=kb_name, user_kb_exists=user_kb_exists)
            
    # Método GET
    return render_template('index.html', step=1, categories=cat_keys, kb_name=kb_name, user_kb_exists=user_kb_exists)

@app.route('/observable', methods=['GET', 'POST'])
def select_observable():
    """Paso 2: Selección de Síntoma Observable."""
    
    BC, kb_name = get_active_kb()
    user_kb_exists = os.path.exists(UserKnowledgeBase)
    
    selected_cat = session.get('selected_cat')
    if not selected_cat:
        return redirect(url_for('select_category'))

    obs_list = BC.get("categorias", {}).get(selected_cat, [])

    if request.method == 'POST':
        obs_choice = request.form.get('observable_choice')
        
        selected_obs = seleccionar_observable(BC, selected_cat, obs_choice)
        
        if selected_obs:
            session['selected_obs'] = selected_obs
            # Obtener preguntas para este observable
            reglas, preguntas = obtener_preguntas_candidatas(BC, selected_obs)
            session['reglas_candidatas'] = reglas
            session['preguntas_observable'] = preguntas
            return redirect(url_for('ask_questions'))
        else:
            error = "Síntoma observable no válido."
            return render_template('index.html', step=2, selected_cat=selected_cat, observables=obs_list, error=error)

    return render_template('index.html', step=2, selected_cat=selected_cat, observables=obs_list)

@app.route('/questions', methods=['GET', 'POST'])
def ask_questions():
    """Paso 3 y 4: Formulario de Preguntas y Procesamiento de Respuestas."""
    
    BC, kb_name = get_active_kb()
    user_kb_exists = os.path.exists(UserKnowledgeBase)
    
    selected_cat = session.get('selected_cat')
    selected_obs = session.get('selected_obs')
    # preguntas_obs tiene formato [{"clave": "...", "texto": "..."}]
    preguntas_obs = session.get('preguntas_observable', [])
    answers = session.get('answers', {})

    if not selected_cat or not selected_obs:
        return redirect(url_for('select_category'))

    # 1. Preparar las preguntas para el template
    # Ya no necesitamos lógica de "preguntas_categoria"
    preguntas_a_mostrar = []
    for q in preguntas_obs:
        clave = q.get("clave")
        texto = q.get("texto")
        # Esta es la 'key' que usará el formulario y que el POST recibirá
        # Usamos la clave si existe, sino normalizamos el texto
        form_key = clave if clave else normalize_text(texto) 
        preguntas_a_mostrar.append({
            "texto": texto,
            "key": form_key # Pasamos la clave al template
        })

    if request.method == 'POST':
        # 2. Captura las respuestas del formulario
        for q in preguntas_a_mostrar:
            # Usamos la misma 'key' que generamos para el template
            key = q.get("key") 
            
            resp = request.form.get(key)
            
            # Normalización de respuestas: Todo es un checkbox "si_no"
            # Un checkbox marcado envía 'on', desmarcado no envía nada (None)
            resp_norm = True if resp == 'on' else False 
            
            answers[key] = resp_norm # Guardamos la respuesta booleana

        session['answers'] = answers
        
        # 3. Ejecutar diagnóstico
        diagnostico = ejecutar_diagnostico(BC, selected_cat, selected_obs, answers)
        session['diagnostico'] = diagnostico
        return redirect(url_for('show_diagnosis'))
    
    # GET: Mostrar el formulario de preguntas
    return render_template('index.html', step=3, questions=preguntas_a_mostrar)

@app.route('/diagnosis')
def show_diagnosis():
    """Paso 5: Mostrar el resultado del Diagnóstico."""
    
    BC, kb_name = get_active_kb()
    user_kb_exists = os.path.exists(UserKnowledgeBase)
    
    diagnostico = session.get('diagnostico')
    
    if not diagnostico:
        return redirect(url_for('select_category'))
        
    return render_template('index.html', step=4, diagnostico=diagnostico)

@app.route('/add-knowledge', methods=['GET', 'POST'])
def add_knowledge():
    """Página para agregar nuevo conocimiento a la base de datos."""
    
    # ########## MODIFICACIÓN INICIO ##########
    if request.method == 'POST':
        try:
            data = request.json
            
            # 1. Recolectar datos básicos
            categoria = data.get("category")
            sintoma_tipo = data.get("symptom_type")
            causa_probable = data.get("probable_cause")
            sugerencia = data.get("user_suggestion")
            # 1.1. (NUEVO) Recolectar acciones
            acciones_nuevas = data.get("new_actions", [])

            # 2. Determinar el síntoma
            sintoma_observable = ""
            if sintoma_tipo == 'new':
                sintoma_observable = data.get("new_symptom")
            elif sintoma_tipo == 'existing':
                sintoma_observable = data.get("existing_symptom")

            if not all([categoria, sintoma_observable, causa_probable, sugerencia]):
                 return jsonify({"success": False, "message": "Faltan datos clave (categoría, síntoma, causa o sugerencia)."}), 400

            # 3. Cargar la base de conocimiento de destino
            target_kb_file = UserKnowledgeBase
            BC_data = None
            if os.path.exists(target_kb_file):
                BC_data = cargar_base_conocimiento(target_kb_file)
            else:
                BC_data = cargar_base_conocimiento(KnowledgeBase)
            
            if not BC_data:
                 return jsonify({"success": False, "message": "Error al cargar la base de conocimiento base."}), 500

            # 4. Recolectar y unificar premisas (claves, textos, preguntas)
            claves_existentes = data.get("existing_premises", [])
            claves_nuevas = data.get("new_premise_keys", [])
            textos_nuevos = data.get("new_premise_texts", [])
            preguntas_nuevas = data.get("new_premise_questions", [])

            claves_premisas_finales = list(set(claves_existentes + claves_nuevas))
            
            # 5. Ejecutar la validación lógica de duplicados
            es_duplicado, mensaje = check_logical_duplicate(BC_data, sintoma_observable, claves_premisas_finales)
            if es_duplicado:
                return jsonify({"success": False, "message": mensaje}), 409 # 409 Conflict

            # 6. (NUEVO) Determinar la lista final de acciones
            # Filtrar strings vacíos que puedan venir del formulario
            acciones_finales = [accion for accion in acciones_nuevas if accion.strip()] 
            
            if not acciones_finales:
                # Si el usuario no puso ninguna, usar una por defecto
                acciones_finales = [
                    "Revisar la sugerencia proporcionada por el usuario.",
                    "Si el problema persiste, contactar a soporte técnico."
                ]

            # 7. Construir la nueva regla
            nueva_regla = {
                "dominio": categoria,
                "sintoma_observable": sintoma_observable,
                "hipotesis": causa_probable.replace(" ", "_"), # Guardar con guiones bajos
                "premisas": [{"clave": k} for k in claves_premisas_finales],
                "preguntas": [],
                "acciones": acciones_finales, # <-- (MODIFICADO) Usar la lista final
                "recomendada_para_usuario": sugerencia
            }
            
            # 8. Añadir preguntas (nuevas y existentes)
            preguntas_existentes = find_questions_for_keys(BC_data, claves_existentes)
            nueva_regla["preguntas"].extend(preguntas_existentes)
            
            for i, clave in enumerate(claves_nuevas):
                if clave: 
                    if i < len(preguntas_nuevas):
                        nueva_regla["preguntas"].append({
                            "clave": clave,
                            "texto": preguntas_nuevas[i]
                        })

            # 9. Actualizar "categorias" si es un síntoma nuevo
            if sintoma_tipo == 'new':
                if categoria not in BC_data["categorias"]:
                     BC_data["categorias"][categoria] = []
                if sintoma_observable not in BC_data["categorias"][categoria]:
                    BC_data["categorias"][categoria].append(sintoma_observable)
            
            # 10. Añadir la regla y guardar en el archivo de USUARIO
            BC_data["reglas"].append(nueva_regla)
            
            with open(UserKnowledgeBase, "w", encoding="utf-8") as f:
                json.dump(BC_data, f, ensure_ascii=False, indent=2)
            
            # 11. Enviar respuesta de éxito con redirección
            return jsonify({
                "success": True, 
                "message": f"¡Conocimiento agregado exitosamente a '{UserKnowledgeBase}'!",
                "redirect": url_for('select_category', kb='user')
            })

        except Exception as e:
            print(f"Error en add_knowledge (POST): {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"success": False, "message": f"Error interno del servidor: {e}"}), 500
    # ########## MODIFICACIÓN FIN ##########
    
    # GET: Mostrar la página
    BC, kb_name = get_active_kb()
    user_kb_exists = os.path.exists(UserKnowledgeBase)
    
    categorias = BC.get("categorias", {})
    cat_keys = list(categorias.keys())
    
    return render_template('index.html', 
                            step=5, 
                            categories=cat_keys,
                            kb_name=kb_name,
                            user_kb_exists=user_kb_exists)

@app.route('/api/symptoms') # Ruta cambiada
def get_symptoms_by_category():
    """API endpoint para obtener síntomas existentes por categoría."""
    
    BC, kb_name = get_active_kb()
    
    try:
        # 1. Obtener de los args de la URL
        category_encoded = request.args.get('category')
        if not category_encoded:
            return {'success': False, 'error': 'No category provided'}, 400
            
        # 2. Decodificar (ej. 'Conectividad%2FSoftware' -> 'Conectividad/Software')
        category_clean = unquote(category_encoded).strip()
        
        categorias = BC.get("categorias", {})
        symptoms = categorias.get(category_clean, [])
        
        return {
            'success': True,
            'symptoms': symptoms,
            'category': category_clean,
            'found': len(symptoms) > 0
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'symptoms': [],
            'category': category_encoded
        }

@app.route('/api/premises') # Ruta cambiada
def get_premises_by_category():
    """API endpoint para obtener premisas (preguntas) existentes por categoría."""
    
    BC, kb_name = get_active_kb()
    
    try:
        # 1. Obtener de los args de la URL
        category_encoded = request.args.get('category')
        if not category_encoded:
            return {'success': False, 'error': 'No category provided'}, 400

        # 2. Decodificar
        category_clean = unquote(category_encoded).strip()
        
        reglas = BC.get("reglas", [])
        
        # 3. Filtrar reglas por la categoría (dominio)
        reglas_categoria = [r for r in reglas if r.get("dominio") == category_clean]
        
        premise_data = []
        seen_claves = set()
        for regla in reglas_categoria:
            for q in regla.get("preguntas", []):
                clave = q.get("clave")
                texto = q.get("texto")
                
                if clave and clave not in seen_claves:
                    seen_claves.add(clave)
                    premise_data.append({
                        'texto': texto,
                        'clave': clave,
                        'tipo': 'si_no' # Hardcodeado, ya que todo es si/no
                    })
        
        print(f"Premisas procesadas para {category_clean}: {len(premise_data)}")
        
        return {
            'success': True,
            'premises': premise_data,
            'category': category_clean,
            'found': len(premise_data) > 0
        }
    except Exception as e:
        print(f"Error al obtener premisas: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'error': str(e),
            'premises': [],
            'category': category_encoded
        }

# En motor_inferencia.py o app.py


if __name__ == '__main__':
    app.run(debug=False)