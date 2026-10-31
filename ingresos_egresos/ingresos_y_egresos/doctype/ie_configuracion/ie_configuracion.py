# Copyright (c) 2024, Ernesto Ruiz and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

class IEConfiguracion(Document):
    def validate(self):
        from ingresos_egresos.pos_hooks import validate_configuration
        validate_configuration(self)
        from ingresos_egresos.accounting import validate_configuration as validate_accounting
        validate_accounting(self)
        previous = frappe.db.get_single_value("IE Configuracion", "moneda_base")
        if previous and previous != self.moneda_base and (
            frappe.db.exists("Movimiento", {}) or frappe.db.exists("Registro de Cierre de Movimiento", {}) or frappe.db.exists("IE Turno POS", {})
        ):
            frappe.throw(_("No se puede cambiar la moneda base porque ya existen movimientos o cierres."))
