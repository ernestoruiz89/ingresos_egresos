# Copyright (c) 2024, Ernesto Ruiz and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	chart = get_chart(data, filters)
	return columns, data, None, chart

def get_columns():
	return [
		{
			"label": _("Clasificación"),
			"fieldname": "clasificacion",
			"fieldtype": "Data",
			"width": 180
		},
		{
			"label": _("Estado"),
			"fieldname": "estado",
			"fieldtype": "Data",
			"width": 120
		},
		{
			"label": _("Cantidad"),
			"fieldname": "cantidad",
			"fieldtype": "Int",
			"width": 100
		},
		{
			"label": _("Monto Total"),
			"fieldname": "total",
			"fieldtype": "Currency",
			"width": 140
		},
		{
			"label": _("% del Total"),
			"fieldname": "percentage",
			"fieldtype": "Percentage",
			"width": 100
		}
	]

def get_data(filters):
	condiciones = ""
	if filters.get("sucursal"):
		condiciones += f" AND sucursal = '{filters.get('sucursal')}'"
	
	if filters.get("type"):
		condiciones += f" AND tipo = '{filters.get('type')}'"

	# Obtener datos agrupados por Clasificación y Estado de Vinculación
	data = frappe.db.sql(f"""
		SELECT 
			clasificacion, 
            CASE WHEN vinculado = 1 THEN 'Cerrado' ELSE 'Pendiente' END as estado,
			COUNT(*) as cantidad, 
			SUM(importe) as total
		FROM `tabMovimiento` 
		WHERE docstatus < 2
		AND fecha_de_registro BETWEEN %s AND %s
		{condiciones}
		GROUP BY clasificacion, vinculado
		ORDER BY total DESC
	""", (filters.get("from_date"), filters.get("to_date")), as_dict=1)

	# Traducir estados
	for row in data:
		row["estado"] = _(row["estado"])

	# Calcular %
	total_general = sum([flt(d.total) for d in data])
	for row in data:
		if total_general > 0:
			row["percentage"] = flt((flt(row.total) / total_general) * 100, 1)
		else:
			row["percentage"] = 0

	return data

def get_chart(data, filters):
	labels = [f"{d.get('clasificacion') or _('Sin Clasificación')} ({d.get('estado')})" for d in data]
	values = [d.get("total") for d in data]

	return {
		"data": {
			"labels": labels,
			"datasets": [
				{
					"name": _("Monto por Concepto"),
					"values": values
				}
			]
		},
		"type": "donut", # Donut chart es mejor para participacion
		"height": 300,
		"colors": ["#456789", "#EC8D71", "#333333", "#E09C2C", "#683226"] # Palette example
	}
