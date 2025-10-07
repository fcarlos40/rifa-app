import streamlit as st
import json
import csv
import smtplib
import re
import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from twilio.rest import Client
from io import StringIO
from streamlit_autorefresh import st_autorefresh
import logging
import pandas as pd
import time
# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# ----------------------------
# FUNCIONES DE PERSISTENCIA DE PREMIOS
# ----------------------------
def guardar_premios(premios):
    """Guarda la lista de premios en un archivo JSON"""
    try:
        with open("premios.json", "w", encoding="utf-8") as f:
            json.dump(premios, f, indent=4, ensure_ascii=False)
        logger.info("Premios guardados en premios.json")
    except Exception as e:
        logger.error(f"Error al guardar premios: {e}")
def cargar_premios():
    """Carga los premios desde un archivo JSON o devuelve lista vacía"""
    if os.path.exists("premios.json"):
        try:
            with open("premios.json", "r", encoding="utf-8") as f:
                premios = json.load(f)
            logger.info("Premios cargados desde premios.json")
            return premios
        except Exception as e:
            logger.error(f"Error al cargar premios: {e}")
            return []
    return []
# ----------------------------
# CONFIGURACIÓN MEJORADA
# ----------------------------
def cargar_configuracion():
    """Carga configuración con validación robusta"""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    config = {
        "ADMIN_USER": os.getenv("ADMIN_USER", "admin"),
        "ADMIN_PASS": os.getenv("ADMIN_PASS", "rifa123"),
        "SMTP_SERVER": os.getenv("SMTP_SERVER", "smtp.gmail.com"),
        "SMTP_PORT": int(os.getenv("SMTP_PORT", 587)),
        "SMTP_EMAIL": os.getenv("SMTP_EMAIL", ""),
        "SMTP_PASSWORD": os.getenv("SMTP_PASSWORD", ""),
        "TWILIO_ACCOUNT_SID": os.getenv("TWILIO_ACCOUNT_SID", ""),
        "TWILIO_AUTH_TOKEN": os.getenv("TWILIO_AUTH_TOKEN", ""),
        "TWILIO_WHATSAPP_FROM": os.getenv("TWILIO_WHATSAPP_FROM", ""),
        "MP_ACCESS_TOKEN": os.getenv("MP_ACCESS_TOKEN", ""),
        "WEBHOOK_URL": os.getenv("WEBHOOK_URL", ""),
        "ENLACE_PAGO_FALLBACK": os.getenv("ENLACE_PAGO_FALLBACK", "https://www.mercadopago.com.ar/"),
        "RIFA_NOMBRE": os.getenv("RIFA_NOMBRE", "Rifa Beneficio"),
        "RIFA_DESCRIPCION": os.getenv("RIFA_DESCRIPCION", ""),
    }
    # Validar MONTO_RIFA
    monto_raw = os.getenv("MONTO_RIFA", "30000")
    monto_limpio = re.sub(r'[^\d.]', '', monto_raw)
    try:
        config["MONTO_RIFA"] = float(monto_limpio) if monto_limpio else 30000.0
    except ValueError:
        config["MONTO_RIFA"] = 30000.0
        logger.warning("MONTO_RIFA inválido, usando valor por defecto: 30000.0")
    return config
# Cargar configuración
CONFIG = cargar_configuracion()
# ----------------------------
# CONSTANTES Y CONFIGURACIÓN
# ----------------------------
ADMIN_USER = CONFIG["ADMIN_USER"]
ADMIN_PASS = CONFIG["ADMIN_PASS"]
SMTP_SERVER = CONFIG["SMTP_SERVER"]
SMTP_PORT = CONFIG["SMTP_PORT"]
SMTP_EMAIL = CONFIG["SMTP_EMAIL"]
SMTP_PASSWORD = CONFIG["SMTP_PASSWORD"]
TWILIO_ACCOUNT_SID = CONFIG["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = CONFIG["TWILIO_AUTH_TOKEN"]
TWILIO_WHATSAPP_FROM = CONFIG["TWILIO_WHATSAPP_FROM"]
MP_ACCESS_TOKEN = CONFIG["MP_ACCESS_TOKEN"]
WEBHOOK_URL = CONFIG["WEBHOOK_URL"]
ENLACE_PAGO_FALLBACK = CONFIG["ENLACE_PAGO_FALLBACK"]
MONTO_RIFA = CONFIG["MONTO_RIFA"]
RIFA_NOMBRE = CONFIG["RIFA_NOMBRE"]
RIFA_DESCRIPCION = CONFIG["RIFA_DESCRIPCION"]
# Carpetas para datos
CARPETA_PARTICIPANTES = "participantes"
CARPETA_BACKUPS = "backups"
os.makedirs(CARPETA_PARTICIPANTES, exist_ok=True)
os.makedirs(CARPETA_BACKUPS, exist_ok=True)
# ----------------------------
# FUNCIONES AUXILIARES MEJORADAS
# ----------------------------
def es_email_valido(email):
    """Valida formato de email"""
    return re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email)
def es_telefono_valido(telefono):
    """Valida formato de teléfono internacional"""
    digits = re.sub(r"[^\d]", "", telefono)
    return len(digits) >= 7 and len(digits) <= 15 and digits.isdigit()
def es_boleto_valido(boleto):
    """Valida que el boleto sea de 5 dígitos"""
    return re.fullmatch(r"\d{5}", boleto) is not None
def normalizar_boleto(boleto):
    """Normaliza el número de boleto a 5 dígitos"""
    clean = re.sub(r"[^\d]", "", boleto)
    if clean.isdigit() and 1 <= len(clean) <= 5:
        return clean.zfill(5)
    return boleto
def guardar_participante_archivo(participante):
    """Guarda participante en archivo JSON individual"""
    nombre_archivo = f"{participante['nombre'].replace(' ', '_')}_{participante['boleto']}.json"
    ruta = os.path.join(CARPETA_PARTICIPANTES, nombre_archivo)
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(participante, f, indent=4, default=str, ensure_ascii=False)
        return ruta
    except Exception as e:
        logger.error(f"Error guardando participante {participante['nombre']}: {e}")
        return None
def cargar_todos_participantes():
    """Carga todos los participantes desde archivos JSON"""
    participantes = []
    for archivo in os.listdir(CARPETA_PARTICIPANTES):
        if archivo.endswith(".json"):
            ruta = os.path.join(CARPETA_PARTICIPANTES, archivo)
            try:
                with open(ruta, "r", encoding="utf-8") as f:
                    p = json.load(f)
                    participantes.append(p)
            except Exception as e:
                logger.warning(f"Error al cargar {archivo}: {e}")
    return sorted(participantes, key=lambda x: x.get('fecha_registro', ''))
def crear_enlace_pago_mercadopago(boleto, nombre, email, monto=MONTO_RIFA):
    """Crea un enlace de pago personalizado en Mercado Pago"""
    if not MP_ACCESS_TOKEN:
        logger.warning("MP_ACCESS_TOKEN no configurado. Usando enlace genérico.")
        return ENLACE_PAGO_FALLBACK
    try:
        headers = {
            "Authorization": f"Bearer {MP_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "transaction_amount": float(monto),
            "description": f"{RIFA_NOMBRE} - Boleto {boleto}",
            "payment_method_id": "ticket",
            "payer": {
                "email": email,
                "first_name": nombre.split()[0],
                "last_name": " ".join(nombre.split()[1:]) if len(nombre.split()) > 1 else ""
            },
            "external_reference": boleto,
            "notification_url": f"{WEBHOOK_URL}/webhook" if WEBHOOK_URL else None,
            "back_urls": {
                "success": f"{WEBHOOK_URL}?page=exito&boleto={boleto}",
                "pending": f"{WEBHOOK_URL}?page=pending",
                "failure": f"{WEBHOOK_URL}?page=error"
            },
            "auto_return": "approved"
        }
        response = requests.post(
            "https://api.mercadopago.com/checkout/preferences",
            json=payload,
            headers=headers,
            timeout=10
        )
        if response.status_code == 201:
            return response.json()["init_point"]
        else:
            logger.error(f"Error MP API ({response.status_code}): {response.text[:200]}")
            return ENLACE_PAGO_FALLBACK
    except Exception as e:
        logger.error(f"Excepción al crear enlace de pago: {e}")
        return ENLACE_PAGO_FALLBACK
