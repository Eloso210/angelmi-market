import streamlit as st
import psycopg2
import pandas as pd
import io
from datetime import datetime

# ==========================================
# 1. CONFIGURACIÓN DE PÁGINA
# ==========================================
st.set_page_config(
    page_title="Angelmi Market Web POS",
    page_icon="🛒",
    layout="wide"
)

# ==========================================
# 2. CONTROL DE SESIÓN Y AUTENTICACIÓN
# ==========================================
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "usuario_actual" not in st.session_state:
    st.session_state.usuario_actual = None
if "carrito" not in st.session_state:
    st.session_state.carrito = []

# ==========================================
# 3. CONEXIÓN Y CONSULTAS OPTIMIZADAS CON CACHÉ
# ==========================================
def get_connection():
    try:
        conn_uri = st.secrets["postgres"]["url"]
    except Exception:
        conn_uri = "postgresql://postgres.wfyyszjwcadmvwghjhqz:angelmi-market2026@aws-0-sa-east-1.pooler.supabase.com:6543/postgres"
    return psycopg2.connect(conn_uri)

@st.cache_data(ttl=300)
def consultar_db(query):
    """Ejecuta consultas de lectura y las guarda en memoria para respuesta instantánea."""
    conn = get_connection()
    df = pd.read_sql(query, conn)
    conn.close()
    return df

