# app.py
from flask import Flask, render_template, request, redirect, url_for, session
from motor_inferencia import (
    cargar_base_conocimiento,
    seleccionar_categoria,
    seleccionar_observable,
    obtener_preguntas_candidatas,
    ejecutar_diagnostico
)
from utils import normalize_text, is_yes

app = Flask(__name__)
# ¡IMPORTANTE! Genera una clave segura y única para la producción
app.secret_key = 'super_clave_secreta_!23456' 

# Cargar la Base de Conocimiento al iniciar la aplicación
BC = cargar_base_conocimiento()

if BC is None:
    print("Error crítico: No se pudo cargar la Base de Conocimiento.")
    exit(1)

@app.route('/', methods=['GET', 'POST'])
def select_category():
    """Paso 1: Selección de Categoría y Observable."""
    
    # Reiniciar la sesión al empezar
    session.clear() 
    session['answers'] = {}

    categorias = BC.get("categorias", {})
    cat_keys = list(categorias.keys())
    
    if request.method == 'POST':
        # Captura la elección de categoría
        cat_choice = request.form.get('category_choice')
        
        selected_cat = seleccionar_categoria(BC, cat_choice)
        
        if selected_cat:
            session['selected_cat'] = selected_cat
            return redirect(url_for('select_observable'))
        else:
            error = "Categoría no válida."
            return render_template('index.html', step=1, categories=cat_keys, error=error)
            
    return render_template('index.html', step=1, categories=cat_keys)

@app.route('/observable', methods=['GET', 'POST'])
def select_observable():
    """Paso 2: Selección de Síntoma Observable."""
    
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
    selected_cat = session.get('selected_cat')
    selected_obs = session.get('selected_obs')
    preguntas_obs = session.get('preguntas_observable', [])
    answers = session.get('answers', {})

    if not selected_cat or not selected_obs:
        return redirect(url_for('select_category'))

    # 1. Obtener todas las preguntas (observable + categoría, evitando duplicados)
    preguntas_a_mostrar = list(preguntas_obs)
    asked_texts = {normalize_text(p["texto"]): p for p in preguntas_obs if p.get("texto")}
    
    cat_qs = BC.get("preguntas_categoria", {}).get(selected_cat, [])
    for q in cat_qs:
        clave = q.get("clave")
        texto = q.get("texto")
        tnorm = normalize_text(texto)
        
        # Evitar si ya se respondió por clave o si el texto normalizado ya está en las de observable
        if clave and answers.get(clave) is not None:
            continue
        if tnorm and tnorm in asked_texts:
            continue
        
        preguntas_a_mostrar.append(q)
        if tnorm:
            asked_texts[tnorm] = q


    if request.method == 'POST':
        # Captura las respuestas del formulario
        for q in preguntas_a_mostrar:
            clave = q.get("clave")
            texto = q.get("texto")
            qtipo = q.get("tipo", "si_no")
            key = clave if clave else normalize_text(texto)
            
            resp = request.form.get(key)
            
            # Normalización de respuestas del formulario
            if qtipo == "si_no":
                # Checkbox devuelve 'on' si marcado o None si no
                resp_norm = True if resp == 'on' else False 
            elif qtipo == "opcion_multiple":
                # La opción múltiple devuelve la opción elegida o None
                resp_norm = resp
            else: # entrada_texto o cualquier otro
                # Texto libre
                resp_norm = resp.strip() if resp else None
            
            if resp_norm is not None:
                answers[key] = resp_norm

        session['answers'] = answers
        # Ejecutar diagnóstico con las respuestas
        diagnostico = ejecutar_diagnostico(BC, selected_cat, selected_obs, answers)
        session['diagnostico'] = diagnostico
        return redirect(url_for('show_diagnosis'))
    
    # GET: Mostrar el formulario de preguntas
    return render_template('index.html', step=3, questions=preguntas_a_mostrar)

@app.route('/diagnosis')
def show_diagnosis():
    """Paso 5: Mostrar el resultado del Diagnóstico."""
    diagnostico = session.get('diagnostico')
    
    if not diagnostico:
        return redirect(url_for('select_category'))
        
    return render_template('index.html', step=4, diagnostico=diagnostico)

if __name__ == '__main__':
    # Usar debug=True solo para desarrollo
    app.run(debug=True)