def procesar_webhook_mercadopago(datos_webhook):
    """Procesa notificaciones de webhook de Mercado Pago"""
    try:
        if datos_webhook.get("type") == "payment":
            payment_id = datos_webhook.get("data", {}).get("id")
            if not MP_ACCESS_TOKEN:
                return False, "MP_ACCESS_TOKEN no configurado"
            headers = {
                "Authorization": f"Bearer {MP_ACCESS_TOKEN}",
                "Content-Type": "application/json"
            }
            response = requests.get(
                f"https://api.mercadopago.com/v1/payments/{payment_id}",
                headers=headers,
                timeout=10
            )
            # ✅ CORREGIDO: status_code debe ser 200, no 30000
            if response.status_code == 200:
                pago = response.json()
                external_reference = pago.get("external_reference")
                status = pago.get("status")
                if status == "approved" and external_reference:
                    participantes = cargar_todos_participantes()
                    for participante in participantes:
                        if participante['boleto'] == external_reference:
                            nombre_archivo = f"{participante['nombre'].replace(' ', '_')}_{participante['boleto']}.json"
                            ruta = os.path.join(CARPETA_PARTICIPANTES, nombre_archivo)
                            participante['estado_pago'] = 'pagado'
                            participante['fecha_pago'] = datetime.now().isoformat()
                            participante['id_pago_mp'] = payment_id
                            participante['metodo_pago'] = pago.get('payment_method_id', '')
                            with open(ruta, "w", encoding="utf-8") as f:
                                json.dump(participante, f, indent=4, default=str, ensure_ascii=False)
                            logger.info(f"Pago confirmado para boleto {external_reference}")
                            return True, "Pago procesado correctamente"
        return False, "Webhook no procesado"
    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        return False, str(e)
def crear_backup_automatico():
    """Crea backup automático de los datos"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        participantes = cargar_todos_participantes()
        backup_data = {
            "timestamp": timestamp,
            "rifa_nombre": RIFA_NOMBRE,
            "participantes": participantes,
            "premios": st.session_state.get('premios', []),
            "historial_sorteos": st.session_state.get('historial_sorteos', [])
        }
        backup_file = os.path.join(CARPETA_BACKUPS, f"backup_{timestamp}.json")
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, indent=4, default=str, ensure_ascii=False)
        backups = sorted([f for f in os.listdir(CARPETA_BACKUPS) if f.startswith("backup_")])
        if len(backups) > 10:
            for old_backup in backups[:-10]:
                os.remove(os.path.join(CARPETA_BACKUPS, old_backup))
        logger.info(f"Backup creado: {backup_file}")
        return True
    except Exception as e:
        logger.error(f"Error en backup: {e}")
        return False
def restaurar_backup(archivo_backup):
    """Restaura datos desde un backup"""
    try:
        with open(archivo_backup, "r", encoding="utf-8") as f:
            backup_data = json.load(f)
        for archivo in os.listdir(CARPETA_PARTICIPANTES):
            if archivo.endswith(".json"):
                os.remove(os.path.join(CARPETA_PARTICIPANTES, archivo))
        for participante in backup_data.get("participantes", []):
            guardar_participante_archivo(participante)
        st.session_state.premios = backup_data.get("premios", [])
        guardar_premios(st.session_state.premios)  # Guardar también en premios.json
        st.session_state.historial_sorteos = backup_data.get("historial_sorteos", [])
        logger.info("Backup restaurado correctamente")
        return True
    except Exception as e:
        logger.error(f"Error restaurando backup: {e}")
        return False
def mostrar_estadisticas_avanzadas():
    """Muestra estadísticas detalladas de la rifa"""
    participantes = cargar_todos_participantes()
    if not participantes:
        st.info("📊 No hay participantes registrados")
        return
    total_participantes = len(participantes)
    pagados = sum(1 for p in participantes if p.get('estado_pago') == 'pagado')
    pendientes = total_participantes - pagados
    recaudacion_total = pagados * MONTO_RIFA
    recaudacion_potencial = total_participantes * MONTO_RIFA
    tasa_conversion = (pagados / total_participantes * 100) if total_participantes > 0 else 0
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Participantes", total_participantes)
    with col2:
        st.metric("Pagos Confirmados", pagados, f"{tasa_conversion:.1f}%")
    with col3:
        st.metric("Por Pagar", pendientes)
    with col4:
        st.metric("Recaudación", f"${recaudacion_total:,.2f}")
    if total_participantes > 0:
        try:
            df = pd.DataFrame(participantes)
            df['fecha_registro'] = pd.to_datetime(df['fecha_registro'])
            st.subheader("📈 Evolución de Registros")
            registros_por_dia = df.set_index('fecha_registro').resample('D').size()
            if not registros_por_dia.empty:
                st.line_chart(registros_por_dia)
            else:
                st.info("No hay suficientes datos para mostrar la evolución")
            st.subheader("💰 Distribución por Estado de Pago")
            estado_counts = df['estado_pago'].value_counts()
            if not estado_counts.empty:
                st.bar_chart(estado_counts)
            if 'ciudad' in df.columns and not df['ciudad'].empty:
                st.subheader("🏙️ Top Ciudades")
                ciudad_counts = df[df['ciudad'] != '']['ciudad'].value_counts().head(10)
                if not ciudad_counts.empty:
                    st.bar_chart(ciudad_counts)
        except Exception as e:
            st.warning(f"No se pudieron generar gráficos: {e}")
def enviar_recordatorio_pago():
    """Envía recordatorios de pago a participantes pendientes"""
    participantes = cargar_todos_participantes()
    pendientes = [p for p in participantes if p.get('estado_pago') == 'pendiente']
    if not pendientes:
        st.info("✅ No hay participantes pendientes de pago")
        return
    st.subheader(f"📧 Enviar Recordatorios de Pago ({len(pendientes)} pendientes)")
    with st.form("recordatorio_pago"):
        asunto = st.text_input("Asunto", value="Recordatorio de Pago - Rifa")
        mensaje_personalizado = st.text_area(
            "Mensaje de recordatorio",
            value="""Hola {nombre},
Te recordamos que tu pago para la rifa está pendiente.
Detalles:
- Boleto: {boleto}
- Monto: ${monto}
- Enlace de pago: {enlace_pago}
Por favor, realiza el pago para confirmar tu participación.
¡Gracias!""",
            height=200
        )
        enviar_emails = st.checkbox("Enviar por email", value=True)
        enviar_whatsapp = st.checkbox("Enviar por WhatsApp", value=False)
        if st.form_submit_button("📤 Enviar Recordatorios"):
            if not SMTP_EMAIL and enviar_emails:
                st.error("❌ SMTP no configurado para emails")
                return
            if not TWILIO_ACCOUNT_SID and enviar_whatsapp:
                st.error("❌ Twilio no configurado para WhatsApp")
                return
            resultados = []
            progress_bar = st.progress(0)
            for i, participante in enumerate(pendientes):
                try:
                    mensaje = mensaje_personalizado.format(
                        nombre=participante['nombre'],
                        boleto=participante['boleto'],
                        monto=MONTO_RIFA,
                        enlace_pago=participante.get('link_pago', ENLACE_PAGO_FALLBACK)
                    )
                    if enviar_emails and participante.get('email'):
                        msg = MIMEMultipart()
                        msg['From'] = SMTP_EMAIL
                        msg['To'] = participante['email']
                        msg['Subject'] = asunto
                        msg.attach(MIMEText(mensaje, 'plain', 'utf-8'))
                        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                            server.starttls()
                            server.login(SMTP_EMAIL, SMTP_PASSWORD)
                            server.send_message(msg)
                        resultados.append(f"✅ Email enviado a {participante['nombre']}")
                    if enviar_whatsapp and participante.get('telefono'):
                        try:
                            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                            to_num = "+" + re.sub(r"[^\d]", "", participante['telefono'].lstrip("+"))
                            client.messages.create(
                                body=mensaje,
                                from_=TWILIO_WHATSAPP_FROM,
                                to=f"whatsapp:{to_num}"
                            )
                            resultados.append(f"✅ WhatsApp enviado a {participante['nombre']}")
                        except Exception as wa_error:
                            resultados.append(f"❌ WhatsApp falló para {participante['nombre']}: {wa_error}")
                    time.sleep(0.5)
                except Exception as e:
                    resultados.append(f"❌ Error con {participante['nombre']}: {str(e)}")
                progress_bar.progress((i + 1) / len(pendientes))
            st.success(f"✅ Proceso completado. {len(resultados)} acciones realizadas")
            for resultado in resultados:
                st.write(resultado)
# ----------------------------
# FUNCIONES DE NOTIFICACIÓN
# ----------------------------
def enviar_email_ganador(ganador, premio, mensaje_personalizado=None):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        return False, "SMTP no configurado"
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_EMAIL
        msg['To'] = ganador['email']
        msg['Subject'] = "🎉 ¡Felicidades! Ganaste en la rifa"
        cuerpo = (mensaje_personalizado or 
                 f"""¡Hola {ganador['nombre']}!
