import hmac
import io
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal

import bcrypt
import pandas as pd
import psycopg2
import psycopg2.errors
import streamlit as st

# ==========================================
# 1. CONFIGURACIÓN DE PÁGINA Y CONSTANTES
# ==========================================
st.set_page_config(
    page_title="Angelmi Market Web POS",
    page_icon="🛒",
    layout="wide"
)

MAX_INTENTOS = 5            # intentos fallidos permitidos...
VENTANA_BLOQUEO_MIN = 10    # ...dentro de esta ventana de minutos
ROLES = ["Cajero", "Almacenero", "Administrador"]
LARGO_MIN_CLAVE = 8

M_POS = "🛒 Punto de Venta (POS)"
M_ANALYTICS = "📈 Sala Estadística (Analytics)"
M_PRODUCTOS = "📦 Gestión de Productos"
M_CATPROV = "📁 Categorías y Proveedores"
M_CLIEMP = "👥 Clientes y Empleados"
M_HISTORICO = "📊 Histórico de Ventas"
M_MER = "📐 Modelo Entidad-Relación (MER)"
M_BITACORA = "📜 Bitácora de Auditoría (.log)"

MENU_POR_ROL = {
    "Administrador": [M_POS, M_ANALYTICS, M_PRODUCTOS, M_CATPROV, M_CLIEMP, M_HISTORICO, M_MER, M_BITACORA],
    "Cajero": [M_POS, M_PRODUCTOS, M_CLIEMP],       # ventas, consulta de stock y registro rápido de clientes
    "Almacenero": [M_PRODUCTOS, M_CATPROV],         # inventario, categorías y proveedores
}

# ==========================================
# 2. ESTADO DE SESIÓN
# ==========================================
for _clave, _valor in {
    "autenticado": False,
    "usuario_actual": None,
    "carrito": [],
    "excel_bytes": None,
}.items():
    st.session_state.setdefault(_clave, _valor)

try:
    _ = st.secrets["postgres"]["url"]
except Exception:
    st.error(
        "Falta configurar la conexión a la base de datos. "
        "Agrega `[postgres] url = \"...\"` en .streamlit/secrets.toml (local) "
        "o en Settings → Secrets (Streamlit Cloud)."
    )
    st.stop()


# ==========================================
# 3. CONEXIÓN, TRANSACCIONES Y CONSULTAS
# ==========================================
def get_connection():
    return psycopg2.connect(st.secrets["postgres"]["url"], connect_timeout=10)


@contextmanager
def db_cursor():
    """Abre una transacción: commit si todo sale bien, rollback si algo falla, siempre cierra."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def leer_db(query, params=None):
    """Consulta de lectura sin caché."""
    conn = get_connection()
    try:
        return pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()


@st.cache_data(ttl=30)
def consultar_db(query, params=None):
    """Consulta de lectura con caché corta (30 s). Se invalida tras cada escritura."""
    return leer_db(query, params)


def invalidar_cache():
    st.cache_data.clear()


def flash(tipo, mensaje):
    """Mensaje que sobrevive al st.rerun() (tipo: success, error, warning, info, toast, balloons)."""
    st.session_state.setdefault("mensajes", []).append((tipo, mensaje))


def mostrar_mensajes():
    for tipo, mensaje in st.session_state.pop("mensajes", []):
        if tipo == "toast":
            st.toast(mensaje, icon="⚠️")
        elif tipo == "balloons":
            st.balloons()
        else:
            getattr(st, tipo)(mensaje)


def registrar_log(accion, detalle, cur=None, usuario=None):
    """
    Registra un evento en AUDITORIA_LOG.
    Si se pasa 'cur', el log se guarda en la MISMA transacción que la operación auditada.
    """
    actual = st.session_state.usuario_actual
    emp_id = actual["id"] if actual else None
    usr = usuario or (actual["usuario"] if actual else "SISTEMA")
    sql = "INSERT INTO AUDITORIA_LOG (id_empleado, usuario, accion, detalle) VALUES (%s, %s, %s, %s)"
    params = (emp_id, usr, accion, detalle)
    if cur is not None:
        cur.execute(sql, params)
        return
    try:
        with db_cursor() as c:
            c.execute(sql, params)
    except Exception as e:
        st.warning(f"No se pudo registrar el evento en la bitácora: {e}")


# ==========================================
# 4. ESQUEMA DE BASE DE DATOS (idempotente)
# ==========================================
def sql_renombrar_constraint(tabla, viejo, nuevo):
    return f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{viejo}' AND conrelid = '{tabla}'::regclass)
           AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{nuevo}' AND conrelid = '{tabla}'::regclass) THEN
            ALTER TABLE {tabla} RENAME CONSTRAINT {viejo} TO {nuevo};
        END IF;
    END $$;
    """


