# Ingresos y Egresos (Frappe App)

Una aplicación poderosa y optimizada para el control y gestión de **Ingresos y Egresos** financieros, construida sobre el framework **Frappe/ERPNext v15**. Diseñada para ofrecer una experiencia de usuario fluida con dashboards interactivos y reportes analíticos avanzados.

## 🚀 Características Principales

### 📊 Dashboard Interactivo
- **Vista General**: Visualiza KPIs en tiempo real de Ingresos, Egresos y Saldo actual por sucursal.
- **Acciones Rápidas**: Registra entradas y salidas directamente desde el dashboard.
- **Drag & Drop**: Sube soportes y evidencia (imágenes/PDFs) arrastrándolos directamente al registrar un movimiento.
- **Cierre Rápido**: Realiza el cierre de caja de movimientos pendientes sin salir de la pantalla principal.
- **Seguridad**: Filtro de sucursal inteligente basado en los permisos del usuario.

### 📝 Gestión de Movimientos
- **Validaciones Avanzadas**: 
  - Prevención de registros en periodos cerrados.
  - Verificación cronológica contra el primer cierre.
  - Optimizaciones de base de datos para alto rendimiento.
- **Tipos de Movimiento**: Ingresos y Egresos con clasificación detallada.

### 📈 Reportes Analíticos
- **Reporte de Flujo de Caja**: 
  - Análisis diario de entradas, salidas y flujo neto.
  - Cálculo automático de saldo acumulado con indicadores visuales de estado.
  - Gráficos combinados de barras y líneas.
- **Reporte por Concepto**:
  - Análisis de distribución de gastos/ingresos.
  - Gráfico de dona para visualizar la participación porcentual por categoría.
- **Reporte de Movimientos**: Listado detallado para auditoría.

## 🛠️ Tecnologías

- **Framework**: Frappe / ERPNext (>= v15.0.0)
- **Lenguaje**: Python (Backend), JavaScript (Frontend)
- **Base de Datos**: MariaDB

## 📦 Instalación

1.  Asegúrate de tener **Frappe Bench** instalado.
2.  Obtén la app en tu bench:

```bash
bench get-app https://github.com/ernestoruiz89/ingresos_egresos.git
```

3.  Instala la app en tu sitio:

```bash
bench --site [tu-sitio] install-app ingresos_egresos
```

4.  Reinicia el bench (si es necesario):

```bash
bench restart
```

## 📄 Licencia

MIT