def registrar_log(accion, detalle):
    """Registra de forma inalterable las acciones de los usuarios en la base de datos."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        emp_id = st.session_state.usuario_actual['id'] if st.session_state.usuario_actual else None
        usr = st.session_state.usuario_actual['usuario'] if st.session_state.usuario_actual else 'SISTEMA'
        cur.execute(
            "INSERT INTO AUDITORIA_LOG (id_empleado, usuario, accion, detalle) VALUES (%s, %s, %s, %s);",
            (emp_id, usr, accion, detalle)
        )
        conn.commit()
        cur.close()
        conn.close()
        st.cache_data.clear()
    except Exception as e:
        print(f"Error al registrar log: {e}")

@st.cache_resource
def verificar_base_de_datos():
    try:
        conn = get_connection()
        cur = conn.cursor()

        ddl_queries = [
            """
            CREATE TABLE IF NOT EXISTS CATEGORIA (
                id_categoria SERIAL PRIMARY KEY,
                nombre VARCHAR(100) NOT NULL,
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
                documento VARCHAR(20),
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
                usuario VARCHAR(50) UNIQUE,
                clave VARCHAR(50),
                fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS PRODUCTO (
                id_producto SERIAL PRIMARY KEY,
                nombre VARCHAR(100) NOT NULL,
                precio NUMERIC(10,2) NOT NULL,
                stock INT NOT NULL,
                id_categoria INT REFERENCES CATEGORIA(id_categoria),
                id_proveedor INT REFERENCES PROVEEDOR(id_proveedor),
                fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS VENTA (
                id_venta SERIAL PRIMARY KEY,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                id_cliente INT REFERENCES CLIENTE(id_cliente),
                id_empleado INT REFERENCES EMPLEADO(id_empleado),
                total NUMERIC(10,2) NOT NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS DETALLE_VENTA (
                id_detalle SERIAL PRIMARY KEY,
                id_venta INT REFERENCES VENTA(id_venta),
                id_producto INT REFERENCES PRODUCTO(id_producto),
                cantidad INT NOT NULL,
                precio_unitario NUMERIC(10,2) NOT NULL,
                subtotal NUMERIC(10,2) NOT NULL
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
            """
        ]

        for q in ddl_queries:
            try:
                cur.execute(q)
            except Exception:
                pass

        cur.execute("SELECT COUNT(*) FROM CATEGORIA;")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO CATEGORIA (nombre, descripcion) VALUES ('Abarrotes', 'Productos de primera necesidad'), ('Bebidas', 'Gaseosas y jugos'), ('Lácteos', 'Leche, quesos y yogur'), ('Limpieza', 'Artículos para el hogar');")

        cur.execute("SELECT COUNT(*) FROM PROVEEDOR;")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO PROVEEDOR (nombre, ruc_dni, telefono, email) VALUES ('Distribuidora Central S.A.C.', '20123456789', '987654321', 'ventas@distribuidora.pe'), ('Comercial San Juan', '20987654321', '912345678', 'contacto@sanjuan.pe');")

        cur.execute("SELECT COUNT(*) FROM CLIENTE;")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO CLIENTE (nombre, documento, telefono, direccion) VALUES ('Público General', '00000000', '000000000', 'Tienda Local'), ('Juan Pérez', '45678912', '998877665', 'Av. Central 123');")

        cur.execute("SELECT COUNT(*) FROM EMPLEADO;")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO EMPLEADO (nombre, cargo, usuario, clave) VALUES ('Admin Angelmi', 'Administrador', 'admin', 'admin123'), ('Cajero 1', 'Cajero', 'cajero1', '1234');")

        cur.execute("SELECT COUNT(*) FROM PRODUCTO;")
        if cur.fetchone()[0] == 0:
            cur.execute("""
                INSERT INTO PRODUCTO (nombre, precio, stock, id_categoria, id_proveedor) VALUES 
                ('Arroz Extra 1kg', 4.50, 50, 1, 1),
                ('Aceite Vegetal 1L', 8.20, 30, 1, 1),
                ('Leche Evaporada 400g', 3.80, 40, 3, 2),
                ('Inca Kola 1.5L', 6.50, 25, 2, 2);
            """)

        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        return str(e)

verificar_base_de_datos()

def validar_clave_admin(clave_ingresada):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT clave FROM EMPLEADO WHERE id_empleado = %s AND cargo = 'Administrador'", (st.session_state.usuario_actual['id'],))
    res = cur.fetchone()
    cur.close()
    conn.close()
    return res and res[0] == clave_ingresada

# ==========================================
# 4. FUNCIÓN EXCEL CON PESTAÑA DE AUDITORÍA
# ==========================================
@st.cache_data(ttl=300)
def generar_reporte_excel():
    conn = get_connection()
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_v = pd.read_sql("SELECT v.id_venta, v.fecha, c.nombre as cliente, e.nombre as empleado, v.total FROM VENTA v LEFT JOIN CLIENTE c ON v.id_cliente = c.id_cliente LEFT JOIN EMPLEADO e ON v.id_empleado = e.id_empleado ORDER BY v.id_venta DESC", conn)
        df_v.to_excel(writer, sheet_name='Ventas', index=False)
        
        df_dv = pd.read_sql("SELECT d.id_detalle, d.id_venta, p.nombre as producto, d.cantidad, d.precio_unitario, d.subtotal FROM DETALLE_VENTA d LEFT JOIN PRODUCTO p ON d.id_producto = p.id_producto", conn)
        df_dv.to_excel(writer, sheet_name='Detalle_Ventas', index=False)
        
        df_p = pd.read_sql("SELECT p.id_producto, p.nombre, p.precio, p.stock, c.nombre as categoria, pr.nombre as proveedor, p.fecha_registro FROM PRODUCTO p LEFT JOIN CATEGORIA c ON p.id_categoria = c.id_categoria LEFT JOIN PROVEEDOR pr ON p.id_proveedor = pr.id_proveedor ORDER BY p.id_producto DESC", conn)
        df_p.to_excel(writer, sheet_name='Productos', index=False)
        
        df_c = pd.read_sql("SELECT id_cliente, nombre, documento, telefono, direccion, fecha_registro FROM CLIENTE", conn)
        df_c.to_excel(writer, sheet_name='Clientes', index=False)
        
        df_e = pd.read_sql("SELECT id_empleado, nombre, cargo, usuario, fecha_registro FROM EMPLEADO", conn)
        df_e.to_excel(writer, sheet_name='Empleados', index=False)
        
        df_cat = pd.read_sql("SELECT * FROM CATEGORIA", conn)
        df_cat.to_excel(writer, sheet_name='Categorias', index=False)
        
        df_prv = pd.read_sql("SELECT * FROM PROVEEDOR", conn)
        df_prv.to_excel(writer, sheet_name='Proveedores', index=False)
        
        df_log = pd.read_sql("""
            SELECT l.id_log, l.fecha, l.usuario, e.nombre as empleado, e.cargo, l.accion, l.detalle
            FROM AUDITORIA_LOG l
            LEFT JOIN EMPLEADO e ON l.id_empleado = e.id_empleado
            ORDER BY l.id_log DESC
        """, conn)
        df_log.to_excel(writer, sheet_name='Log_Acciones', index=False)
        
    conn.close()
    return output.getvalue()

# ==========================================
# 5. FORMULARIO DE LOGIN
# ==========================================
def validar_login(usuario, clave):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id_empleado, nombre, cargo, usuario FROM EMPLEADO WHERE usuario = %s AND clave = %s", (usuario, clave))
    res = cur.fetchone()
    cur.close()
    conn.close()
    return res

if not st.session_state.autenticado:
    st.markdown("<h2 style='text-align: center;'>🔐 Acceso al Sistema POS Angelmi Market</h2>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 1.5, 1])
    with c2:
        with st.form("form_login"):
            user_input = st.text_input("Usuario")
            pass_input = st.text_input("Contraseña", type="password")
            btn_login = st.form_submit_button("Iniciar Sesión", use_container_width=True)
            if btn_login:
                user_data = validar_login(user_input, pass_input)
                if user_data:
                    st.session_state.autenticado = True
                    st.session_state.usuario_actual = {
                        "id": user_data[0],
                        "nombre": user_data[1],
                        "cargo": user_data[2],
                        "usuario": user_data[3]
                    }
                    registrar_log("INICIO_SESION", f"El usuario {user_data[3]} ({user_data[2]}) inició sesión.")
                    st.success(f"Bienvenido {user_data[1]}")
                    st.rerun()
                else:
                    st.error("Usuario o contraseña incorrectos.")
    st.stop()

# ==========================================
# 6. BARRA LATERAL Y NAVEGACIÓN
# ==========================================
st.sidebar.title("🏪 Angelmi Market")
es_admin = st.session_state.usuario_actual['cargo'] == "Administrador"
st.sidebar.caption(f"👤 Conectado: **{st.session_state.usuario_actual['nombre']}** ({st.session_state.usuario_actual['cargo']})")

if st.sidebar.button("🚪 Cerrar Sesión"):
    registrar_log("CIERRE_SESION", f"El usuario {st.session_state.usuario_actual['usuario']} cerró sesión.")
    st.session_state.autenticado = False
    st.session_state.usuario_actual = None
    st.session_state.carrito = []
    st.rerun()

st.sidebar.divider()

st.sidebar.download_button(
    label="📊 Descargar Respaldo (Excel)",
    data=generar_reporte_excel(),
    file_name=f"Respaldo_AngelmiMarket_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True
)

st.sidebar.divider()

opciones_menu = ["🛒 Punto de Venta (POS)", "📈 Sala Estadística (Analytics)", "📦 Gestión de Productos", "📁 Categorías y Proveedores", "👥 Clientes y Empleados", "📊 Histórico de Ventas", "📐 Modelo Entidad-Relación (MER)"]
if es_admin:
    opciones_menu.append("📜 Bitácora de Auditoría (.LDF)")

opcion = st.sidebar.radio("Menú de Opciones", opciones_menu)

# ==========================================
# MÓDULO 1: POS
# ==========================================
if opcion == "🛒 Punto de Venta (POS)":
    st.title("🛒 Punto de Venta")
    df_productos = consultar_db("SELECT p.id_producto, p.nombre, p.precio, p.stock, c.nombre as categoria FROM PRODUCTO p LEFT JOIN CATEGORIA c ON p.id_categoria = c.id_categoria")
    df_clientes = consultar_db("SELECT id_cliente, nombre FROM CLIENTE")

    col_izq, col_der = st.columns([1, 1])
    with col_izq:
        st.subheader("1. Selección de Producto")
        prod_sel = st.selectbox(
            "Buscar Producto:",
            options=df_productos['id_producto'].tolist(),
            format_func=lambda x: f"{df_productos[df_productos['id_producto']==x]['nombre'].values[0]} - S/ {df_productos[df_productos['id_producto']==x]['precio'].values[0]:.2f} (Stock: {df_productos[df_productos['id_producto']==x]['stock'].values[0]})"
        )
        info_prod = df_productos[df_productos['id_producto'] == prod_sel].iloc[0]
        cantidad = st.number_input("Cantidad:", min_value=1, max_value=int(info_prod['stock']) if info_prod['stock'] > 0 else 1, value=1)
        
        if st.button("➕ Agregar al Carrito", use_container_width=True):
            if info_prod['stock'] < cantidad:
                st.error("Stock insuficiente.")
            else:
                encontrado = False
                for item in st.session_state.carrito:
                    if item['id_producto'] == info_prod['id_producto']:
                        if item['cantidad'] + cantidad <= info_prod['stock']:
                            item['cantidad'] += cantidad
                            item['subtotal'] = item['cantidad'] * item['precio']
                            encontrado = True
                            st.success(f"Se actualizó la cantidad de {info_prod['nombre']}.")
                        else:
                            st.warning("No hay suficiente stock disponible.")
                            encontrado = True
                        break
                if not encontrado:
                    st.session_state.carrito.append({
                        'id_producto': int(info_prod['id_producto']),
                        'nombre': str(info_prod['nombre']),
                        'precio': float(info_prod['precio']),
                        'cantidad': int(cantidad),
                        'subtotal': float(info_prod['precio'] * cantidad)
                    })
                    st.success(f"{info_prod['nombre']} agregado al carrito.")

    with col_der:
        st.subheader("2. Detalle de la Venta")
        id_cli = st.selectbox("Cliente:", options=df_clientes['id_cliente'].tolist(), format_func=lambda x: df_clientes[df_clientes['id_cliente']==x]['nombre'].values[0])
        st.text_input("Atendido por:", value=st.session_state.usuario_actual['nombre'], disabled=True)
        
        if st.session_state.carrito:
            df_cart = pd.DataFrame(st.session_state.carrito)
            st.dataframe(df_cart[['nombre', 'precio', 'cantidad', 'subtotal']], use_container_width=True)
            total_venta = df_cart['subtotal'].sum()
            st.markdown(f"### **Total a Pagar: S/ {total_venta:.2f}**")
            
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ Procesar Venta", use_container_width=True, type="primary"):
                    try:
                        conn = get_connection()
                        cur = conn.cursor()
                        cur.execute("INSERT INTO VENTA (id_cliente, id_empleado, total) VALUES (%s, %s, %s) RETURNING id_venta;",
                                    (id_cli, st.session_state.usuario_actual['id'], total_venta))
                        id_venta = cur.fetchone()[0]
                        
                        detalles_log = []
                        productos_agotados = []
                        
                        for item in st.session_state.carrito:
                            cur.execute("INSERT INTO DETALLE_VENTA (id_venta, id_producto, cantidad, precio_unitario, subtotal) VALUES (%s, %s, %s, %s, %s);",
                                        (id_venta, item['id_producto'], item['cantidad'], item['precio'], item['subtotal']))
                            cur.execute("UPDATE PRODUCTO SET stock = stock - %s WHERE id_producto = %s RETURNING stock, nombre;", (item['cantidad'], item['id_producto']))
                            res_stk = cur.fetchone()
                            if res_stk and res_stk[0] == 0:
                                productos_agotados.append(res_stk[1])
                            detalles_log.append(f"{item['nombre']} (x{item['cantidad']})")
                            
                        conn.commit()
                        cur.close()
                        conn.close()
                        
                        st.session_state.carrito = []
                        registrar_log("VENTA_PROCESADA", f"Venta N°{id_venta} por S/{total_venta:.2f}. Productos: {', '.join(detalles_log)}")
                        
                        # Alerta emergente flotante arriba a la derecha si un producto llega a stock 0
                        for prod_agotado in productos_agotados:
                            st.toast(f"🚨 ¡ATENCIÓN! El producto '{prod_agotado}' se ha quedado SIN STOCK.", icon="⚠️")
                            
                        st.balloons()
                        st.success(f"🎉 ¡Venta N° {id_venta} registrada con éxito!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error procesando venta: {e}")
            with c2:
                if st.button("🗑️ Vaciar Carrito", use_container_width=True):
                    st.session_state.carrito = []
                    st.rerun()
        else:
            st.info("El carrito de compras está vacío.")

# ==========================================
# MÓDULO 2: SALA ESTADÍSTICA (ANALYTICS)
# ==========================================
elif opcion == "📈 Sala Estadística (Analytics)":
    st.title("📈 Sala Estadística y Análisis de Negocio")
    st.caption("Métricas clave de rendimiento, ventas e inventario en tiempo real.")

    # Consultas de estadísticas
    df_kpi_v = consultar_db("SELECT COUNT(id_venta) as total_ventas, COALESCE(SUM(total),0) as total_ingresos, COALESCE(AVG(total),0) as ticket_promedio FROM VENTA")
    df_kpi_units = consultar_db("SELECT COALESCE(SUM(cantidad),0) as unidades_vendidas FROM DETALLE_VENTA")
    df_prod_estrella = consultar_db("SELECT p.nombre, SUM(d.cantidad) as total_cant FROM DETALLE_VENTA d JOIN PRODUCTO p ON d.id_producto = p.id_producto GROUP BY p.nombre ORDER BY total_cant DESC LIMIT 1")
    df_agotados = consultar_db("SELECT COUNT(*) as count FROM PRODUCTO WHERE stock = 0")
    
    total_ingresos = df_kpi_v['total_ingresos'].values[0] if not df_kpi_v.empty else 0.0
    total_transacciones = df_kpi_v['total_ventas'].values[0] if not df_kpi_v.empty else 0
    ticket_prom = df_kpi_v['ticket_promedio'].values[0] if not df_kpi_v.empty else 0.0
    total_unidades = df_kpi_units['unidades_vendidas'].values[0] if not df_kpi_units.empty else 0
    prod_top_nombre = df_prod_estrella['nombre'].values[0] if not df_prod_estrella.empty else "N/A"
    cant_agotados = df_agotados['count'].values[0] if not df_agotados.empty else 0

    # Tarjetas KPI superiores
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("💰 Total Ingresos", f"S/ {total_ingresos:,.2f}")
    k2.metric("📦 Unidades Vendidas", f"{total_unidades:,}")
    k3.metric("🎟️ Ticket Promedio", f"S/ {ticket_prom:,.2f}")
    k4.metric("🏆 Producto Estrella", prod_top_nombre)
    k5.metric("🚨 Stock Cero (Agotados)", f"{cant_agotados} ítems", delta_color="inverse")

    st.divider()

    # Gráficos Visuales
    col_g1, col_g2 = st.columns(2)
    
    with col_g1:
        st.subheader("📊 Ventas por Categoría (S/)")
        df_cat_sales = consultar_db("""
            SELECT c.nombre as "Categoría", SUM(d.subtotal) as "Monto (S/)"
            FROM DETALLE_VENTA d
            JOIN PRODUCTO p ON d.id_producto = p.id_producto
            JOIN CATEGORIA c ON p.id_categoria = c.id_categoria
            GROUP BY c.nombre
            ORDER BY "Monto (S/)" DESC
        """)
        if not df_cat_sales.empty:
            st.bar_chart(df_cat_sales.set_index("Categoría"))
        else:
            st.info("Aún no hay datos de ventas registradas.")

    with col_g2:
        st.subheader("📈 Tendencia Histórica de Ventas")
        df_date_sales = consultar_db("""
            SELECT DATE(fecha) as "Fecha", SUM(total) as "Ingresos (S/)"
            FROM VENTA
            GROUP BY DATE(fecha)
            ORDER BY "Fecha" ASC
        """)
        if not df_date_sales.empty:
            st.line_chart(df_date_sales.set_index("Fecha"))
        else:
            st.info("Aún no hay historial de fechas.")

    st.divider()

    # Ranking Completo de Clientes
    st.subheader("👑 Ranking Completo de Clientes")
    df_ranking_clientes = consultar_db("""
        SELECT 
            c.id_cliente as "ID",
            c.nombre as "Nombre Cliente",
            c.documento as "DNI / RUC",
            c.telefono as "Teléfono",
            COUNT(v.id_venta) as "N° Compras",
            COALESCE(SUM(v.total), 0) as "Total Gastado (S/)"
        FROM CLIENTE c
        LEFT JOIN VENTA v ON c.id_cliente = v.id_cliente
        GROUP BY c.id_cliente, c.nombre, c.documento, c.telefono
        ORDER BY "Total Gastado (S/)" DESC
    """)
    if not df_ranking_clientes.empty:
        st.dataframe(df_ranking_clientes, use_container_width=True)
    else:
        st.info("No se han registrado clientes.")

    st.divider()

    # Productos con Stock Crítico o Agotados
    col_p_top, col_p_low = st.columns(2)
    with col_p_top:
        st.subheader("🔥 Top 5 Productos Más Vendidos")
        df_top5 = consultar_db("""
            SELECT p.nombre as "Producto", SUM(d.cantidad) as "Cant. Vendida", SUM(d.subtotal) as "Total (S/)"
            FROM DETALLE_VENTA d
            JOIN PRODUCTO p ON d.id_producto = p.id_producto
            GROUP BY p.nombre
            ORDER BY "Cant. Vendida" DESC
            LIMIT 5
        """)
        st.dataframe(df_top5, use_container_width=True)

    with col_p_low:
        st.subheader("⚠️ Alerta de Inventario Crítico (Stock <= 5)")
        df_low_stock = consultar_db("""
            SELECT p.id_producto as "ID", p.nombre as "Producto", p.stock as "Stock Actual", c.nombre as "Categoría"
            FROM PRODUCTO p
            LEFT JOIN CATEGORIA c ON p.id_categoria = c.id_categoria
            WHERE p.stock <= 5
            ORDER BY p.stock ASC
        """)
        st.dataframe(df_low_stock, use_container_width=True)

# ==========================================
# MÓDULO 3: GESTIÓN DE PRODUCTOS
# ==========================================
elif opcion == "📦 Gestión de Productos":
    st.title("📦 Gestión de Inventario y Productos")
    df_prod = consultar_db("SELECT p.id_producto, p.nombre, p.precio, p.stock, c.nombre as categoria, pr.nombre as proveedor, p.fecha_registro FROM PRODUCTO p LEFT JOIN CATEGORIA c ON p.id_categoria = c.id_categoria LEFT JOIN PROVEEDOR pr ON p.id_proveedor = pr.id_proveedor ORDER BY p.id_producto DESC")
    df_cat = consultar_db("SELECT id_categoria, nombre FROM CATEGORIA")
    df_prov = consultar_db("SELECT id_proveedor, nombre FROM PROVEEDOR")

    st.subheader("Listado de Productos")
    st.dataframe(df_prod, use_container_width=True)

    col_add, col_del = st.columns(2)
    with col_add:
        with st.expander("➕ Registrar Nuevo Producto"):
            with st.form("form_nuevo_prod"):
                nom = st.text_input("Nombre del Producto")
                pre = st.number_input("Precio (S/)", min_value=0.1, value=1.0, step=0.5)
                stk = st.number_input("Stock Inicial", min_value=1, value=10, step=1)
                cat = st.selectbox("Categoría", options=df_cat['id_categoria'].tolist(), format_func=lambda x: df_cat[df_cat['id_categoria']==x]['nombre'].values[0])
                prv = st.selectbox("Proveedor", options=df_prov['id_proveedor'].tolist(), format_func=lambda x: df_prov[df_prov['id_proveedor']==x]['nombre'].values[0])
                
                if st.form_submit_button("Guardar Producto"):
                    if nom:
                        conn = get_connection()
                        cur = conn.cursor()
                        cur.execute("INSERT INTO PRODUCTO (nombre, precio, stock, id_categoria, id_proveedor) VALUES (%s, %s, %s, %s, %s)",
                                    (nom, pre, stk, cat, prv))
                        conn.commit()
                        cur.close()
                        conn.close()
                        registrar_log("PRODUCTO_CREADO", f"Creación de producto: {nom} - Precio S/{pre:.2f} - Stock: {stk}")
                        st.success("Producto registrado exitosamente.")
                        st.rerun()
                    else:
                        st.warning("El nombre del producto es obligatorio.")

    with col_del:
        if es_admin:
            with st.expander("🗑️ Eliminar Producto (Solo Admin)"):
                with st.form("form_elim_prod"):
                    prod_elim = st.selectbox("Seleccionar producto a eliminar:", options=df_prod['id_producto'].tolist(), format_func=lambda x: df_prod[df_prod['id_producto']==x]['nombre'].values[0] if not df_prod.empty else "N/A")
                    pass_confirm = st.text_input("Confirmar con Contraseña de Admin:", type="password")
                    if st.form_submit_button("❌ Eliminar Producto Definitivamente"):
                        if validar_clave_admin(pass_confirm):
                            try:
                                conn = get_connection()
                                cur = conn.cursor()
                                nom_p = df_prod[df_prod['id_producto']==prod_elim]['nombre'].values[0]
                                cur.execute("DELETE FROM PRODUCTO WHERE id_producto = %s", (prod_elim,))
                                conn.commit()
                                cur.close()
                                conn.close()
                                registrar_log("PRODUCTO_ELIMINADO", f"Eliminado producto ID {prod_elim} ({nom_p}) por el Admin.")
                                st.success(f"Producto '{nom_p}' eliminado.")
                                st.rerun()
                            except Exception:
                                st.error("No se puede eliminar un producto que ya tiene ventas asociadas en el historial.")
                        else:
                            st.error("Contraseña de administrador incorrecta.")
        else:
            st.info("🔒 La opción de eliminar productos requiere permisos de Administrador.")

# ==========================================
# MÓDULO 4: CATEGORÍAS Y PROVEEDORES
# ==========================================
elif opcion == "📁 Categorías y Proveedores":
    st.title("📁 Categorías y Proveedores")
    col1, col2 = st.columns(2)
    df_cat = consultar_db("SELECT * FROM CATEGORIA")
    df_prov = consultar_db("SELECT * FROM PROVEEDOR")

    with col1:
        st.subheader("Categorías")
        st.dataframe(df_cat, use_container_width=True)
        with st.form("form_cat"):
            nom_cat = st.text_input("Nombre de Categoría")
            desc_cat = st.text_input("Descripción")
            if st.form_submit_button("Agregar Categoría"):
                if nom_cat:
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute("INSERT INTO CATEGORIA (nombre, descripcion) VALUES (%s, %s)", (nom_cat, desc_cat))
                    conn.commit()
                    cur.close()
                    conn.close()
                    registrar_log("CATEGORIA_CREADA", f"Categoría creada: {nom_cat}")
                    st.success("Categoría agregada.")
                    st.rerun()

        if es_admin and not df_cat.empty:
            with st.expander("🗑️ Eliminar Categoría (Admin)"):
                with st.form("form_del_cat"):
                    cat_elim = st.selectbox("Categoría a eliminar:", options=df_cat['id_categoria'].tolist(), format_func=lambda x: df_cat[df_cat['id_categoria']==x]['nombre'].values[0])
                    pass_admin_cat = st.text_input("Contraseña de Admin:", type="password")
                    if st.form_submit_button("Eliminar Categoría"):
                        if validar_clave_admin(pass_admin_cat):
                            try:
                                conn = get_connection()
                                cur = conn.cursor()
                                nom_c = df_cat[df_cat['id_categoria']==cat_elim]['nombre'].values[0]
                                cur.execute("DELETE FROM CATEGORIA WHERE id_categoria = %s", (cat_elim,))
                                conn.commit()
                                cur.close()
                                conn.close()
                                registrar_log("CATEGORIA_ELIMINADA", f"Eliminada categoría: {nom_c}")
                                st.success("Categoría eliminada.")
                                st.rerun()
                            except Exception:
                                st.error("No se puede eliminar una categoría asignada a productos existentes.")
                        else:
                            st.error("Contraseña de Administrador incorrecta.")

    with col2:
        st.subheader("Proveedores")
        st.dataframe(df_prov, use_container_width=True)
        with st.form("form_prov"):
            nom_prv = st.text_input("Nombre del Proveedor")
            ruc = st.text_input("RUC / DNI")
            tel = st.text_input("Teléfono")
            email = st.text_input("Email")
            if st.form_submit_button("Agregar Proveedor"):
                if nom_prv:
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute("INSERT INTO PROVEEDOR (nombre, ruc_dni, telefono, email) VALUES (%s, %s, %s, %s)", (nom_prv, ruc, tel, email))
                    conn.commit()
                    cur.close()
                    conn.close()
                    registrar_log("PROVEEDOR_CREADO", f"Proveedor creado: {nom_prv}")
                    st.success("Proveedor agregado.")
                    st.rerun()

        if es_admin and not df_prov.empty:
            with st.expander("🗑️ Eliminar Proveedor (Admin)"):
                with st.form("form_del_prov"):
                    prov_elim = st.selectbox("Proveedor a eliminar:", options=df_prov['id_proveedor'].tolist(), format_func=lambda x: df_prov[df_prov['id_proveedor']==x]['nombre'].values[0])
                    pass_admin_prv = st.text_input("Contraseña de Admin:", type="password", key="pass_prv")
                    if st.form_submit_button("Eliminar Proveedor"):
                        if validar_clave_admin(pass_admin_prv):
                            try:
                                conn = get_connection()
                                cur = conn.cursor()
                                nom_pr = df_prov[df_prov['id_proveedor']==prov_elim]['nombre'].values[0]
                                cur.execute("DELETE FROM PROVEEDOR WHERE id_proveedor = %s", (prov_elim,))
                                conn.commit()
                                cur.close()
                                conn.close()
                                registrar_log("PROVEEDOR_ELIMINADO", f"Eliminado proveedor: {nom_pr}")
                                st.success("Proveedor eliminado.")
                                st.rerun()
                            except Exception:
                                st.error("No se puede eliminar un proveedor asignado a productos existentes.")
                        else:
                            st.error("Contraseña de Administrador incorrecta.")

# ==========================================
# MÓDULO 5: CLIENTES Y EMPLEADOS
# ==========================================
elif opcion == "👥 Clientes y Empleados":
    st.title("👥 Clientes y Empleados")
    col1, col2 = st.columns(2)
    df_cli = consultar_db("SELECT id_cliente, nombre, documento, telefono, direccion, fecha_registro FROM CLIENTE ORDER BY id_cliente DESC")
    df_emp = consultar_db("SELECT id_empleado, nombre, cargo, usuario, fecha_registro FROM EMPLEADO ORDER BY id_empleado DESC")

    with col1:
        st.subheader("Clientes")
        st.dataframe(df_cli, use_container_width=True)
        with st.form("form_cli"):
            nom = st.text_input("Nombre Completo")
            doc = st.text_input("DNI / RUC")
            tel = st.text_input("Teléfono")
            dir_cli = st.text_input("Dirección")
            if st.form_submit_button("Registrar Cliente"):
                if nom:
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute("INSERT INTO CLIENTE (nombre, documento, telefono, direccion) VALUES (%s, %s, %s, %s)", (nom, doc, tel, dir_cli))
                    conn.commit()
                    cur.close()
                    conn.close()
                    registrar_log("CLIENTE_CREADO", f"Cliente creado: {nom} ({doc})")
                    st.success("Cliente registrado.")
                    st.rerun()

        if es_admin and not df_cli.empty:
            with st.expander("🗑️ Eliminar Cliente (Admin)"):
                with st.form("form_del_cli"):
                    cli_elim = st.selectbox("Cliente a eliminar:", options=df_cli['id_cliente'].tolist(), format_func=lambda x: df_cli[df_cli['id_cliente']==x]['nombre'].values[0])
                    pass_admin_cli = st.text_input("Contraseña de Admin:", type="password", key="pass_cli")
                    if st.form_submit_button("Eliminar Cliente"):
                        if validar_clave_admin(pass_admin_cli):
                            try:
                                conn = get_connection()
                                cur = conn.cursor()
                                nom_cl = df_cli[df_cli['id_cliente']==cli_elim]['nombre'].values[0]
                                cur.execute("DELETE FROM CLIENTE WHERE id_cliente = %s", (cli_elim,))
                                conn.commit()
                                cur.close()
                                conn.close()
                                registrar_log("CLIENTE_ELIMINADO", f"Eliminado cliente: {nom_cl}")
                                st.success("Cliente eliminado.")
                                st.rerun()
                            except Exception:
                                st.error("No se puede eliminar un cliente con ventas registradas.")
                        else:
                            st.error("Contraseña de Administrador incorrecta.")

    with col2:
        st.subheader("Empleados (Gestión de Usuarios)")
        st.dataframe(df_emp, use_container_width=True)
        
        if es_admin:
            with st.expander("➕ Crear Nuevo Credencial / Empleado (Admin)"):
                with st.form("form_emp"):
                    nom_emp = st.text_input("Nombre del Empleado")
                    cargo = st.selectbox("Asignar Rol / Permisos", ["Cajero", "Almacenero", "Administrador"])
                    user = st.text_input("Usuario")
                    passw = st.text_input("Contraseña", type="password")
                    if st.form_submit_button("Crear Credencial"):
                        if nom_emp and user and passw:
                            try:
                                conn = get_connection()
                                cur = conn.cursor()
                                cur.execute("INSERT INTO EMPLEADO (nombre, cargo, usuario, clave) VALUES (%s, %s, %s, %s)", (nom_emp, cargo, user, passw))
                                conn.commit()
                                cur.close()
                                conn.close()
                                registrar_log("USUARIO_CREADO", f"Creado credencial para {user} con rol: {cargo}")
                                st.success(f"Empleado {user} registrado correctamente con rol {cargo}.")
                                st.rerun()
                            except Exception:
                                st.error("El nombre de usuario ya existe en el sistema.")
                        else:
                            st.warning("Todos los campos son obligatorios.")

            with st.expander("🗑️ Eliminar Usuario / Empleado (Admin)"):
                with st.form("form_del_emp"):
                    emps_disponibles = df_emp[df_emp['id_empleado'] != st.session_state.usuario_actual['id']]
                    if not emps_disponibles.empty:
                        emp_elim = st.selectbox("Seleccionar empleado a dar de baja:", options=emps_disponibles['id_empleado'].tolist(), format_func=lambda x: f"{emps_disponibles[emps_disponibles['id_empleado']==x]['nombre'].values[0]} ({emps_disponibles[emps_disponibles['id_empleado']==x]['usuario'].values[0]})")
                        pass_admin_emp = st.text_input("Contraseña de Admin actual:", type="password", key="pass_emp")
                        if st.form_submit_button("Dar de Baja Empleado"):
                            if validar_clave_admin(pass_admin_emp):
                                try:
                                    conn = get_connection()
                                    cur = conn.cursor()
                                    nom_e = emps_disponibles[emps_disponibles['id_empleado']==emp_elim]['usuario'].values[0]
                                    cur.execute("DELETE FROM EMPLEADO WHERE id_empleado = %s", (emp_elim,))
                                    conn.commit()
                                    cur.close()
                                    conn.close()
                                    registrar_log("USUARIO_ELIMINADO", f"Dado de baja el usuario {nom_e} por el Administrador.")
                                    st.success(f"Usuario {nom_e} eliminado del sistema.")
                                    st.rerun()
                                except Exception:
                                    st.error("No se puede eliminar un empleado que ya figura en registros de ventas u operaciones.")
                            else:
                                st.error("Contraseña de Administrador incorrecta.")
                    else:
                        st.info("No hay otros usuarios disponibles para eliminar.")
        else:
            st.warning("🔒 Solo el Administrador puede crear credenciales o eliminar cuentas de usuario.")

# ==========================================
# MÓDULO 6: HISTÓRICO DE VENTAS
# ==========================================
elif opcion == "📊 Histórico de Ventas":
    st.title("📊 Reporte e Histórico de Ventas")
    df_ventas = consultar_db("SELECT v.id_venta, v.fecha, c.nombre as cliente, e.nombre as empleado, v.total FROM VENTA v LEFT JOIN CLIENTE c ON v.id_cliente = c.id_cliente LEFT JOIN EMPLEADO e ON v.id_empleado = e.id_empleado ORDER BY v.id_venta DESC")
    df_detalles = consultar_db("SELECT d.id_venta, p.nombre as producto, d.cantidad, d.precio_unitario, d.subtotal FROM DETALLE_VENTA d LEFT JOIN PRODUCTO p ON d.id_producto = p.id_producto")

    m1, m2, m3 = st.columns(3)
    m1.metric("Total Ventas (S/)", f"S/ {df_ventas['total'].sum():.2f}" if not df_ventas.empty else "S/ 0.00")
    m2.metric("N° Transacciones", len(df_ventas))
    m3.metric("Ticket Promedio", f"S/ {df_ventas['total'].mean():.2f}" if not df_ventas.empty else "S/ 0.00")

    st.subheader("Registro de Comprobantes")
    if not df_ventas.empty:
        st.dataframe(df_ventas, use_container_width=True)
        st.subheader("🔍 Consultar Detalle de una Venta")
        id_v_sel = st.selectbox("Seleccione ID de Venta:", df_ventas['id_venta'].tolist())
        st.dataframe(df_detalles[df_detalles['id_venta'] == id_v_sel][['producto', 'cantidad', 'precio_unitario', 'subtotal']], use_container_width=True)
    else:
        st.info("Aún no se han realizado ventas.")

# ==========================================
# MÓDULO 7: BITÁCORA DE AUDITORÍA (SOLO ADMIN)
# ==========================================
elif opcion == "📜 Bitácora de Auditoría (.LDF)":
    st.title("📜 Bitácora de Auditoría y Registro de Transacciones (.LDF)")
    st.info("🔒 Registro inalterable de operaciones. Esta sección y sus registros no pueden ser eliminados ni modificados por ningún usuario.")
    
    df_logs = consultar_db("""
        SELECT l.id_log as "ID Log", l.fecha as "Fecha/Hora", l.usuario as "Usuario", e.nombre as "Empleado", e.cargo as "Rol", l.accion as "Acción", l.detalle as "Detalle"
        FROM AUDITORIA_LOG l
        LEFT JOIN EMPLEADO e ON l.id_empleado = e.id_empleado
        ORDER BY l.id_log DESC
    """)

    st.dataframe(df_logs, use_container_width=True)

# ==========================================
# MÓDULO 8: MODELO ENTIDAD-RELACIÓN (MER)
# ==========================================
elif opcion == "📐 Modelo Entidad-Relación (MER)":
    st.title("📐 Diagrama Entidad - Relación (MER)")
    st.markdown("Representación relacional completa de la base de datos **AngelmiMarketDB** incluyendo la tabla de Auditoría.")
    
    graphviz_code = """
    digraph MER {
        rankdir=LR;
        node [shape=rectangle, style=filled, fillcolor="#EBF5FB", color="#1F618D", fontname="Helvetica"];
        edge [color="#2E4053", fontname="Helvetica", fontsize=10];

        CATEGORIA [label="CATEGORIA\\n- id_categoria (PK)\\n- nombre\\n- descripcion"];
        PROVEEDOR [label="PROVEEDOR\\n- id_proveedor (PK)\\n- nombre\\n- ruc_dni\\n- telefono\\n- email"];
        CLIENTE [label="CLIENTE\\n- id_cliente (PK)\\n- nombre\\n- documento\\n- fecha_registro"];
        EMPLEADO [label="EMPLEADO\\n- id_empleado (PK)\\n- nombre\\n- cargo\\n- usuario\\n- clave\\n- fecha_registro"];
        PRODUCTO [label="PRODUCTO\\n- id_producto (PK)\\n- nombre\\n- precio\\n- stock\\n- id_categoria (FK)\\n- id_proveedor (FK)\\n- fecha_registro"];
        VENTA [label="VENTA\\n- id_venta (PK)\\n- fecha\\n- id_cliente (FK)\\n- id_empleado (FK)\\n- total"];
        DETALLE_VENTA [label="DETALLE_VENTA\\n- id_detalle (PK)\\n- id_venta (FK)\\n- id_producto (FK)\\n- cantidad\\n- precio_unitario\\n- subtotal"];
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