¡Felicidades! Has ganado el premio: **{premio}** en nuestra rifa.
Detalles:
- Boleto: {ganador['boleto']}
- Premio: {premio}
Pronto nos pondremos en contacto para coordinar la entrega.
¡Gracias por participar!""")
        msg.attach(MIMEText(cuerpo, 'plain', 'utf-8'))
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.send_message(msg)
        logger.info(f"Email enviado a ganador: {ganador['nombre']}")
        return True, "Éxito"
    except Exception as e:
        logger.error(f"Error enviando email a {ganador['nombre']}: {e}")
        return False, str(e)
def enviar_whatsapp_ganador(ganador, premio, mensaje_personalizado=None):
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_WHATSAPP_FROM:
        return False, "Twilio no configurado"
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        mensaje = (mensaje_personalizado or 
                  f"🎉 ¡Felicidades, {ganador['nombre']}! Ganaste: *{premio}* en la rifa. Boleto: {ganador['boleto']}. Pronto te contactaremos.")
        to_num = "+" + re.sub(r"[^\d]", "", ganador['telefono'].lstrip("+"))
        message = client.messages.create(
            body=mensaje,
            from_=TWILIO_WHATSAPP_FROM,
            to=f"whatsapp:{to_num}"
        )
        logger.info(f"WhatsApp enviado a ganador: {ganador['nombre']} - SID: {message.sid}")
        return True, "Éxito"
    except Exception as e:
        logger.error(f"Error enviando WhatsApp a {ganador['nombre']}: {e}")
        return False, str(e)
# ----------------------------
# FUNCIONES DE EXPORTACIÓN
# ----------------------------
def guardar_datos():
    participantes = cargar_todos_participantes()
    return json.dumps({
        "rifa_nombre": RIFA_NOMBRE,
        "fecha_exportacion": datetime.now().isoformat(),
        "premios": st.session_state.premios,
        "participantes": participantes,
        "historial_sorteos": st.session_state.historial_sorteos,
        "mensaje_email": st.session_state.mensaje_email,
        "mensaje_whatsapp": st.session_state.mensaje_whatsapp,
    }, indent=4, default=str, ensure_ascii=False)
def cargar_datos(uploaded_file):
    try:
        data = json.load(uploaded_file)
        st.session_state.premios = data.get("premios", [])
        guardar_premios(st.session_state.premios)  # Persistir
        st.session_state.historial_sorteos = data.get("historial_sorteos", [])
        st.session_state.mensaje_email = data.get("mensaje_email", st.session_state.mensaje_email)
        st.session_state.mensaje_whatsapp = data.get("mensaje_whatsapp", st.session_state.mensaje_whatsapp)
        for archivo in os.listdir(CARPETA_PARTICIPANTES):
            if archivo.endswith(".json"):
                os.remove(os.path.join(CARPETA_PARTICIPANTES, archivo))
        for participante in data.get("participantes", []):
            guardar_participante_archivo(participante)
        st.success("✅ Datos cargados correctamente.")
        logger.info("Datos cargados desde archivo")
    except Exception as e:
        st.error(f"❌ Error cargando datos: {e}")
        logger.error(f"Error cargando datos: {e}")
def exportar_resultados_csv(historial=None):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Fecha", "Premio", "Nombre", "Boleto", "Email", "Teléfono", "Dirección", "Ciudad", "Localidad", "Estado Pago", "Fecha Registro"])
    registros = historial or []
    for sorteo in registros:
        for res in sorteo.get("ganadores", []):
            g = res
            writer.writerow([
                sorteo.get("fecha", ""),
                sorteo.get("premio", "Lotería Nocturna"),
                g.get('nombre', ''),
                g.get('boleto', ''),
                g.get('email', ''),
                g.get('telefono', ''),
                g.get('direccion', ''),
                g.get('ciudad', ''),
                g.get('localidad', ''),
                g.get('estado_pago', 'pendiente'),
                g.get('fecha_registro', '')
            ])
    return output.getvalue()
def exportar_participantes_csv():
    participantes = cargar_todos_participantes()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Nombre", "Boleto", "Email", "Teléfono", "Dirección", "Ciudad", "Localidad", "Estado Pago", "Fecha Registro", "Fecha Pago"])
    for p in participantes:
        writer.writerow([
            p.get('nombre', ''),
            p.get('boleto', ''),
            p.get('email', ''),
            p.get('telefono', ''),
            p.get('direccion', ''),
            p.get('ciudad', ''),
            p.get('localidad', ''),
            p.get('estado_pago', 'pendiente'),
            p.get('fecha_registro', ''),
            p.get('fecha_pago', '')
        ])
    return output.getvalue()
# ----------------------------
# FUNCIONES DE SORTEO
# ----------------------------
def get_next_draw_time():
    now = datetime.utcnow() - timedelta(hours=3)
    draw_time = now.replace(hour=21, minute=30, second=0, microsecond=0)
    if now > draw_time:
        draw_time += timedelta(days=1)
    return draw_time
@st.cache_data(ttl=300)
def obtener_numero_nocturna():
    try:
        url = "https://www.resultadosloterias.com.ar/cordoba/nocturna/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        numero_tag = soup.find('span', class_='numero')
        if numero_tag:
            numero = re.sub(r'\D', '', numero_tag.get_text())
            if len(numero) == 5:
                return numero
        for span in soup.find_all('span'):
            texto = span.get_text()
            match = re.search(r'\b\d{5}\b', texto)
            if match:
                return match.group()
        for div in soup.find_all('div'):
            texto = div.get_text()
            match = re.search(r'\b\d{5}\b', texto)
            if match:
                return match.group()
        return None
    except Exception as e:
        logger.error(f"Error al obtener resultados oficiales: {e}")
        return None
# ----------------------------
# GESTIÓN MEJORADA DE PREMIOS (CON PERSISTENCIA)
# ----------------------------
def gestionar_premios():
    st.header("🏆 Gestión de Premios")
    if st.session_state.premios:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total de Premios", len(st.session_state.premios))
        with col2:
            st.metric("Estado", "✅ Activos")
        with col3:
            st.metric("Visibilidad", "🌐 Públicos")
    with st.form("form_gestion_premios"):
        st.subheader("➕ Agregar Nuevo Premio")
        col1, col2 = st.columns([3, 1])
        with col1:
            if st.session_state.editando_premio_idx is not None:
                premio_actual = st.session_state.premios[st.session_state.editando_premio_idx]
                nuevo_premio = st.text_input(
                    "Nombre del premio", 
                    value=premio_actual,
                    placeholder="Ej: Primer Premio - $50,000",
                    help="Describe el premio de forma atractiva para los participantes"
                )
            else:
                nuevo_premio = st.text_input(
                    "Nombre del premio", 
                    placeholder="Ej: Primer Premio - $50,000",
                    help="Describe el premio de forma atractiva para los participantes"
                )
        with col2:
            st.write("")
            st.write("")
            if st.session_state.editando_premio_idx is not None:
                btn_text = "💾 Actualizar Premio"
            else:
                btn_text = "➕ Agregar Premio"
            if st.form_submit_button(btn_text, use_container_width=True):
                if nuevo_premio.strip():
                    premio_limpio = " ".join(nuevo_premio.split())
                    if st.session_state.editando_premio_idx is not None:
                        st.session_state.premios[st.session_state.editando_premio_idx] = premio_limpio
                        st.success(f"✅ Premio actualizado: '{premio_limpio}'")
                        st.session_state.editando_premio_idx = None
                    else:
                        st.session_state.premios.append(premio_limpio)
                        st.success(f"✅ Premio agregado: '{premio_limpio}'")
                    guardar_premios(st.session_state.premios)  # ✅ Persistir cambios
                    st.rerun()
                else:
                    st.warning("⚠️ El nombre del premio no puede estar vacío")
    if st.session_state.premios:
        st.subheader("📋 Lista de Premios Activos")
        st.info("💡 Estos premios se mostrarán automáticamente en el registro público")
        for idx, premio in enumerate(st.session_state.premios):
            with st.container():
                col_nombre, col_acciones = st.columns([4, 2])
                with col_nombre:
                    st.markdown(f"""
                    <div style='padding: 10px; background: #f8f9fa; border-radius: 8px; border-left: 4px solid #FFD700; margin: 5px 0;'>
                        <span style='background: #FFD700; color: #000; padding: 2px 8px; border-radius: 12px; font-weight: bold; margin-right: 10px;'>#{idx+1}</span>
                        <strong>{premio}</strong>
                    </div>
                    """, unsafe_allow_html=True)
                with col_acciones:
                    col_edit, col_up, col_down, col_del = st.columns(4)
                    with col_edit:
                        if st.button("✏️", key=f"edit_{idx}", help="Editar premio", use_container_width=True):
                            st.session_state.editando_premio_idx = idx
                            st.rerun()
                    with col_up:
                        if idx > 0 and st.button("⬆️", key=f"up_{idx}", help="Mover arriba", use_container_width=True):
                            st.session_state.premios[idx], st.session_state.premios[idx-1] = st.session_state.premios[idx-1], st.session_state.premios[idx]
                            guardar_premios(st.session_state.premios)
                            st.rerun()
                    with col_down:
                        if idx < len(st.session_state.premios) - 1 and st.button("⬇️", key=f"down_{idx}", help="Mover abajo", use_container_width=True):
                            st.session_state.premios[idx], st.session_state.premios[idx+1] = st.session_state.premios[idx+1], st.session_state.premios[idx]
                            guardar_premios(st.session_state.premios)
                            st.rerun()
                    with col_del:
                        if st.button("🗑️", key=f"del_{idx}", help="Eliminar premio", use_container_width=True):
                            eliminado = st.session_state.premios.pop(idx)
                            st.success(f"🗑️ Premio eliminado: '{eliminado}'")
                            guardar_premios(st.session_state.premios)  # ✅ Persistir
                            if st.session_state.editando_premio_idx == idx:
                                st.session_state.editando_premio_idx = None
                            elif st.session_state.editando_premio_idx is not None and st.session_state.editando_premio_idx > idx:
                                st.session_state.editando_premio_idx -= 1
                            st.rerun()
        st.markdown("---")
        col_clear, col_export, col_import = st.columns(3)
        with col_clear:
            if st.button("🗑️ Limpiar Todos los Premios", use_container_width=True):
                if st.session_state.premios:
                    if st.checkbox("¿Estás seguro de eliminar TODOS los premios?"):
                        st.session_state.premios = []
                        guardar_premios(st.session_state.premios)  # ✅ Vaciar archivo
                        st.success("✅ Todos los premios han sido eliminados")
                        st.rerun()
        with col_export:
            # ✅ CORREGIDO: cadena multilínea
            premios_texto = "\n".join([f"{i+1}. {premio}" for i, premio in enumerate(st.session_state.premios)])
            st.download_button(
                "📥 Exportar Lista",
                premios_texto,
                "lista_premios_rifa.txt",
                "text/plain",
                use_container_width=True
            )
        with col_import:
            texto_premios = st.text_area(
                "Importar premios (uno por línea)",
                height=100,
                placeholder="Primer Premio - $50,000\nSegundo Premio - $20,000\nTercer Premio - $10,000",
                help="Pega la lista de premios, uno por línea"
            )
            if st.button("📤 Importar Premios", use_container_width=True):
                if texto_premios.strip():
                    nuevos_premios = [line.strip() for line in texto_premios.split('\n') if line.strip()]
                    st.session_state.premios.extend(nuevos_premios)
                    guardar_premios(st.session_state.premios)  # ✅ Persistir
                    st.success(f"✅ {len(nuevos_premios)} premios importados correctamente")
                    st.rerun()
    else:
        st.info("🎯 No hay premios configurados. Agrega algunos premios para que aparezcan en el registro público.")
        with st.expander("💡 Ejemplos de premios (click para agregar)"):
            ejemplos = [
                "Primer Premio - $50,000 en efectivo",
                "Segundo Premio - Motocicleta 150cc",
                "Tercer Premio - Televisor LED 55'",
                "Cuarto Premio - Notebook i5",
                "Quinto Premio - Smartphone Galaxy A54"
            ]
            for ejemplo in ejemplos:
                if st.button(f"➕ {ejemplo}", key=f"ej_{ejemplo}", use_container_width=True):
                    st.session_state.premios.append(ejemplo)
                    guardar_premios(st.session_state.premios)  # ✅ Persistir
                    st.success(f"✅ Premio de ejemplo agregado: '{ejemplo}'")
                    st.rerun()
    if st.session_state.premios:
        st.markdown("---")
        st.subheader("👁️ Vista Previa - Registro Público")
        st.info("Así se verán los premios en la página de registro público")
        with st.container():
            st.markdown("""
            <div style='background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                        padding: 25px; border-radius: 15px; margin: 20px 0; color: white;'>
                <h3 style='color: white; text-align: center; margin-bottom: 20px;'>🏆 Premios en Juego</h3>
            """, unsafe_allow_html=True)
            for idx, premio in enumerate(st.session_state.premios):
                st.markdown(f"""
                <div style='background: rgba(255, 255, 255, 0.95); padding: 15px; margin: 10px 0; 
                            border-radius: 10px; border-left: 5px solid #FFD700; box-shadow: 0 4px 6px rgba(0,0,0,0.1);'>
                    <div style='color: #2c3e50; font-weight: bold; font-size: 1.1em;'>
                        <span style='background: #FFD700; color: #2c3e50; border-radius: 50%; 
                                    width: 30px; height: 30px; display: inline-flex; align-items: center; 
                                    justify-content: center; font-weight: bold; margin-right: 10px;'>{idx + 1}</span>
                        {premio}
                    </div>
                </div>
                """, unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
# ----------------------------
# INICIALIZACIÓN DE SESIÓN (CON CARGA PERSISTENTE DE PREMIOS)
# ----------------------------
if 'logueado' not in st.session_state:
    st.session_state.logueado = False
if 'premios' not in st.session_state:
    st.session_state.premios = cargar_premios()  # ✅ Cargar desde archivo
if 'historial_sorteos' not in st.session_state:
    st.session_state.historial_sorteos = []
if 'editando_premio_idx' not in st.session_state:
    st.session_state.editando_premio_idx = None
if 'editando_participante_idx' not in st.session_state:
    st.session_state.editando_participante_idx = None
if 'numero_ganador_oficial' not in st.session_state:
    st.session_state.numero_ganador_oficial = None
if 'ultimo_sorteo_verificado' not in st.session_state:
    st.session_state.ultimo_sorteo_verificado = None
if 'form_submitted' not in st.session_state:
    st.session_state.form_submitted = False
if 'mensaje_email' not in st.session_state:
    st.session_state.mensaje_email = "¡Hola {nombre}!\n¡Felicidades! Has ganado el premio: **{premio}** en nuestra rifa.\nDetalles:\n- Boleto: {boleto}\n- Premio: {premio}\nPronto nos pondremos en contacto para coordinar la entrega.\n¡Gracias por participar!"
if 'mensaje_whatsapp' not in st.session_state:
    st.session_state.mensaje_whatsapp = "🎉 ¡Felicidades, {nombre}! Ganaste: *{premio}* en la rifa. Boleto: {boleto}. Pronto te contactaremos."
# ----------------------------
# ESTILOS COMUNES
# ----------------------------
contador_css = """
<style>
.contador-box {
    background: linear-gradient(120deg, #89f7fe 0%, #66a6ff 100%);
    padding: 20px;
    border-radius: 15px;
    text-align: center;
    margin: 15px 0;
    color: white;
    font-weight: bold;
    box-shadow: 0 4px 8px rgba(0,0,0,0.2);
}
.contador-num {
    font-size: 2.2em;
    margin: 0 8px;
}
.logo-container {
    text-align: center;
    margin-bottom: 20px;
}
.estado-pago {
    font-weight: bold;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.8em;
}
.estado-pendiente { 
    background: #fff3cd; 
    color: #856404;
    border: 1px solid #ffeaa7;
}
.estado-pagado { 
    background: #d1ecf1; 
    color: #0c5460;
    border: 1px solid #bee5eb;
}
</style>
"""
# ----------------------------
# PÁGINA DE LOGIN
# ----------------------------
page = st.query_params.get("page", "admin")
if isinstance(page, list):
    page = page[0]
if not st.session_state.logueado and page not in ["registro", "resultados", "exito", "error"]:
    st.set_page_config(page_title="🔐 Login - Rifa", page_icon="🔑", layout="centered")
    st.markdown(contador_css, unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown('<div class="logo-container">', unsafe_allow_html=True)
        st.image("https://emojipedia-us.s3.dualstack.us-west-1.amazonaws.com/thumbs/120/apple/325/ticket_1f3ab.png", width=100)
        st.markdown('</div>', unsafe_allow_html=True)
        st.title("🔐 Acceso Administrador")
        with st.form("login_form"):
            usuario = st.text_input("Usuario")
            contraseña = st.text_input("Contraseña", type="password")
            if st.form_submit_button("Iniciar Sesión", type="primary", use_container_width=True):
                if usuario == ADMIN_USER and contraseña == ADMIN_PASS:
                    st.session_state.logueado = True
                    # ✅ Eliminado código muerto: st.session_state.participantes
                    st.rerun()
                else:
                    st.error("❌ Usuario o contraseña incorrectos")
        st.markdown("---")
        st.markdown("¿Eres participante? [Regístrate aquí](?page=registro)")
        st.markdown("[Ver resultados](?page=resultados)")
    st.stop()
# ----------------------------
# PÁGINAS PÚBLICAS
# ----------------------------
if page == "registro":
    if st.session_state.form_submitted:
        st.set_page_config(page_title="✅ Registro Exitoso", page_icon="🎉", layout="centered")
        st.markdown(contador_css, unsafe_allow_html=True)
        st.title("✅ ¡Registro exitoso!")
        st.balloons()
        st.markdown("¡Gracias por participar! Tu boleto ha sido reservado.")
        st.markdown("### 💳 Para confirmar tu participación, realiza el pago:")
        st.markdown(f'<div style="text-align: center; margin: 20px 0;">'
                   f'<a href="{st.session_state.enlace_pago}" target="_blank" style="background: #00bb2d; color: white; padding: 15px 30px; text-decoration: none; border-radius: 10px; font-weight: bold; display: inline-block;">'
                   f'👉 Pagar ${MONTO_RIFA} con Mercado Pago</a></div>', unsafe_allow_html=True)
        st.info("💡 **Importante:** Tu participación solo será válida una vez confirmado el pago.")
        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📝 Registrar otra persona", use_container_width=True):
                st.session_state.form_submitted = False
                st.rerun()
        with col2:
            if st.button("🏠 Volver al inicio", use_container_width=True):
                st.query_params.clear()
                st.rerun()
        st.stop()
    st.set_page_config(page_title="🎟️ ¡Regístrate en la Rifa!", page_icon="📝", layout="centered")
    st_autorefresh(interval=1000, key="public_contador_refresh")
    premios_css = """
    <style>
    .contador-box { background: linear-gradient(120deg, #89f7fe 0%, #66a6ff 100%); padding: 20px; border-radius: 15px; text-align: center; margin: 15px 0; color: white; font-weight: bold; box-shadow: 0 4px 8px rgba(0,0,0,0.2); }
    .contador-num { font-size: 2.2em; margin: 0 8px; }
    .logo-container { text-align: center; margin-bottom: 20px; }
    .premios-section { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 25px; border-radius: 15px; margin: 20px 0; color: white; }
    .premio-card { background: rgba(255, 255, 255, 0.95); padding: 15px; margin: 10px 0; border-radius: 10px; border-left: 5px solid #FFD700; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
    .premio-titulo { color: #2c3e50; font-weight: bold; font-size: 1.1em; margin-bottom: 5px; }
    .premio-numero { background: #FFD700; color: #2c3e50; border-radius: 50%; width: 30px; height: 30px; display: inline-flex; align-items: center; justify-content: center; font-weight: bold; margin-right: 10px; }
    .sin-premios { background: rgba(255, 255, 255, 0.9); padding: 20px; border-radius: 10px; text-align: center; color: #666; font-style: italic; }
    </style>
    """
    st.markdown(premios_css + contador_css, unsafe_allow_html=True)
    st.markdown('<div class="logo-container">', unsafe_allow_html=True)
    st.image("https://emojipedia-us.s3.dualstack.us-west-1.amazonaws.com/thumbs/120/apple/325/ticket_1f3ab.png", width=100)
    st.markdown('</div>', unsafe_allow_html=True)
    st.title(f"🎟️ {RIFA_NOMBRE}")
    if RIFA_DESCRIPCION:
        st.markdown(f"*{RIFA_DESCRIPCION}*")
    # ✅ MOSTRAR PREMIOS DESDE SESIÓN (YA PERSISTENTES)
    if st.session_state.premios:
        st.markdown('<div class="premios-section">', unsafe_allow_html=True)
        st.markdown("### 🏆 Premios en Juego")
        st.markdown("¡Participa por estos increíbles premios!")
        for idx, premio in enumerate(st.session_state.premios):
            st.markdown(f"""
            <div class="premio-card">
                <div class="premio-titulo">
                    <span class="premio-numero">{idx + 1}</span>
                    {premio}
                </div>
            </div>
            """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="premios-section">', unsafe_allow_html=True)
        st.markdown("### 🎁 Premios Sorpresa")
        st.markdown('<div class="sin-premios">', unsafe_allow_html=True)
        st.markdown("¡Premios increíbles te esperan! Los detalles se revelarán pronto.")
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    next_draw = get_next_draw_time()
    now_arg = datetime.utcnow() - timedelta(hours=3)
    diff = next_draw - now_arg
    if diff.total_seconds() > 0:
        days = diff.days
        hours, remainder = divmod(diff.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        st.markdown('<div class="contador-box">', unsafe_allow_html=True)
        st.markdown(f"### ⏳ ¡El próximo sorteo es en!")
        st.markdown(
            f'<p><span class="contador-num">{days}</span>d &nbsp; <span class="contador-num">{hours:02d}</span>h &nbsp; <span class="contador-num">{minutes:02d}</span>m &nbsp; <span class="contador-num">{seconds:02d}</span>s</p>',
            unsafe_allow_html=True
        )
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="contador-box" style="background: linear-gradient(120deg, #ff9a9e 0%, #fad0c4 100%);">', unsafe_allow_html=True)
        st.markdown("### 🎉 ¡El sorteo ya se realizó hoy! Los resultados se publicarán pronto.")
        st.markdown('</div>', unsafe_allow_html=True)
    st.markdown("### 📝 Completa el formulario para participar:")
    with st.form("form_registro_publico"):
        col1, col2 = st.columns(2)
        with col1:
            nombre = st.text_input("Nombre completo *", placeholder="Ej: Juan Pérez")
            boleto = st.text_input(
                "Número de boleto *", 
                placeholder="5 dígitos (ej: 01234)",
                help="El número debe tener exactamente 5 dígitos"
            )
            email = st.text_input("Correo electrónico *", placeholder="tuemail@ejemplo.com")
        with col2:
            telefono = st.text_input("Teléfono con código de país *", placeholder="+5491112345678")
            direccion = st.text_input("Dirección", placeholder="Calle, número, piso")
            ciudad = st.text_input("Ciudad", placeholder="Buenos Aires")
            localidad = st.text_input("Localidad", placeholder="Palermo")
        st.markdown("---")
        col_info1, col_info2, col_info3 = st.columns(3)
        with col_info1:
            st.metric("🎫 Valor del boleto", f"${MONTO_RIFA}")
        with col_info2:
            participantes_count = len(cargar_todos_participantes())
            st.metric("👥 Participantes", participantes_count)
        with col_info3:
            st.metric("🏆 Premios", len(st.session_state.premios))
        submitted = st.form_submit_button("✅ Registrarme y Participar", use_container_width=True)
        if submitted:
            errores = []
            boleto_norm = normalizar_boleto(boleto.strip()) if boleto.strip() else ""
            if not nombre.strip(): 
                errores.append("Nombre es obligatorio.")
            if not boleto.strip(): 
                errores.append("Boleto es obligatorio.")
            if not email.strip(): 
                errores.append("Email es obligatorio.")
            if not telefono.strip(): 
                errores.append("Teléfono es obligatorio.")
            if boleto_norm and not es_boleto_valido(boleto_norm):
                errores.append("El boleto debe ser un número de 5 dígitos (ej: 01234).")
            if email.strip() and not es_email_valido(email.strip()):
                errores.append("Email inválido.")
            if telefono.strip() and not es_telefono_valido(telefono.strip()):
                errores.append("Teléfono debe ser número internacional válido (ej: +5491112345678).")
            participantes_existentes = cargar_todos_participantes()
            if boleto_norm and any(p['boleto'] == boleto_norm for p in participantes_existentes):
                errores.append("Ese boleto ya está tomado. Elige otro.")
            if errores:
                for e in errores:
                    st.error(f"❌ {e}")
            else:
                enlace_pago = crear_enlace_pago_mercadopago(boleto_norm, nombre.strip(), email.strip())
                st.session_state.enlace_pago = enlace_pago
                participante = {
                    "nombre": nombre.strip(),
                    "boleto": boleto_norm,
                    "email": email.strip(),
                    "telefono": "+" + re.sub(r"[^\d]", "", telefono.strip().lstrip("+")),
                    "direccion": direccion.strip(),
                    "ciudad": ciudad.strip(),
                    "localidad": localidad.strip(),
                    "fecha_registro": datetime.now().isoformat(),
                    "estado_pago": "pendiente",
                    "id_pago": boleto_norm,
                    "link_pago": enlace_pago
                }
                if guardar_participante_archivo(participante):
                    st.session_state.form_submitted = True
                    st.rerun()
                else:
                    st.error("❌ Error al guardar el registro. Intenta nuevamente.")
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🏠 Volver al inicio", use_container_width=True):
            st.query_params.clear()
            st.rerun()
    with col2:
        st.markdown("[📋 Ver reglamento](#)", unsafe_allow_html=True)
    with col3:
        st.markdown("[🏆 Ver resultados](?page=resultados)", unsafe_allow_html=True)
elif page == "resultados":
    st.set_page_config(page_title="🏆 Resultados del Sorteo", page_icon="🏅", layout="centered")
    resultados_css = """
    <style>
    .logo-container { text-align: center; margin-bottom: 20px; }
    .resultado-card { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); padding: 20px; border-radius: 15px; margin: 15px 0; color: white; box-shadow: 0 4px 8px rgba(0,0,0,0.2); }
    .premio-actual { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); padding: 25px; border-radius: 15px; margin: 20px 0; color: white; text-align: center; }
    .ganador-info { background: rgba(255, 255, 255, 0.95); padding: 15px; margin: 10px 0; border-radius: 10px; color: #2c3e50; }
    .estado-pago { font-weight: bold; padding: 4px 12px; border-radius: 20px; font-size: 0.8em; display: inline-block; margin-left: 10px; }
    .estado-pendiente { background: #fff3cd; color: #856404; border: 1px solid #ffeaa7; }
    .estado-pagado { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
    .sin-ganadores { background: rgba(255, 255, 255, 0.9); padding: 30px; border-radius: 10px; text-align: center; color: #666; font-style: italic; margin: 20px 0; }
    </style>
    """
    st.markdown(resultados_css, unsafe_allow_html=True)
    st.markdown('<div class="logo-container">', unsafe_allow_html=True)
    st.image("https://emojipedia-us.s3.dualstack.us-west-1.amazonaws.com/thumbs/120/apple/325/trophy_1f3c6.png", width=80)
    st.markdown('</div>', unsafe_allow_html=True)
    st.title("🏆 Resultados del Sorteo")
    if st.session_state.premios:
        st.markdown("### 🎁 Premios de la Rifa")
        for idx, premio in enumerate(st.session_state.premios):
            st.markdown(f"**{idx + 1}.** {premio}")
        st.markdown("---")
    if not st.session_state.historial_sorteos:
        st.info("📭 Los resultados aún no están disponibles. ¡Vuelve después del sorteo!")
    else:
        ultimo_sorteo = st.session_state.historial_sorteos[-1]
        st.markdown('<div class="premio-actual">', unsafe_allow_html=True)
        st.markdown(f"### 📅 Último Sorteo - {ultimo_sorteo['fecha']}")
        if ultimo_sorteo.get('numero_oficial'):
            st.markdown(f"### 🎯 Número Ganador: `{ultimo_sorteo['numero_oficial']}`")
        st.markdown('</div>', unsafe_allow_html=True)
        ganadores = ultimo_sorteo.get("ganadores", [])
        if ganadores:
            st.markdown("### 🎉 Ganadores")
            for g in ganadores:
                estado = g.get('estado_pago', 'pendiente')
                estado_class = "pagado" if estado == "pagado" else "pendiente"
                st.markdown(f"""
                <div class="ganador-info">
                    <h4>🏆 {ultimo_sorteo.get('premio', 'Lotería Nocturna')}</h4>
                    <p><strong>🥇 Ganador:</strong> {g['nombre']}</p>
                    <p><strong>🎫 Boleto:</strong> <code>{g['boleto']}</code></p>
                    <p><strong>📍 Ciudad:</strong> {g.get('ciudad', 'No especificada')}</p>
                    <p><strong>Estado:</strong> <span class='estado-pago estado-{estado_class}'>{estado.upper()}</span></p>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown('<div class="sin-ganadores">', unsafe_allow_html=True)
            st.markdown("### 🤷‍♂️ No hubo ganadores")
            st.markdown("En este sorteo no hubo participantes con el número ganador.")
            st.markdown('</div>', unsafe_allow_html=True)
        if len(st.session_state.historial_sorteos) > 1:
            st.markdown("---")
            st.markdown("### 📜 Historial Anterior")
            for sorteo in reversed(st.session_state.historial_sorteos[:-1]):
                with st.expander(f"Sorteo del {sorteo['fecha']} - Número: {sorteo.get('numero_oficial', 'N/A')}"):
                    ganadores_hist = sorteo.get("ganadores", [])
                    if ganadores_hist:
                        for g in ganadores_hist:
                            estado = g.get('estado_pago', 'pendiente')
                            estado_class = "pagado" if estado == "pagado" else "pendiente"
                            st.markdown(f"""
                            **{g['nombre']}** - Boleto: `{g['boleto']}` 
                            <span class='estado-pago estado-{estado_class}'>{estado}</span>
                            """, unsafe_allow_html=True)
                    else:
                        st.markdown("No hubo ganadores")
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🎟️ Participar en la rifa", use_container_width=True):
            st.query_params["page"] = "registro"
            st.rerun()
    with col2:
        if st.button("🏠 Volver al inicio", use_container_width=True):
            st.query_params.clear()
            st.rerun()
elif page == "exito":
    st.set_page_config(page_title="✅ Pago Exitoso", page_icon="🎉", layout="centered")
    st.title("✅ ¡Pago Confirmado!")
    st.balloons()
    st.success("Tu pago ha sido confirmado. ¡Ya estás participando en la rifa!")
    boleto = st.query_params.get("boleto", "")
    if isinstance(boleto, list):
        boleto = boleto[0] if boleto else ""
    if boleto:
        st.info(f"Tu boleto: **{boleto}**")
    if st.button("🏠 Volver al inicio"):
        st.query_params.clear()
        st.rerun()
elif page == "error":
    st.set_page_config(page_title="❌ Error en Pago", page_icon="⚠️", layout="centered")
    st.error("❌ Hubo un problema con tu pago")
    st.info("Por favor, intenta nuevamente o contacta con soporte.")
    if st.button("🔄 Reintentar pago"):
        st.query_params.clear()
        st.rerun()
# ----------------------------
# PANEL DE ADMINISTRACIÓN
# ----------------------------
else:
    st.set_page_config(page_title="🎟️ Panel Admin - Rifa", page_icon="👑", layout="wide")
    st_autorefresh(interval=1000, key="admin_contador_refresh")
    st.markdown(contador_css, unsafe_allow_html=True)
    st.markdown("""
    <style>
    @media (max-width: 768px) {
        .stButton button { width: 100% !important; }
        .stForm { padding: 10px; }
        h1, h2, h3 { text-align: center; }
    }
    .metric-card {
        background: white;
        padding: 15px;
        border-radius: 10px;
        border-left: 4px solid #4CAF50;
        margin: 5px 0;
    }
    </style>
    """, unsafe_allow_html=True)
    col_logo, col_titulo, col_logout = st.columns([1, 3, 1])
    with col_logo:
        st.image("https://emojipedia-us.s3.dualstack.us-west-1.amazonaws.com/thumbs/120/apple/325/crown_1f451.png", width=60)
    with col_titulo:
        st.title(f"👑 Panel de Administración - {RIFA_NOMBRE}")
    with col_logout:
        if st.button("🚪 Cerrar Sesión", use_container_width=True):
            st.session_state.logueado = False
            st.rerun()
    base_url = st.get_option("server.baseUrlPath") or "http://localhost:8501"
    st.markdown(f"""
    **🔗 Enlaces importantes:**
    - **Registro público:** `{base_url}?page=registro`
    - **Resultados públicos:** `{base_url}?page=resultados`
    - **Monto de la rifa:** `${MONTO_RIFA}`
    """)
    next_draw = get_next_draw_time()
    now_arg = datetime.utcnow() - timedelta(hours=3)
    diff = next_draw - now_arg
    if diff.total_seconds() > 0:
        days = diff.days
        hours, remainder = divmod(diff.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        st.markdown('<div class="contador-box">', unsafe_allow_html=True)
        st.markdown(f"### ⏳ Próximo sorteo en:")
        st.markdown(
            f'<p><span class="contador-num">{days}</span>d &nbsp; <span class="contador-num">{hours:02d}</span>h &nbsp; <span class="contador-num">{minutes:02d}</span>m &nbsp; <span class="contador-num">{seconds:02d}</span>s</p>',
            unsafe_allow_html=True
        )
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="contador-box" style="background: linear-gradient(120deg, #ff9a9e 0%, #fad0c4 100%);">', unsafe_allow_html=True)
        st.markdown("### 🎉 ¡El sorteo ya se realizó hoy! Verifica los resultados oficiales.")
        st.markdown('</div>', unsafe_allow_html=True)
    with st.sidebar:
        st.header("📁 Gestión de Datos")
        st.download_button(
            "💾 Descargar datos (JSON)", 
            guardar_datos(), 
            "rifa_datos.json", 
            "application/json",
            use_container_width=True
        )
        st.download_button(
            "📊 Exportar participantes (CSV)",
            exportar_participantes_csv(),
            "participantes_rifa.csv",
            "text/csv",
            use_container_width=True
        )
        uploaded_json = st.file_uploader("📤 Cargar datos (JSON)", type=["json"])
        if uploaded_json:
            if st.button("🔄 Cargar Datos", use_container_width=True):
                cargar_datos(uploaded_json)
                st.rerun()
        st.markdown("---")
        st.header("⚙️ Configuración")
        if st.button("🔄 Crear Backup", use_container_width=True):
            if crear_backup_automatico():
                st.success("✅ Backup creado")
            else:
                st.error("❌ Error creando backup")
        backup_files = [f for f in os.listdir(CARPETA_BACKUPS) if f.startswith("backup_")]
        if backup_files:
            selected_backup = st.selectbox("Seleccionar backup", sorted(backup_files, reverse=True))
            if st.button("🔄 Restaurar Backup", use_container_width=True):
                if restaurar_backup(os.path.join(CARPETA_BACKUPS, selected_backup)):
                    st.rerun()
    with st.expander("📊 Estadísticas Avanzadas", expanded=True):
        mostrar_estadisticas_avanzadas()
    with st.expander("✉️ Mensajes de Notificación"):
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📧 Mensaje de Email")
            mensaje_email = st.text_area(
                "Plantilla para emails a ganadores",
                value=st.session_state.mensaje_email,
                height=200,
                help="Usa {nombre}, {premio}, {boleto} como variables"
            )
        with col2:
            st.subheader("📱 Mensaje de WhatsApp")
            mensaje_whatsapp = st.text_area(
                "Plantilla para WhatsApp a ganadores",
                value=st.session_state.mensaje_whatsapp,
                height=150,
                help="Usa {nombre}, {premio}, {boleto} como variables"
            )
        if st.button("💾 Guardar Mensajes", use_container_width=True):
            st.session_state.mensaje_email = mensaje_email
            st.session_state.mensaje_whatsapp = mensaje_whatsapp
            st.success("✅ Mensajes actualizados")
    gestionar_premios()
    st.header("👥 Gestión de Participantes")
    with st.expander("👤 Registrar Participante Manualmente"):
        with st.form("form_manual"):
            col1, col2 = st.columns(2)
            with col1:
                nombre = st.text_input("Nombre *", key="m_nombre")
                email = st.text_input("Email", key="m_email")
                telefono = st.text_input("Teléfono (+54...)", key="m_tel")
            with col2:
                boleto = st.text_input("Boleto * (5 dígitos)", key="m_boleto")
                ciudad = st.text_input("Ciudad", key="m_ciudad")
                localidad = st.text_input("Localidad", key="m_loc")
            direccion = st.text_input("Dirección", key="m_dir")
            if st.form_submit_button("➕ Registrar Participante", use_container_width=True):
                boleto_norm = normalizar_boleto(boleto.strip()) if boleto.strip() else ""
                if not nombre.strip():
                    st.warning("⚠️ Nombre es obligatorio.")
                elif not boleto.strip():
                    st.warning("⚠️ Boleto es obligatorio.")
                elif not es_boleto_valido(boleto_norm):
                    st.warning("⚠️ El boleto debe ser un número de 5 dígitos (ej: 01234).")
                else:
                    participantes_existentes = cargar_todos_participantes()
                    if any(p['boleto'] == boleto_norm for p in participantes_existentes):
                        st.warning("⚠️ Ese boleto ya está registrado.")
                    else:
                        enlace_pago = crear_enlace_pago_mercadopago(boleto_norm, nombre.strip(), email.strip())
                        participante = {
                            "nombre": nombre.strip(),
                            "boleto": boleto_norm,
                            "email": email.strip(),
                            "telefono": "+" + re.sub(r"[^\d]", "", telefono.strip().lstrip("+")) if telefono.strip() else "",
                            "direccion": direccion.strip(),
                            "ciudad": ciudad.strip(),
                            "localidad": localidad.strip(),
                            "fecha_registro": datetime.now().isoformat(),
                            "estado_pago": "pendiente",
                            "id_pago": boleto_norm,
                            "link_pago": enlace_pago
                        }
                        if guardar_participante_archivo(participante):
                            st.success("✅ Participante registrado correctamente.")
                            st.rerun()
                        else:
                            st.error("❌ Error al guardar el participante.")
    participantes = cargar_todos_participantes()
    if participantes:
        st.subheader(f"📋 Lista de Participantes ({len(participantes)})")
        col_search, col_filter = st.columns([2, 1])
        with col_search:
            search = st.text_input("🔍 Buscar por nombre o boleto")
        with col_filter:
            filter_estado = st.selectbox("Filtrar por estado", ["Todos", "Pagado", "Pendiente"])
        filtered_participantes = participantes
        if search:
            filtered_participantes = [
                p for p in filtered_participantes
                if search.lower() in p['nombre'].lower() or search in p['boleto']
            ]
        if filter_estado != "Todos":
            estado_filter = "pagado" if filter_estado == "Pagado" else "pendiente"
            filtered_participantes = [p for p in filtered_participantes if p.get('estado_pago') == estado_filter]
        for p in filtered_participantes:
            with st.container():
                col_info, col_actions = st.columns([3, 1])
                with col_info:
                    estado = p.get('estado_pago', 'pendiente')
                    estado_class = "pagado" if estado == "pagado" else "pendiente"
                    st.markdown(f"""
                    **{p['nombre']}** | 🎟️ `{p['boleto']}` | 📧 {p['email'] or '—'} 
                    <span class='estado-pago estado-{estado_class}'>{estado}</span>
                    """, unsafe_allow_html=True)
                    if p.get('direccion') or p.get('ciudad'):
                        ubicacion = f"{p.get('direccion', '')} {p.get('ciudad', '')} {p.get('localidad', '')}".strip()
                        if ubicacion:
                            st.caption(f"📍 {ubicacion}")
                with col_actions:
                    if estado == "pendiente":
                        if st.button("✅ Pagar", key=f"pago_{p['boleto']}", use_container_width=True):
                            nombre_archivo = f"{p['nombre'].replace(' ', '_')}_{p['boleto']}.json"
                            ruta = os.path.join(CARPETA_PARTICIPANTES, nombre_archivo)
                            try:
                                with open(ruta, "r", encoding="utf-8") as f:
                                    data = json.load(f)
                                data["estado_pago"] = "pagado"
                                data["fecha_pago"] = datetime.now().isoformat()
                                with open(ruta, "w", encoding="utf-8") as f:
                                    json.dump(data, f, indent=4, default=str, ensure_ascii=False)
                                st.success(f"✅ {p['nombre']} marcado como pagado.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Error: {e}")
                    else:
                        st.button("✅ Pagado", key=f"paid_{p['boleto']}", disabled=True, use_container_width=True)
                st.markdown("---")
    with st.expander("📤 Carga Masiva por CSV"):
        st.markdown("""
        **Formato del CSV requerido:**
        - Columnas: `nombre, boleto, email, telefono, direccion, ciudad, localidad`
        - El boleto debe ser de 5 dígitos
        - La primera fila debe ser el encabezado
        """)
        uploaded_csv = st.file_uploader("Selecciona archivo CSV", type=["csv"], key="csv_up")
        if uploaded_csv:
            try:
                stringio = StringIO(uploaded_csv.getvalue().decode("utf-8"))
                reader = csv.DictReader(stringio)
                nuevos, duplicados, errores = 0, 0, 0
                participantes_existentes = cargar_todos_participantes()
                boletos_existentes = {p['boleto'] for p in participantes_existentes}
                progress_bar = st.progress(0)
                resultados = []
                rows = list(reader)
                for i, row in enumerate(rows):
                    boleto = row.get('boleto', '').strip()
                    if not boleto:
                        continue
                    boleto_norm = normalizar_boleto(boleto)
                    if not es_boleto_valido(boleto_norm):
                        resultados.append(f"❌ Boleto inválido: {boleto}")
                        errores += 1
                        continue
                    if boleto_norm in boletos_existentes:
                        resultados.append(f"⚠️ Boleto duplicado: {boleto_norm}")
                        duplicados += 1
                        continue
                    enlace_pago = crear_enlace_pago_mercadopago(
                        boleto_norm, 
                        row.get('nombre', '').strip(), 
                        row.get('email', '').strip()
                    )
                    participante = {
                        "nombre": row.get('nombre', '').strip(),
                        "boleto": boleto_norm,
                        "email": row.get('email', '').strip(),
                        "telefono": "+" + re.sub(r"[^\d]", "", row.get('telefono', '').strip().lstrip("+")) if row.get('telefono') else "",
                        "direccion": row.get('direccion', '').strip(),
                        "ciudad": row.get('ciudad', '').strip(),
                        "localidad": row.get('localidad', '').strip(),
                        "fecha_registro": datetime.now().isoformat(),
                        "estado_pago": "pendiente",
                        "id_pago": boleto_norm,
                        "link_pago": enlace_pago
                    }
                    if guardar_participante_archivo(participante):
                        nuevos += 1
                        boletos_existentes.add(boleto_norm)
                        resultados.append(f"✅ Agregado: {participante['nombre']} - {boleto_norm}")
                    else:
                        errores += 1
                        resultados.append(f"❌ Error guardando: {participante['nombre']}")
                    progress_bar.progress((i + 1) / len(rows))
                st.success(f"✅ Proceso completado: {nuevos} nuevos, {duplicados} duplicados, {errores} errores")
                with st.expander("Ver detalles del proceso"):
                    for resultado in resultados:
                        st.write(resultado)
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error procesando CSV: {e}")
    with st.expander("⏰ Recordatorios de Pago"):
        enviar_recordatorio_pago()
    st.header("🎲 Sistema de Sorteo")
    st.markdown("""
    La **Lotería de Córdoba Nocturna** se realiza **todos los días a las 21:30 hs** (hora Argentina).
    Verifica los resultados oficiales y notifica automáticamente a los ganadores **que hayan pagado**.
    """)
    col_verif, col_info = st.columns([2, 3])
    with col_verif:
        if st.button("🔍 Verificar resultados oficiales", type="primary", use_container_width=True):
            with st.spinner("Buscando resultados oficiales..."):
                numero_oficial = obtener_numero_nocturna()
            if numero_oficial:
                st.session_state.numero_ganador_oficial = numero_oficial
                st.session_state.ultimo_sorteo_verificado = datetime.now().date()
                st.success(f"✅ Número ganador oficial: **{numero_oficial}**")
                participantes = cargar_todos_participantes()
                ganadores = [p for p in participantes if p.get('boleto') == numero_oficial and p.get('estado_pago') == "pagado"]
                if ganadores:
                    st.subheader(f"🎉 ¡{len(ganadores)} Ganador(es) Encontrado(s)!")
                    resumen = []
                    for g in ganadores:
                        email_ok, email_msg = False, ""
                        wa_ok, wa_msg = False, ""
                        if g.get('email'):
                            email_ok, email_msg = enviar_email_ganador(
                                g, "Premio de la Lotería Nocturna", 
                                st.session_state.mensaje_email.format(
                                    nombre=g['nombre'], 
                                    premio="Premio de la Lotería Nocturna",
                                    boleto=g['boleto']
                                )
                            )
                        if g.get('telefono'):
                            wa_ok, wa_msg = enviar_whatsapp_ganador(
                                g, "Premio de la Lotería Nocturna",
                                st.session_state.mensaje_whatsapp.format(
                                    nombre=g['nombre'], 
                                    premio="Premio de la Lotería Nocturna",
                                    boleto=g['boleto']
                                )
                            )
                        resumen.append({
                            "ganador": g,
                            "email_ok": email_ok,
                            "email_msg": email_msg,
                            "wa_ok": wa_ok,
                            "wa_msg": wa_msg
                        })
                    st.session_state.historial_sorteos.append({
                        "fecha": date.today().isoformat(),
                        "numero_oficial": numero_oficial,
                        "premio": "Premio de la Lotería Nocturna",
                        "ganadores": ganadores
                    })
                    emails_ok = sum(1 for r in resumen if r["email_ok"])
                    wa_ok = sum(1 for r in resumen if r["wa_ok"])
                    st.success(f"📧 Emails enviados: {emails_ok}/{len(ganadores)}")
                    st.success(f"📱 WhatsApp enviados: {wa_ok}/{len(ganadores)}")
                    for r in resumen:
                        g = r["ganador"]
                        with st.container():
                            st.markdown(f"**{g['nombre']}** (Boleto: `{g['boleto']}`)")
                            col1, col2 = st.columns(2)
                            with col1:
                                if r["email_ok"]:
                                    st.success("✅ Email enviado")
                                else:
                                    st.error(f"❌ Email: {r['email_msg']}")
                            with col2:
                                if r["wa_ok"]:
                                    st.success("✅ WhatsApp enviado")
                                else:
                                    st.error(f"❌ WhatsApp: {r['wa_msg']}")
                    st.balloons()
                else:
                    st.info("ℹ️ No hay participantes **pagos** con el número ganador.")
                    st.session_state.historial_sorteos.append({
                        "fecha": date.today().isoformat(),
                        "numero_oficial": numero_oficial,
                        "premio": "Premio de la Lotería Nocturna",
                        "ganadores": []
                    })
            else:
                st.error("❌ No se pudo obtener el número ganador. Intenta después de las 21:30 hs.")
    with col_info:
        if st.session_state.numero_ganador_oficial:
            st.markdown(f"### 🎯 Último número ganador: **{st.session_state.numero_ganador_oficial}**")
            if st.session_state.ultimo_sorteo_verificado:
                st.caption(f"Verificado el {st.session_state.ultimo_sorteo_verificado}")
        else:
            st.info("👉 Haz clic en 'Verificar resultados oficiales' después de las 21:30 hs.")
    if st.session_state.historial_sorteos:
        st.header("📜 Historial de Resultados")
        ultimo_sorteo = st.session_state.historial_sorteos[-1]
        st.subheader(f"Último sorteo: {ultimo_sorteo.get('fecha', 'N/A')}")
        if ultimo_sorteo.get("ganadores"):
            for g in ultimo_sorteo["ganadores"]:
                estado = g.get('estado_pago', 'pendiente')
                estado_color = "pagado" if estado == "pagado" else "pendiente"
                st.markdown(f"""
                <div class="resultado-card">
                    <h4>🎁 {ultimo_sorteo.get('premio', 'Lotería Nocturna')}</h4>
                    <p><strong>Ganador:</strong> {g['nombre']} (Boleto: {g['boleto']}) <span class='estado-pago estado-{estado_color}'>[{estado}]</span></p>
                    <p>📧 {g['email'] or '—'} | 📞 {g['telefono'] or '—'}</p>
                    <p>📍 {g['direccion'] or '—'}, {g['ciudad']} {g['localidad']}</p>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No hubo ganadores en el último sorteo.")
        st.download_button(
            "📥 Descargar Historial Completo (CSV)",
            exportar_resultados_csv(st.session_state.historial_sorteos),
            "historial_resultados_rifa.csv",
            "text/csv",
            use_container_width=True
        )
    st.markdown("---")
    st.header("⚠️ Gestión de Riesgos")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 Reiniciar Participantes", use_container_width=True):
            if st.checkbox("CONFIRMAR: Eliminar todos los participantes"):
                import shutil
                shutil.rmtree(CARPETA_PARTICIPANTES)
                os.makedirs(CARPETA_PARTICIPANTES, exist_ok=True)
                st.session_state.historial_sorteos = []
                st.success("✅ Participantes y resultados reiniciados.")
                st.rerun()
    with col2:
        if "confirmar_todo" not in st.session_state:
            st.session_state.confirmar_todo = False
        if st.button("🗑️ Reiniciar TODO", use_container_width=True):
            st.session_state.confirmar_todo = True
        if st.session_state.confirmar_todo:
            if st.checkbox("CONFIRMAR REINICIO TOTAL: Esto borrará TODOS los datos"):
                if st.button("🔥 EJECUTAR REINICIO TOTAL", type="primary", use_container_width=True):
                    import shutil
                    shutil.rmtree(CARPETA_PARTICIPANTES)
                    os.makedirs(CARPETA_PARTICIPANTES, exist_ok=True)
                    shutil.rmtree(CARPETA_BACKUPS)
                    os.makedirs(CARPETA_BACKUPS, exist_ok=True)
                    if os.path.exists("premios.json"):
                        os.remove("premios.json")
                    for key in list(st.session_state.keys()):
                        del st.session_state[key]
                    st.success("✅ Sistema reiniciado completamente.")
                    st.rerun()
# ----------------------------
# FOOTER
# ----------------------------
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: #666;'>"
    "Sistema de Rifa v2.0 - Desarrollado con Streamlit"
    "</div>",
    unsafe_allow_html=True
)#    
 