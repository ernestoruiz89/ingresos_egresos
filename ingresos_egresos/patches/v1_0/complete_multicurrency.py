"""Normalize legacy amounts and rebuild closure snapshots, without resubmitting documents."""
import frappe
from frappe import _
from frappe.utils import flt
from ingresos_egresos.currency import get_base_currency, valid_rate


def execute():
    if not frappe.db.exists("Movimiento", {}) and not frappe.db.exists("Registro de Cierre de Movimiento", {}):
        return
    base = get_base_currency()
    precision = frappe.get_meta("Movimiento").get_field("importe_base").precision
    precision = int(precision or frappe.db.get_single_value("System Settings", "currency_precision") or 2)
    movements = frappe.get_all("Movimiento", fields=["name", "moneda", "tasa_de_cambio", "importe", "importe_base", "cierre", "docstatus", "turno_pos"])
    effective = {}
    linked_currencies = {}
    for row in movements:
        if row.turno_pos:continue
        legacy = not row.moneda or not valid_rate(row.tasa_de_cambio)
        currency = base if legacy else row.moneda
        rate = 1 if currency == base else row.tasa_de_cambio
        effective[row.name] = dict(moneda=currency, tasa_de_cambio=rate, moneda_base=base,
                                  importe_base=flt(flt(row.importe) * flt(rate), precision))
        if row.cierre and row.docstatus < 2:
            linked_currencies.setdefault(row.cierre, set()).add(currency)
    closures = frappe.get_all("Registro de Cierre de Movimiento", filters={"turno_pos":["is","not set"]}, fields=["name", "moneda", "docstatus"], order_by="fecha_final asc")
    closure_currencies = {}
    # Check ambiguous legacy closures before changing any amounts.
    for closure in closures:
        linked = linked_currencies.get(closure.name, set())
        if len(linked) > 1 or (linked and closure.moneda and closure.moneda not in linked):
            frappe.throw(_("El cierre {0} contiene monedas incompatibles. Debe corregirse antes de migrar.").format(closure.name))
        closure_currencies[closure.name] = closure.moneda or next(iter(linked), base)
    for row in movements:
        if row.turno_pos:continue
        frappe.db.set_value("Movimiento", row.name, effective[row.name], update_modified=False)
    for closure in closures:
        doc = frappe.get_doc("Registro de Cierre de Movimiento", closure.name)
        doc.moneda = closure_currencies[closure.name]
        doc.moneda_base = base
        if doc.docstatus != 2:
            doc.populate_entries_and_totals()
            doc.db_update()
            doc.update_children()
        else:
            frappe.db.set_value(doc.doctype, doc.name, {"moneda": doc.moneda, "moneda_base": base}, update_modified=False)
