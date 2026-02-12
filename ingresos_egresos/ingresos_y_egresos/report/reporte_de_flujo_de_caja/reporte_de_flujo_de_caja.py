# Copyright (c) 2024, Ernesto Ruiz and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate, add_days

def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	chart = get_chart(data)
	return columns, data, None, chart

def get_columns():
	return [
		{
			"label": _("Sucursal"),
			"fieldname": "sucursal",
			"fieldtype": "Link",
			"options": "Branch",
			"width": 120
		},
		{
			"label": _("Fecha"),
			"fieldname": "fecha",
			"fieldtype": "Date",
			"width": 120
		},
		{
			"label": _("Estado"),
			"fieldname": "estado",
			"fieldtype": "Data",
			"width": 100
		},
		{
			"label": _("Entradas"),
			"fieldname": "ingresos",
			"fieldtype": "Currency",
			"width": 120
		},
		{
			"label": _("Salidas"),
			"fieldname": "egresos",
			"fieldtype": "Currency",
			"width": 120
		},
		{
			"label": _("Flujo Neto"),
			"fieldname": "neto",
			"fieldtype": "Currency",
			"width": 120
		},
		{
			"label": _("Saldo Acumulado"),
			"fieldname": "saldo_acumulado",
			"fieldtype": "Currency",
			"width": 140
		}
	]

def get_data(filters):
	condiciones = ""
	if filters.get("sucursal"):
		condiciones += f" AND sucursal = '{filters.get('sucursal')}'"
	
	# Obtener movimientos agrupados por sucursal, fecha y estado de vinculación
	movimientos = frappe.db.sql(f"""
		SELECT 
			sucursal,
			fecha_de_registro as fecha,
            CASE WHEN vinculado = 1 THEN 'Cerrado' ELSE 'Pendiente' END as estado,
			SUM(CASE WHEN tipo = 'Ingreso' THEN importe ELSE 0 END) as ingresos,
			SUM(CASE WHEN tipo = 'Egreso' THEN importe ELSE 0 END) as egresos
		FROM `tabMovimiento`
		WHERE docstatus < 2
		AND fecha_de_registro BETWEEN %s AND %s
		{condiciones}
		GROUP BY sucursal, fecha_de_registro, vinculado
		ORDER BY fecha_de_registro ASC, sucursal ASC
	""", (filters.get("from_date"), filters.get("to_date")), as_dict=1)

	# Calcular Saldo Inicial (antes de la fecha 'from_date')
	# Incluimos históricos tanto cerrados como pendientes si están antes del periodo?
    # Generalmente el saldo inicial se basa en lo consolidado, pero si queremos proyectar flujo...
    # Para ser consistentes con el dashboard, incluiremos docstatus < 2
	saldo_inicial = frappe.db.sql(f"""
		SELECT 
			SUM(CASE WHEN tipo = 'Ingreso' THEN importe ELSE -importe END) as saldo
		FROM `tabMovimiento`
		WHERE docstatus < 2
		AND fecha_de_registro < %s
		{condiciones}
	""", (filters.get("from_date")), as_dict=1)[0].saldo or 0.0

	data = []
	saldo_acumulado = flt(saldo_inicial)

	# Si queremos mostrar una fila inicial con saldo anterior (opcional)
	# data.append({
	# 	"fecha": add_days(filters.get("from_date"), -1),
	# 	"ingresos": 0,
	# 	"egresos": 0,
	# 	"neto": 0,
	# 	"saldo_acumulado": saldo_acumulado,
	# 	"is_opening": True
	# })

	for row in movimientos:
		neto = flt(row.ingresos) - flt(row.egresos)
		saldo_acumulado += neto
		
		data.append({
			"sucursal": row.sucursal,
			"fecha": row.fecha,
            "estado": _(row.estado),
			"ingresos": flt(row.ingresos, 2),
			"egresos": flt(row.egresos, 2),
			"neto": flt(neto, 2),
			"saldo_acumulado": flt(saldo_acumulado, 2)
		})

	return data

def get_chart(data):
	labels = [f"{d.get('fecha')} ({d.get('estado')})" for d in data]
	ingresos = [d.get("ingresos") for d in data]
	egresos = [d.get("egresos") for d in data]
	saldo = [d.get("saldo_acumulado") for d in data]

	return {
		"data": {
			"labels": labels,
			"datasets": [
				{
					"name": _("Ingresos"),
					"values": ingresos,
					"chartType": "bar"
				},
				{
					"name": _("Egresos"),
					"values": egresos,
					"chartType": "bar"
				},
				{
					"name": _("Saldo Acumulado"),
					"values": saldo,
					"chartType": "line"
				}
			]
		},
		"type": "axis-mixed", # Permite combinar barras y líneas
		"colors": ["#28a745", "#dc3545", "#007bff"]
	}