@st.cache_resource
def verificar_base_de_datos():
    """Crea/actualiza las 8 tablas (3FN) y devuelve la lista de errores (vacía si todo salió bien)."""
    ddl = [
        """
        CREATE TABLE IF NOT EXISTS CATEGORIA (
            id_categoria SERIAL PRIMARY KEY,
            nombre VARCHAR(100) NOT NULL CONSTRAINT uq_categoria_nombre UNIQUE,
            descripcion VARCHAR(255)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS PROVEEDOR (
            id_proveedor SERIAL PRIMARY KEY,
            nombre VARCHAR(100) NOT NULL,
            ruc_dni VARCHAR(20),
            telefono VARCHAR(20),
            email VARCHAR(100)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS CLIENTE (
            id_cliente SERIAL PRIMARY KEY,
            nombre VARCHAR(100) NOT NULL,
            documento VARCHAR(20) NOT NULL CONSTRAINT uq_cliente_documento UNIQUE,
            telefono VARCHAR(20),
            direccion VARCHAR(200),
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS EMPLEADO (
            id_empleado SERIAL PRIMARY KEY,
            nombre VARCHAR(100) NOT NULL,
            cargo VARCHAR(50),
            usuario VARCHAR(50) CONSTRAINT uq_empleado_usuario UNIQUE,
            clave VARCHAR(100),
            activo BOOLEAN NOT NULL DEFAULT TRUE,
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS PRODUCTO (
            id_producto SERIAL PRIMARY KEY,
            nombre VARCHAR(100) NOT NULL,
            precio NUMERIC(10,2) NOT NULL CONSTRAINT chk_producto_precio CHECK (precio >= 0),
            stock INT NOT NULL CONSTRAINT chk_producto_stock CHECK (stock >= 0),
            id_categoria INT NOT NULL REFERENCES CATEGORIA(id_categoria),
            id_proveedor INT NOT NULL REFERENCES PROVEEDOR(id_proveedor),
            activo BOOLEAN NOT NULL DEFAULT TRUE,
            fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS VENTA (
            id_venta SERIAL PRIMARY KEY,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            id_cliente INT NOT NULL REFERENCES CLIENTE(id_cliente),
            id_empleado INT NOT NULL REFERENCES EMPLEADO(id_empleado),
            total NUMERIC(10,2) NOT NULL CHECK (total >= 0)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS DETALLE_VENTA (
            id_detalle SERIAL PRIMARY KEY,
            id_venta INT NOT NULL REFERENCES VENTA(id_venta),
            id_producto INT NOT NULL REFERENCES PRODUCTO(id_producto),
            cantidad INT NOT NULL CHECK (cantidad > 0),
            precio_unitario NUMERIC(10,2) NOT NULL CHECK (precio_unitario >= 0),
            subtotal NUMERIC(10,2) NOT NULL CHECK (subtotal >= 0),
            CONSTRAINT chk_detalle_subtotal CHECK (subtotal = cantidad * precio_unitario)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS AUDITORIA_LOG (
            id_log SERIAL PRIMARY KEY,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            id_empleado INT REFERENCES EMPLEADO(id_empleado),
            usuario VARCHAR(50),
            accion VARCHAR(100),
            detalle TEXT
        );
        """,
        # --- Migraciones para bases de datos ya existentes ---
        "ALTER TABLE EMPLEADO ALTER COLUMN clave TYPE VARCHAR(100);",   # el hash bcrypt mide 60 caracteres
        "ALTER TABLE EMPLEADO ADD COLUMN IF NOT EXISTS activo BOOLEAN NOT NULL DEFAULT TRUE;",
        "ALTER TABLE PRODUCTO ADD COLUMN IF NOT EXISTS activo BOOLEAN NOT NULL DEFAULT TRUE;",
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint
                           WHERE conname = 'chk_detalle_subtotal' AND conrelid = 'detalle_venta'::regclass) THEN
                ALTER TABLE DETALLE_VENTA
                    ADD CONSTRAINT chk_detalle_subtotal CHECK (subtotal = cantidad * precio_unitario) NOT VALID;
            END IF;
        END $$;
        """,
        sql_renombrar_constraint("producto", "producto_precio_check", "chk_producto_precio"),
        sql_renombrar_constraint("producto", "producto_stock_check", "chk_producto_stock"),
        sql_renombrar_constraint("categoria", "categoria_nombre_key", "uq_categoria_nombre"),
        sql_renombrar_constraint("cliente", "cliente_documento_key", "uq_cliente_documento"),
        sql_renombrar_constraint("empleado", "empleado_usuario_key", "uq_empleado_usuario"),
        # --- Bitácora inalterable a nivel de base de datos ---
        """
        CREATE OR REPLACE FUNCTION fn_auditoria_inalterable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'AUDITORIA_LOG es inalterable: operacion % no permitida', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        DROP TRIGGER IF EXISTS trg_auditoria_no_modificar ON AUDITORIA_LOG;
        CREATE TRIGGER trg_auditoria_no_modificar
            BEFORE UPDATE OR DELETE ON AUDITORIA_LOG
            FOR EACH ROW EXECUTE FUNCTION fn_auditoria_inalterable();
        """,
        """
        DROP TRIGGER IF EXISTS trg_auditoria_no_truncar ON AUDITORIA_LOG;
        CREATE TRIGGER trg_auditoria_no_truncar
            BEFORE TRUNCATE ON AUDITORIA_LOG
            FOR EACH STATEMENT EXECUTE FUNCTION fn_auditoria_inalterable();
        """,
    ]
    errores = []
    try:
        conn = get_connection()
    except Exception as e:
        return [f"No se pudo conectar a la base de datos: {e}"]
    try:
        conn.autocommit = True
        cur = conn.cursor()
        for q in ddl:
            try:
                cur.execute(q)
            except Exception as e:
                errores.append(str(e).strip())
    finally:
        conn.close()
    return errores


errores_bd = verificar_base_de_datos()


# ==========================================
# 5. CONTRASEÑAS (bcrypt)
# ==========================================
def politica_clave(clave):
    """Devuelve un mensaje de error si la contraseña no es válida, o None si está bien."""
    if len(clave) < LARGO_MIN_CLAVE:
        return f"La contraseña debe tener al menos {LARGO_MIN_CLAVE} caracteres."
    if len(clave.encode("utf-8")) > 72:
        return "La contraseña es demasiado larga (máximo 72 bytes)."
    return None


def hashear_clave(clave):
    return bcrypt.hashpw(clave.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def es_hash(valor):
    return bool(valor) and valor.startswith(("$2a$", "$2b$", "$2y$"))


def verificar_clave(clave, almacenado):
    if not almacenado:
        return False
    if es_hash(almacenado):
        try:
            return bcrypt.checkpw(clave.encode("utf-8"), almacenado.encode("utf-8"))
        except ValueError:
            return False
    # Contraseña antigua en texto plano: se acepta UNA vez y se migra a hash en validar_login().
    return hmac.compare_digest(clave.encode("utf-8"), almacenado.encode("utf-8"))


def intentos_fallidos_recientes(usuario):
    with db_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM AUDITORIA_LOG WHERE accion = 'LOGIN_FALLIDO' AND usuario = %s "
            "AND fecha > CURRENT_TIMESTAMP - (%s * INTERVAL '1 minute')",
            (usuario, VENTANA_BLOQUEO_MIN)
        )
        return cur.fetchone()[0]


def validar_login(usuario, clave):
    with db_cursor() as cur:
        cur.execute(
            "SELECT id_empleado, nombre, cargo, usuario, clave FROM EMPLEADO WHERE usuario = %s AND activo",
            (usuario,)
        )
        fila = cur.fetchone()
        if not fila or not verificar_clave(clave, fila[4]):
            return None
        if not es_hash(fila[4]):
            cur.execute("UPDATE EMPLEADO SET clave = %s WHERE id_empleado = %s", (hashear_clave(clave), fila[0]))
    return fila[:4]


def verificar_clave_empleado(id_empleado, clave, solo_admin=False):
    sql = "SELECT clave FROM EMPLEADO WHERE id_empleado = %s AND activo"
    if solo_admin:
        sql += " AND cargo = 'Administrador'"
    with db_cursor() as cur:
        cur.execute(sql, (id_empleado,))
        fila = cur.fetchone()
    return bool(fila) and verificar_clave(clave, fila[0])


def validar_clave_admin(clave):
    ok = verificar_clave_empleado(st.session_state.usuario_actual["id"], clave, solo_admin=True)
    if not ok:
        registrar_log("CLAVE_ADMIN_INCORRECTA", "Confirmación de contraseña de administrador fallida.")
    return ok


def rol_actual():
    return st.session_state.usuario_actual["cargo"]


def es_admin():
    return rol_actual() == "Administrador"


# ==========================================
# 6. REPORTES (Excel y .log)
# ==========================================
HOJAS_EXCEL = {
    "Ventas": "SELECT v.id_venta, v.fecha, c.nombre AS cliente, e.nombre AS empleado, v.total FROM VENTA v "
              "LEFT JOIN CLIENTE c ON v.id_cliente = c.id_cliente LEFT JOIN EMPLEADO e ON v.id_empleado = e.id_empleado "
              "ORDER BY v.id_venta DESC",
    "Detalle_Ventas": "SELECT d.id_detalle, d.id_venta, p.nombre AS producto, d.cantidad, d.precio_unitario, d.subtotal "
                      "FROM DETALLE_VENTA d LEFT JOIN PRODUCTO p ON d.id_producto = p.id_producto",
    "Productos": "SELECT p.id_producto, p.nombre, p.precio, p.stock, p.activo, c.nombre AS categoria, pr.nombre AS proveedor, "
                 "p.fecha_registro FROM PRODUCTO p LEFT JOIN CATEGORIA c ON p.id_categoria = c.id_categoria "
                 "LEFT JOIN PROVEEDOR pr ON p.id_proveedor = pr.id_proveedor ORDER BY p.id_producto DESC",
    "Clientes": "SELECT id_cliente, nombre, documento, telefono, direccion, fecha_registro FROM CLIENTE",
    "Empleados": "SELECT id_empleado, nombre, cargo, usuario, activo, fecha_registro FROM EMPLEADO",  # sin contraseñas
    "Categorias": "SELECT * FROM CATEGORIA",
    "Proveedores": "SELECT * FROM PROVEEDOR",
    "Log_Acciones": "SELECT l.id_log, l.fecha, l.usuario, e.nombre AS empleado, e.cargo, l.accion, l.detalle "
                    "FROM AUDITORIA_LOG l LEFT JOIN EMPLEADO e ON l.id_empleado = e.id_empleado ORDER BY l.id_log DESC",
}


def generar_reporte_excel():
    conn = get_connection()
    try:
        salida = io.BytesIO()
        with pd.ExcelWriter(salida, engine="openpyxl") as writer:
            for hoja, sql in HOJAS_EXCEL.items():
                pd.read_sql_query(sql, conn).to_excel(writer, sheet_name=hoja, index=False)
        return salida.getvalue()
    finally:
        conn.close()


def generar_archivo_log():
    df = leer_db("SELECT id_log, fecha, usuario, accion, detalle FROM AUDITORIA_LOG ORDER BY id_log")
    lineas = [
        f"{r.fecha:%Y-%m-%d %H:%M:%S} | {r.usuario} | {r.accion} | {r.detalle}"
        for r in df.itertuples(index=False)
    ]
    return "\n".join(lineas).encode("utf-8")


# ==========================================
# 7. INICIO DE SESIÓN
# ==========================================
if not st.session_state.autenticado:
    st.markdown("<h2 style='text-align: center;'>🔐 Acceso al Sistema POS Angelmi Market</h2>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 1.5, 1])
    with c2:
        with st.form("form_login"):
            user_input = st.text_input("Usuario")
            pass_input = st.text_input("Contraseña", type="password")
            btn_login = st.form_submit_button("Iniciar Sesión", use_container_width=True)

        if btn_login:
            usuario = user_input.strip()
            if not usuario or not pass_input:
                st.warning("Ingresa usuario y contraseña.")
            elif intentos_fallidos_recientes(usuario[:50]) >= MAX_INTENTOS:
                st.error(f"Demasiados intentos fallidos. Intenta de nuevo en {VENTANA_BLOQUEO_MIN} minutos.")
            else:
                user_data = validar_login(usuario, pass_input)
                if user_data:
                    st.session_state.autenticado = True
                    st.session_state.usuario_actual = {
                        "id": user_data[0],
                        "nombre": user_data[1],
                        "cargo": user_data[2],
                        "usuario": user_data[3],
                    }
                    registrar_log("INICIO_SESION", f"El usuario {user_data[3]} ({user_data[2]}) inició sesión.")
                    st.rerun()
                else:
                    registrar_log("LOGIN_FALLIDO", "Intento de inicio de sesión fallido.", usuario=usuario[:50])
                    st.error("Usuario o contraseña incorrectos.")
    st.stop()


# ==========================================
# 8. BARRA LATERAL
# ==========================================
st.sidebar.title("🏪 Angelmi Market")
st.sidebar.caption(
    f"👤 Conectado: **{st.session_state.usuario_actual['nombre']}** ({rol_actual()})"
)

if st.sidebar.button("🚪 Cerrar Sesión"):
    registrar_log("CIERRE_SESION", f"El usuario {st.session_state.usuario_actual['usuario']} cerró sesión.")
    st.session_state.autenticado = False
    st.session_state.usuario_actual = None
    st.session_state.carrito = []
    st.session_state.excel_bytes = None
    st.rerun()

with st.sidebar.expander("🔑 Cambiar mi contraseña"):
    with st.form("form_cambio_clave", clear_on_submit=True):
        clave_actual = st.text_input("Contraseña actual", type="password")
        clave_nueva = st.text_input("Nueva contraseña", type="password")
        clave_repetida = st.text_input("Repetir nueva contraseña", type="password")
        if st.form_submit_button("Actualizar contraseña"):
            error_clave = politica_clave(clave_nueva)
            if not verificar_clave_empleado(st.session_state.usuario_actual["id"], clave_actual):
                st.error("La contraseña actual es incorrecta.")
            elif error_clave:
                st.error(error_clave)
            elif clave_nueva != clave_repetida:
                st.error("Las contraseñas nuevas no coinciden.")
            else:
                with db_cursor() as cur:
                    cur.execute("UPDATE EMPLEADO SET clave = %s WHERE id_empleado = %s",
                                (hashear_clave(clave_nueva), st.session_state.usuario_actual["id"]))
                    registrar_log("CLAVE_CAMBIADA", "El usuario cambió su propia contraseña.", cur)
                st.success("Contraseña actualizada.")

st.sidebar.divider()

if es_admin():
    if st.sidebar.button("📊 Preparar respaldo (Excel)", use_container_width=True):
        with st.spinner("Generando respaldo..."):
            st.session_state.excel_bytes = generar_reporte_excel()
        registrar_log("RESPALDO_GENERADO", "Se generó un respaldo completo en Excel.")
    if st.session_state.excel_bytes:
        st.sidebar.download_button(
            label="⬇️ Descargar respaldo (.xlsx)",
            data=st.session_state.excel_bytes,
            file_name=f"Respaldo_AngelmiMarket_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    st.sidebar.divider()

menu_permitido = MENU_POR_ROL.get(rol_actual(), [M_PRODUCTOS])
opcion = st.sidebar.radio("Menú de Opciones", menu_permitido)


# ==========================================
# 9. ELIMINACIÓN GENÉRICA (solo Administrador, con contraseña)
# ==========================================
def eliminar_registro(tabla, columna_id, valor, accion, detalle, clave, mensaje_ok, mensaje_fk):
    """tabla y columna_id son constantes del código (nunca datos del usuario)."""
    if not validar_clave_admin(clave):
        st.error("Contraseña de Administrador incorrecta.")
        return
    try:
        with db_cursor() as cur:
            cur.execute(f"DELETE FROM {tabla} WHERE {columna_id} = %s", (int(valor),))
            registrar_log(accion, detalle, cur)
    except psycopg2.errors.ForeignKeyViolation:
        st.error(mensaje_fk)
        return
    except Exception as e:
        st.error(f"Error al eliminar: {e}")
        return
    invalidar_cache()
    flash("success", mensaje_ok)
    st.rerun()


# ==========================================
# MÓDULO 1: PUNTO DE VENTA
# ==========================================
def procesar_venta(id_cliente, carrito):
    """
    Todo en una sola transacción: si algo falla (p. ej. stock insuficiente), no se guarda nada.
    El precio se toma de la base de datos (no del navegador) y el stock se descuenta solo si alcanza.
    """
    lineas, agotados = [], []
    with db_cursor() as cur:
        for item in sorted(carrito, key=lambda i: i["id_producto"]):   # orden fijo: evita bloqueos cruzados
            cantidad = int(item["cantidad"])
            cur.execute(
                "UPDATE PRODUCTO SET stock = stock - %s "
                "WHERE id_producto = %s AND activo AND stock >= %s "
                "RETURNING stock, nombre, precio",
                (cantidad, int(item["id_producto"]), cantidad)
            )
            fila = cur.fetchone()
            if fila is None:
                raise ValueError(f"Stock insuficiente o producto no disponible: {item['nombre']}")
            stock_restante, nombre, precio = fila
            if stock_restante == 0:
                agotados.append(nombre)
            lineas.append((int(item["id_producto"]), nombre, cantidad, precio, precio * cantidad))

        total = sum((l[4] for l in lineas), Decimal("0.00"))
        cur.execute(
            "INSERT INTO VENTA (id_cliente, id_empleado, total) VALUES (%s, %s, %s) RETURNING id_venta",
            (int(id_cliente), int(st.session_state.usuario_actual["id"]), total)
        )
        id_venta = cur.fetchone()[0]
        for id_prod, _nombre, cantidad, precio, subtotal in lineas:
            cur.execute(
                "INSERT INTO DETALLE_VENTA (id_venta, id_producto, cantidad, precio_unitario, subtotal) "
                "VALUES (%s, %s, %s, %s, %s)",
                (id_venta, id_prod, cantidad, precio, subtotal)
            )
        detalle = ", ".join(f"{l[1]} (x{l[2]})" for l in lineas)
        registrar_log("VENTA_PROCESADA", f"Venta N°{id_venta} por S/{total:.2f}. Productos: {detalle}", cur)
    return id_venta, total, agotados


def modulo_pos():
    st.title("🛒 Punto de Venta")
    df_productos = consultar_db(
        "SELECT p.id_producto, p.nombre, p.precio, p.stock, c.nombre AS categoria "
        "FROM PRODUCTO p LEFT JOIN CATEGORIA c ON p.id_categoria = c.id_categoria "
        "WHERE p.activo ORDER BY p.nombre"
    )
    df_clientes = consultar_db("SELECT id_cliente, nombre FROM CLIENTE ORDER BY nombre")

    if df_productos.empty:
        st.warning("No hay productos activos registrados.")
        return
    if df_clientes.empty:
        st.warning("Registra al menos un cliente (por ejemplo, 'Público General') para vender.")
        return

    productos = {int(r.id_producto): r for r in df_productos.itertuples(index=False)}
    clientes = {int(i): n for i, n in zip(df_clientes["id_cliente"], df_clientes["nombre"])}

    col_izq, col_der = st.columns(2)

    with col_izq:
        st.subheader("1. Selección de Producto")
        prod_sel = st.selectbox(
            "Buscar Producto:",
            options=list(productos.keys()),
            format_func=lambda i: f"{productos[i].nombre} - S/ {float(productos[i].precio):.2f} (Stock: {int(productos[i].stock)})"
        )
        prod = productos[prod_sel]
        stock = int(prod.stock)
        if stock <= 0:
            st.warning("Este producto está sin stock.")
        cantidad = st.number_input("Cantidad:", min_value=1, max_value=max(stock, 1), value=1, step=1, disabled=stock <= 0)

        if st.button("➕ Agregar al Carrito", use_container_width=True, disabled=stock <= 0):
            en_carrito = next((i for i in st.session_state.carrito if i["id_producto"] == prod_sel), None)
            ya_agregado = en_carrito["cantidad"] if en_carrito else 0
            if ya_agregado + int(cantidad) > stock:
                st.warning("No hay suficiente stock disponible.")
            elif en_carrito:
                en_carrito["cantidad"] += int(cantidad)
                en_carrito["subtotal"] = round(en_carrito["cantidad"] * en_carrito["precio"], 2)
                st.success(f"Se actualizó la cantidad de {prod.nombre}.")
            else:
                st.session_state.carrito.append({
                    "id_producto": prod_sel,
                    "nombre": str(prod.nombre),
                    "precio": float(prod.precio),
                    "cantidad": int(cantidad),
                    "subtotal": round(float(prod.precio) * int(cantidad), 2),
                })
                st.success(f"{prod.nombre} agregado al carrito.")

    with col_der:
        st.subheader("2. Detalle de la Venta")
        id_cli = st.selectbox("Cliente:", options=list(clientes.keys()), format_func=lambda i: clientes[i])
        st.text_input("Atendido por:", value=st.session_state.usuario_actual["nombre"], disabled=True)

        if st.session_state.carrito:
            df_cart = pd.DataFrame(st.session_state.carrito)
            st.dataframe(df_cart[["nombre", "precio", "cantidad", "subtotal"]], use_container_width=True)
            total_estimado = float(df_cart["subtotal"].sum())
            st.markdown(f"### **Total a Pagar: S/ {total_estimado:.2f}**")

            b1, b2 = st.columns(2)
            with b1:
                if st.button("✅ Procesar Venta", use_container_width=True, type="primary"):
                    try:
                        id_venta, total, agotados = procesar_venta(id_cli, st.session_state.carrito)
                    except ValueError as e:          # stock insuficiente: nada se guardó
                        invalidar_cache()
                        st.error(str(e))
                    except Exception as e:
                        st.error(f"Error procesando venta: {e}")
                    else:
                        st.session_state.carrito = []
                        invalidar_cache()
                        for nombre in agotados:
                            flash("toast", f"🚨 ¡ATENCIÓN! El producto '{nombre}' se ha quedado SIN STOCK.")
                        flash("balloons", "")
                        flash("success", f"🎉 ¡Venta N° {id_venta} registrada con éxito! Total: S/ {total:.2f}")
                        st.rerun()
            with b2:
                if st.button("🗑️ Vaciar Carrito", use_container_width=True):
                    st.session_state.carrito = []
                    st.rerun()
        else:
            st.info("El carrito de compras está vacío.")


# ==========================================
# MÓDULO 2: SALA ESTADÍSTICA
# ==========================================
def modulo_analytics():
    st.title("📈 Sala Estadística y Análisis de Negocio")
    st.caption("Métricas clave de rendimiento, ventas e inventario.")

    df_kpi_v = consultar_db("SELECT COUNT(id_venta) AS total_ventas, COALESCE(SUM(total),0) AS total_ingresos, COALESCE(AVG(total),0) AS ticket_promedio FROM VENTA")
    df_kpi_units = consultar_db("SELECT COALESCE(SUM(cantidad),0) AS unidades_vendidas FROM DETALLE_VENTA")
    df_estrella = consultar_db("SELECT p.nombre, SUM(d.cantidad) AS total_cant FROM DETALLE_VENTA d JOIN PRODUCTO p ON d.id_producto = p.id_producto GROUP BY p.nombre ORDER BY total_cant DESC LIMIT 1")
    df_agotados = consultar_db("SELECT COUNT(*) AS count FROM PRODUCTO WHERE stock = 0 AND activo")

    total_ingresos = df_kpi_v["total_ingresos"].values[0] if not df_kpi_v.empty else 0.0
    ticket_prom = df_kpi_v["ticket_promedio"].values[0] if not df_kpi_v.empty else 0.0
    total_unidades = df_kpi_units["unidades_vendidas"].values[0] if not df_kpi_units.empty else 0
    prod_top = df_estrella["nombre"].values[0] if not df_estrella.empty else "N/A"
    cant_agotados = df_agotados["count"].values[0] if not df_agotados.empty else 0

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("💰 Total Ingresos", f"S/ {total_ingresos:,.2f}")
    k2.metric("📦 Unidades Vendidas", f"{total_unidades:,}")
    k3.metric("🎟️ Ticket Promedio", f"S/ {ticket_prom:,.2f}")
    k4.metric("🏆 Producto Estrella", prod_top)
    k5.metric("🚨 Stock Cero (Agotados)", f"{cant_agotados} ítems", delta_color="inverse")

    st.divider()
    g1, g2 = st.columns(2)
    with g1:
        st.subheader("📊 Ventas por Categoría (S/)")
        df_cat = consultar_db("""
            SELECT c.nombre AS "Categoría", SUM(d.subtotal) AS "Monto (S/)"
            FROM DETALLE_VENTA d
            JOIN PRODUCTO p ON d.id_producto = p.id_producto
            JOIN CATEGORIA c ON p.id_categoria = c.id_categoria
            GROUP BY c.nombre ORDER BY "Monto (S/)" DESC
        """)
        if not df_cat.empty:
            st.bar_chart(df_cat.set_index("Categoría"))
        else:
            st.info("Aún no hay datos de ventas registradas.")
    with g2:
        st.subheader("📈 Tendencia Histórica de Ventas")
        df_fecha = consultar_db("""
            SELECT DATE(fecha) AS "Fecha", SUM(total) AS "Ingresos (S/)"
            FROM VENTA GROUP BY DATE(fecha) ORDER BY "Fecha" ASC
        """)
        if not df_fecha.empty:
            st.line_chart(df_fecha.set_index("Fecha"))
        else:
            st.info("Aún no hay historial de fechas.")

    st.divider()
    st.subheader("👑 Ranking Completo de Clientes")
    df_rank = consultar_db("""
        SELECT c.id_cliente AS "ID", c.nombre AS "Nombre Cliente", c.documento AS "DNI / RUC",
               c.telefono AS "Teléfono", COUNT(v.id_venta) AS "N° Compras",
               COALESCE(SUM(v.total), 0) AS "Total Gastado (S/)"
        FROM CLIENTE c LEFT JOIN VENTA v ON c.id_cliente = v.id_cliente
        GROUP BY c.id_cliente, c.nombre, c.documento, c.telefono
        ORDER BY "Total Gastado (S/)" DESC
    """)
    if not df_rank.empty:
        st.dataframe(df_rank, use_container_width=True)
    else:
        st.info("No se han registrado clientes.")

    st.divider()
    p1, p2 = st.columns(2)
    with p1:
        st.subheader("🔥 Top 5 Productos Más Vendidos")
        st.dataframe(consultar_db("""
            SELECT p.nombre AS "Producto", SUM(d.cantidad) AS "Cant. Vendida", SUM(d.subtotal) AS "Total (S/)"
            FROM DETALLE_VENTA d JOIN PRODUCTO p ON d.id_producto = p.id_producto
            GROUP BY p.nombre ORDER BY "Cant. Vendida" DESC LIMIT 5
        """), use_container_width=True)
    with p2:
        st.subheader("⚠️ Alerta de Inventario Crítico (Stock <= 5)")
        st.dataframe(consultar_db("""
            SELECT p.id_producto AS "ID", p.nombre AS "Producto", p.stock AS "Stock Actual", c.nombre AS "Categoría"
            FROM PRODUCTO p LEFT JOIN CATEGORIA c ON p.id_categoria = c.id_categoria
            WHERE p.stock <= 5 AND p.activo ORDER BY p.stock ASC
        """), use_container_width=True)


# ==========================================
# MÓDULO 3: GESTIÓN DE PRODUCTOS
# ==========================================
def modulo_productos():
    puede_editar = rol_actual() in ("Administrador", "Almacenero")
    st.title("📦 Gestión de Inventario y Productos" if puede_editar else "📦 Consulta de Stock")

    df_prod = consultar_db("""
        SELECT p.id_producto, p.nombre, p.precio, p.stock, c.nombre AS categoria, pr.nombre AS proveedor, p.fecha_registro
        FROM PRODUCTO p
        LEFT JOIN CATEGORIA c ON p.id_categoria = c.id_categoria
        LEFT JOIN PROVEEDOR pr ON p.id_proveedor = pr.id_proveedor
        WHERE p.activo ORDER BY p.id_producto DESC
    """)
    st.subheader("Listado de Productos")
    st.dataframe(df_prod, use_container_width=True)

    if not puede_editar:
        st.info("🔒 Tu rol solo permite consultar el stock.")
        return

    df_cat = consultar_db("SELECT id_categoria, nombre FROM CATEGORIA ORDER BY nombre")
    df_prov = consultar_db("SELECT id_proveedor, nombre FROM PROVEEDOR ORDER BY nombre")
    categorias = {int(i): n for i, n in zip(df_cat["id_categoria"], df_cat["nombre"])}
    proveedores = {int(i): n for i, n in zip(df_prov["id_proveedor"], df_prov["nombre"])}

    col_add, col_del = st.columns(2)

    with col_add:
        with st.expander("➕ Registrar Nuevo Producto"):
            if not categorias or not proveedores:
                st.warning("Primero registra al menos una categoría y un proveedor.")
            else:
                with st.form("form_nuevo_prod"):
                    nom = st.text_input("Nombre del Producto", max_chars=100)
                    pre = st.number_input("Precio (S/)", min_value=0.1, value=1.0, step=0.5)
                    stk = st.number_input("Stock Inicial", min_value=1, value=10, step=1)
                    cat = st.selectbox("Categoría", options=list(categorias.keys()), format_func=lambda i: categorias[i])
                    prv = st.selectbox("Proveedor", options=list(proveedores.keys()), format_func=lambda i: proveedores[i])
                    if st.form_submit_button("Guardar Producto"):
                        if not nom.strip():
                            st.warning("El nombre del producto es obligatorio.")
                        else:
                            precio = Decimal(str(pre)).quantize(Decimal("0.01"))
                            try:
                                with db_cursor() as cur:
                                    cur.execute(
                                        "INSERT INTO PRODUCTO (nombre, precio, stock, id_categoria, id_proveedor) VALUES (%s, %s, %s, %s, %s)",
                                        (nom.strip(), precio, int(stk), cat, prv)
                                    )
                                    registrar_log("PRODUCTO_CREADO", f"Creación de producto: {nom.strip()} - Precio S/{precio:.2f} - Stock: {int(stk)}", cur)
                            except Exception as e:
                                st.error(f"Error al registrar producto: {e}")
                            else:
                                invalidar_cache()
                                flash("success", "Producto registrado exitosamente.")
                                st.rerun()

    with col_del:
        if es_admin():
            with st.expander("🗑️ Desactivar Producto (Solo Admin)"):
                if df_prod.empty:
                    st.info("No hay productos activos.")
                else:
                    activos = {int(i): n for i, n in zip(df_prod["id_producto"], df_prod["nombre"])}
                    with st.form("form_elim_prod"):
                        st.caption("El producto deja de aparecer en el sistema, pero su historial de ventas se conserva.")
                        prod_elim = st.selectbox("Seleccionar producto:", options=list(activos.keys()), format_func=lambda i: activos[i])
                        pass_confirm = st.text_input("Confirmar con Contraseña de Admin:", type="password")
                        if st.form_submit_button("❌ Desactivar Producto"):
                            if not validar_clave_admin(pass_confirm):
                                st.error("Contraseña de administrador incorrecta.")
                            else:
                                try:
                                    with db_cursor() as cur:
                                        cur.execute("UPDATE PRODUCTO SET activo = FALSE WHERE id_producto = %s", (prod_elim,))
                                        registrar_log("PRODUCTO_DESACTIVADO", f"Desactivado producto ID {prod_elim} ({activos[prod_elim]}) por el Admin.", cur)
                                except Exception as e:
                                    st.error(f"Error al desactivar producto: {e}")
                                else:
                                    invalidar_cache()
                                    flash("success", f"Producto '{activos[prod_elim]}' desactivado. Su historial de ventas se conserva.")
                                    st.rerun()
        else:
            st.info("🔒 Desactivar productos requiere permisos de Administrador.")


# ==========================================
# MÓDULO 4: CATEGORÍAS Y PROVEEDORES
# ==========================================
def modulo_catprov():
    st.title("📁 Categorías y Proveedores")
    df_cat = consultar_db("SELECT * FROM CATEGORIA ORDER BY id_categoria")
    df_prov = consultar_db("SELECT * FROM PROVEEDOR ORDER BY id_proveedor")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Categorías")
        st.dataframe(df_cat, use_container_width=True)
        with st.form("form_cat"):
            nom_cat = st.text_input("Nombre de Categoría", max_chars=100)
            desc_cat = st.text_input("Descripción", max_chars=255)
            if st.form_submit_button("Agregar Categoría"):
                if not nom_cat.strip():
                    st.warning("El nombre es obligatorio.")
                else:
                    try:
                        with db_cursor() as cur:
                            cur.execute("INSERT INTO CATEGORIA (nombre, descripcion) VALUES (%s, %s)", (nom_cat.strip(), desc_cat.strip()))
                            registrar_log("CATEGORIA_CREADA", f"Categoría creada: {nom_cat.strip()}", cur)
                    except psycopg2.errors.UniqueViolation:
                        st.error("No se pudo agregar: la categoría ya existe en el sistema.")
                    except Exception as e:
                        st.error(f"Error: {e}")
                    else:
                        invalidar_cache()
                        flash("success", "Categoría agregada.")
                        st.rerun()

        if es_admin() and not df_cat.empty:
            cats = {int(i): n for i, n in zip(df_cat["id_categoria"], df_cat["nombre"])}
            with st.expander("🗑️ Eliminar Categoría (Admin)"):
                with st.form("form_del_cat"):
                    cat_elim = st.selectbox("Categoría a eliminar:", options=list(cats.keys()), format_func=lambda i: cats[i])
                    pass_cat = st.text_input("Contraseña de Admin:", type="password")
                    if st.form_submit_button("Eliminar Categoría"):
                        eliminar_registro("CATEGORIA", "id_categoria", cat_elim, "CATEGORIA_ELIMINADA",
                                          f"Eliminada categoría: {cats[cat_elim]}", pass_cat,
                                          "Categoría eliminada.",
                                          "No se puede eliminar una categoría asignada a productos existentes.")

    with col2:
        st.subheader("Proveedores")
        st.dataframe(df_prov, use_container_width=True)
        with st.form("form_prov"):
            nom_prv = st.text_input("Nombre del Proveedor", max_chars=100)
            ruc = st.text_input("RUC / DNI", max_chars=20)
            tel = st.text_input("Teléfono", max_chars=20)
            email = st.text_input("Email", max_chars=100)
            if st.form_submit_button("Agregar Proveedor"):
                if not nom_prv.strip():
                    st.warning("El nombre es obligatorio.")
                else:
                    try:
                        with db_cursor() as cur:
                            cur.execute("INSERT INTO PROVEEDOR (nombre, ruc_dni, telefono, email) VALUES (%s, %s, %s, %s)",
                                        (nom_prv.strip(), ruc.strip(), tel.strip(), email.strip()))
                            registrar_log("PROVEEDOR_CREADO", f"Proveedor creado: {nom_prv.strip()}", cur)
                    except Exception as e:
                        st.error(f"Error: {e}")
                    else:
                        invalidar_cache()
                        flash("success", "Proveedor agregado.")
                        st.rerun()

        if es_admin() and not df_prov.empty:
            provs = {int(i): n for i, n in zip(df_prov["id_proveedor"], df_prov["nombre"])}
            with st.expander("🗑️ Eliminar Proveedor (Admin)"):
                with st.form("form_del_prov"):
                    prov_elim = st.selectbox("Proveedor a eliminar:", options=list(provs.keys()), format_func=lambda i: provs[i])
                    pass_prv = st.text_input("Contraseña de Admin:", type="password", key="pass_prv")
                    if st.form_submit_button("Eliminar Proveedor"):
                        eliminar_registro("PROVEEDOR", "id_proveedor", prov_elim, "PROVEEDOR_ELIMINADO",
                                          f"Eliminado proveedor: {provs[prov_elim]}", pass_prv,
                                          "Proveedor eliminado.",
                                          "No se puede eliminar un proveedor asignado a productos existentes.")


# ==========================================
# MÓDULO 5: CLIENTES Y EMPLEADOS
# ==========================================
def seccion_clientes():
    st.subheader("Clientes")
    df_cli = consultar_db("SELECT id_cliente, nombre, documento, telefono, direccion, fecha_registro FROM CLIENTE ORDER BY id_cliente DESC")
    st.dataframe(df_cli, use_container_width=True)

    with st.form("form_cli"):
        nom = st.text_input("Nombre Completo", max_chars=100)
        doc = st.text_input("DNI / RUC", max_chars=20)
        tel = st.text_input("Teléfono", max_chars=20)
        dir_cli = st.text_input("Dirección", max_chars=200)
        if st.form_submit_button("Registrar Cliente"):
            if not (nom.strip() and doc.strip()):
                st.warning("El nombre y el DNI / RUC son obligatorios.")
            else:
                try:
                    with db_cursor() as cur:
                        cur.execute("INSERT INTO CLIENTE (nombre, documento, telefono, direccion) VALUES (%s, %s, %s, %s)",
                                    (nom.strip(), doc.strip(), tel.strip(), dir_cli.strip()))
                        registrar_log("CLIENTE_CREADO", f"Cliente creado: {nom.strip()} ({doc.strip()})", cur)
                except psycopg2.errors.UniqueViolation:
                    st.error("Error: el DNI o RUC ingresado ya se encuentra registrado.")
                except Exception as e:
                    st.error(f"Error: {e}")
                else:
                    invalidar_cache()
                    flash("success", "Cliente registrado.")
                    st.rerun()

    if es_admin() and not df_cli.empty:
        clientes = {int(i): n for i, n in zip(df_cli["id_cliente"], df_cli["nombre"])}
        with st.expander("🗑️ Eliminar Cliente (Admin)"):
            with st.form("form_del_cli"):
                cli_elim = st.selectbox("Cliente a eliminar:", options=list(clientes.keys()), format_func=lambda i: clientes[i])
                pass_cli = st.text_input("Contraseña de Admin:", type="password", key="pass_cli")
                if st.form_submit_button("Eliminar Cliente"):
                    eliminar_registro("CLIENTE", "id_cliente", cli_elim, "CLIENTE_ELIMINADO",
                                      f"Eliminado cliente: {clientes[cli_elim]}", pass_cli,
                                      "Cliente eliminado.",
                                      "No se puede eliminar un cliente con ventas registradas.")


def seccion_empleados():
    st.subheader("Empleados (Gestión de Usuarios)")
    df_emp = consultar_db("SELECT id_empleado, nombre, cargo, usuario, activo, fecha_registro FROM EMPLEADO ORDER BY id_empleado DESC")
    st.dataframe(df_emp, use_container_width=True)

    with st.expander("➕ Crear Nuevo Credencial / Empleado (Admin)"):
        with st.form("form_emp"):
            nom_emp = st.text_input("Nombre del Empleado", max_chars=100)
            cargo = st.selectbox("Asignar Rol / Permisos", ROLES)
            user = st.text_input("Usuario", max_chars=50)
            passw = st.text_input(f"Contraseña (mínimo {LARGO_MIN_CLAVE} caracteres)", type="password")
            if st.form_submit_button("Crear Credencial"):
                error_clave = politica_clave(passw)
                if not (nom_emp.strip() and user.strip() and passw):
                    st.warning("Todos los campos son obligatorios.")
                elif error_clave:
                    st.error(error_clave)
                else:
                    try:
                        with db_cursor() as cur:
                            cur.execute("INSERT INTO EMPLEADO (nombre, cargo, usuario, clave) VALUES (%s, %s, %s, %s)",
                                        (nom_emp.strip(), cargo, user.strip(), hashear_clave(passw)))
                            registrar_log("USUARIO_CREADO", f"Creado credencial para {user.strip()} con rol: {cargo}", cur)
                    except psycopg2.errors.UniqueViolation:
                        st.error("El nombre de usuario ya existe en el sistema.")
                    except Exception as e:
                        st.error(f"Error: {e}")
                    else:
                        invalidar_cache()
                        flash("success", f"Empleado {user.strip()} registrado correctamente con rol {cargo}.")
                        st.rerun()

    with st.expander("🗑️ Dar de baja Usuario / Empleado (Admin)"):
        disponibles = df_emp[(df_emp["id_empleado"] != st.session_state.usuario_actual["id"]) & (df_emp["activo"])]
        if disponibles.empty:
            st.info("No hay otros usuarios activos para dar de baja.")
        else:
            etiquetas = {int(r.id_empleado): f"{r.nombre} ({r.usuario})" for r in disponibles.itertuples(index=False)}
            with st.form("form_del_emp"):
                st.caption("La baja es lógica: el usuario ya no puede ingresar, pero su historial se conserva.")
                emp_elim = st.selectbox("Seleccionar empleado:", options=list(etiquetas.keys()), format_func=lambda i: etiquetas[i])
                pass_emp = st.text_input("Contraseña de Admin actual:", type="password", key="pass_emp")
                if st.form_submit_button("Dar de Baja Empleado"):
                    if not validar_clave_admin(pass_emp):
                        st.error("Contraseña de Administrador incorrecta.")
                    else:
                        try:
                            with db_cursor() as cur:
                                cur.execute("UPDATE EMPLEADO SET activo = FALSE WHERE id_empleado = %s", (emp_elim,))
                                registrar_log("USUARIO_BAJA", f"Dado de baja el usuario {etiquetas[emp_elim]} por el Administrador.", cur)
                        except Exception as e:
                            st.error(f"Error: {e}")
                        else:
                            invalidar_cache()
                            flash("success", f"Usuario {etiquetas[emp_elim]} dado de baja.")
                            st.rerun()


def modulo_clientes_empleados():
    if es_admin():
        st.title("👥 Clientes y Empleados")
        col1, col2 = st.columns(2)
        with col1:
            seccion_clientes()
        with col2:
            seccion_empleados()
    else:
        st.title("👥 Clientes")
        seccion_clientes()


# ==========================================
# MÓDULO 6: HISTÓRICO DE VENTAS
# ==========================================
def modulo_historico():
    st.title("📊 Reporte e Histórico de Ventas")
    df_ventas = consultar_db(HOJAS_EXCEL["Ventas"])
    df_detalles = consultar_db(HOJAS_EXCEL["Detalle_Ventas"])

    m1, m2, m3 = st.columns(3)
    m1.metric("Total Ventas (S/)", f"S/ {df_ventas['total'].sum():.2f}" if not df_ventas.empty else "S/ 0.00")
    m2.metric("N° Transacciones", len(df_ventas))
    m3.metric("Ticket Promedio", f"S/ {df_ventas['total'].mean():.2f}" if not df_ventas.empty else "S/ 0.00")

    st.subheader("Registro de Comprobantes")
    if not df_ventas.empty:
        st.dataframe(df_ventas, use_container_width=True)
        st.subheader("🔍 Consultar Detalle de una Venta")
        id_v_sel = st.selectbox("Seleccione ID de Venta:", df_ventas["id_venta"].tolist())
        st.dataframe(df_detalles[df_detalles["id_venta"] == id_v_sel][["producto", "cantidad", "precio_unitario", "subtotal"]],
                     use_container_width=True)
    else:
        st.info("Aún no se han realizado ventas.")


# ==========================================
# MÓDULO 7: BITÁCORA DE AUDITORÍA
# ==========================================
def modulo_bitacora():
    st.title("📜 Bitácora de Auditoría y Registro de Transacciones (.log)")
    st.info("🔒 Registro inalterable: la base de datos rechaza cualquier UPDATE, DELETE o TRUNCATE sobre esta tabla.")
    df_logs = leer_db("""
        SELECT l.id_log AS "ID Log", l.fecha AS "Fecha/Hora", l.usuario AS "Usuario", e.nombre AS "Empleado",
               e.cargo AS "Rol", l.accion AS "Acción", l.detalle AS "Detalle"
        FROM AUDITORIA_LOG l LEFT JOIN EMPLEADO e ON l.id_empleado = e.id_empleado
        ORDER BY l.id_log DESC
    """)
    st.download_button("📥 Descargar auditoria_angelmi.log", data=generar_archivo_log(),
                       file_name="auditoria_angelmi.log", mime="text/plain")
    st.dataframe(df_logs, use_container_width=True)


# ==========================================
# MÓDULO 8: MODELO ENTIDAD-RELACIÓN
# ==========================================
def modulo_mer():
    st.title("📐 Diagrama Entidad - Relación (MER)")
    st.markdown("Representación relacional completa de la base de datos **AngelmiMarketDB** incluyendo la tabla de Auditoría.")
    graphviz_code = """
    digraph MER {
        rankdir=LR;
        node [shape=rectangle, style=filled, fillcolor="#EBF5FB", color="#1F618D", fontname="Helvetica"];
        edge [color="#2E4053", fontname="Helvetica", fontsize=10];

        CATEGORIA [label="CATEGORIA\\n- id_categoria (PK)\\n- nombre (UNIQUE)\\n- descripcion"];
        PROVEEDOR [label="PROVEEDOR\\n- id_proveedor (PK)\\n- nombre\\n- ruc_dni\\n- telefono\\n- email"];
        CLIENTE [label="CLIENTE\\n- id_cliente (PK)\\n- nombre\\n- documento (UNIQUE)\\n- telefono\\n- direccion\\n- fecha_registro"];
        EMPLEADO [label="EMPLEADO\\n- id_empleado (PK)\\n- nombre\\n- cargo\\n- usuario (UNIQUE)\\n- clave (hash bcrypt)\\n- activo\\n- fecha_registro"];
        PRODUCTO [label="PRODUCTO\\n- id_producto (PK)\\n- nombre\\n- precio (CHECK >= 0)\\n- stock (CHECK >= 0)\\n- id_categoria (FK)\\n- id_proveedor (FK)\\n- activo\\n- fecha_registro"];
        VENTA [label="VENTA\\n- id_venta (PK)\\n- fecha\\n- id_cliente (FK)\\n- id_empleado (FK)\\n- total (CHECK >= 0)"];
        DETALLE_VENTA [label="DETALLE_VENTA\\n- id_detalle (PK)\\n- id_venta (FK)\\n- id_producto (FK)\\n- cantidad (CHECK > 0)\\n- precio_unitario (CHECK >= 0)\\n- subtotal (CHECK = cantidad * precio_unitario)"];
        AUDITORIA_LOG [label="AUDITORIA_LOG\\n- id_log (PK)\\n- fecha\\n- id_empleado (FK)\\n- usuario\\n- accion\\n- detalle"];

        CATEGORIA -> PRODUCTO [label="1 : N"];
        PROVEEDOR -> PRODUCTO [label="1 : N"];
        PRODUCTO -> DETALLE_VENTA [label="1 : N"];
        VENTA -> DETALLE_VENTA [label="1 : N"];
        CLIENTE -> VENTA [label="1 : N"];
        EMPLEADO -> VENTA [label="1 : N"];
        EMPLEADO -> AUDITORIA_LOG [label="1 : N"];
    }
    """
    st.graphviz_chart(graphviz_code)


# ==========================================
# 10. ENRUTADOR (con verificación de permisos)
# ==========================================
MODULOS = {
    M_POS: modulo_pos,
    M_ANALYTICS: modulo_analytics,
    M_PRODUCTOS: modulo_productos,
    M_CATPROV: modulo_catprov,
    M_CLIEMP: modulo_clientes_empleados,
    M_HISTORICO: modulo_historico,
    M_MER: modulo_mer,
    M_BITACORA: modulo_bitacora,
}

if errores_bd and es_admin():
    with st.expander("⚠️ Avisos al preparar la base de datos (solo visible para el Administrador)"):
        for err in errores_bd:
            st.code(err)

mostrar_mensajes()

if opcion not in menu_permitido:       # defensa extra: nunca ejecutar un módulo que el rol no tiene
    st.error("🔒 No tienes permisos para acceder a este módulo.")
    st.stop()

MODULOS[opcion]()
