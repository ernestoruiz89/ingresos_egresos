import frappe
from frappe.utils import flt

def execute():
    frappe.reload_doc("ingresos_y_egresos", "doctype", "registro_de_cierre_de_movimiento")

    # 1. Obtener todas las sucursales
    sucursales = frappe.get_all("Branch", pluck="name")

    for sucursal in sucursales:
        # 2. Inicializar saldo acumulado
        saldo_acumulado = 0.0

        # 3. Obtener todos los cierres ordenados cronológicamente
        cierres = frappe.get_all("Registro de Cierre de Movimiento", 
            filters={"sucursal": sucursal, "docstatus": 1}, 
            order_by="fecha_final asc",
            fields=["name", "fecha_inicio", "fecha_final", "total_ingresos", "total_egresos", "saldo_final"]
        )

        if not cierres:
            continue

        primer_cierre = cierres[0]

        # 4. Calcular saldo inicial histórico (antes del primer cierre)
        # Esto cubre movimientos que ocurrieron antes de que se empezara a usar la funcion de cierre
        movs_anteriores = frappe.db.sql("""
            SELECT SUM(CASE WHEN tipo = 'Ingreso' THEN importe ELSE -importe END)
            FROM `tabMovimiento`
            WHERE sucursal = %s
            AND docstatus = 1
            AND fecha_de_registro < %s
        """, (sucursal, primer_cierre.fecha_inicio))
        
        if movs_anteriores and movs_anteriores[0][0]:
            saldo_acumulado = flt(movs_anteriores[0][0])

        # 5. Iterar cierres y actualizar
        for cierre in cierres:
            # Recalcular totales del cierre si están en 0 (por si acaso)
            t_ing = flt(cierre.total_ingresos)
            t_egr = flt(cierre.total_egresos)

            if t_ing == 0 and t_egr == 0:
                 # Intentar calcular desde movimientos vinculados a este cierre
                 # O desde movimientos en ese rango de fechas
                 totales_calc = frappe.db.sql("""
                    SELECT 
                        SUM(CASE WHEN tipo = 'Ingreso' THEN importe ELSE 0 END),
                        SUM(CASE WHEN tipo = 'Egreso' THEN importe ELSE 0 END)
                    FROM `tabMovimiento`
                    WHERE sucursal = %s
                    AND docstatus = 1
                    AND fecha_de_registro BETWEEN %s AND %s
                 """, (sucursal, cierre.fecha_inicio, cierre.fecha_final))
                 
                 if totales_calc and totales_calc[0]:
                     t_ing = flt(totales_calc[0][0])
                     t_egr = flt(totales_calc[0][1])
                     
                     # Actualizar en DB
                     frappe.db.set_value("Registro de Cierre de Movimiento", cierre.name, {
                         "total_ingresos": t_ing,
                         "total_egresos": t_egr
                     }, update_modified=False)

            # Calcular nuevo saldo final
            nuevo_saldo = saldo_acumulado + t_ing - t_egr
            
            # Actualizar saldo_final en el cierre
            frappe.db.set_value("Registro de Cierre de Movimiento", cierre.name, "saldo_final", nuevo_saldo, update_modified=False)
            
            # El saldo final de este cierre se convierte en el saldo acumulado para el siguiente
            saldo_acumulado = nuevo_saldo
