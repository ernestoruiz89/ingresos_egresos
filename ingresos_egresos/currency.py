"""Currency rules shared by movements, closures and reports."""

from math import isfinite

import frappe
from frappe import _
from frappe.utils import flt, getdate


def get_base_currency():
    currency = frappe.db.get_single_value("IE Configuracion", "moneda_base")
    if not currency:
        frappe.throw(_("Debe configurar la moneda base en IE Configuración."))
    return currency


def valid_rate(value):
    try:
        return isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


@frappe.whitelist()
def get_currency_settings():
    frappe.has_permission("Movimiento", "read", throw=True)
    return {"moneda_base": get_base_currency()}


@frappe.whitelist()
def get_rate(moneda, fecha_de_registro):
    frappe.has_permission("Movimiento", "read", throw=True)
    from erpnext.setup.utils import get_exchange_rate

    base = get_base_currency()
    rate = 1 if moneda == base else get_exchange_rate(moneda, base, getdate(fecha_de_registro))
    return {"moneda_base": base, "tasa_de_cambio": flt(rate) if valid_rate(rate) else None}


def calculate_amounts(moneda, rate, amount, date):
    base = get_base_currency()
    moneda = moneda or base
    if moneda == base:
        rate = 1
    elif rate in (None, "", 0, "0"):
        rate = get_rate(moneda, date)["tasa_de_cambio"]
    if not valid_rate(rate):
        frappe.throw(_("Debe indicar una tasa de cambio positiva y válida para {0}.").format(moneda))
    if not isfinite(flt(amount)):
        frappe.throw(_("El importe debe ser un número finito."))
    result = flt(amount) * float(rate)
    if not isfinite(result):
        frappe.throw(_("El importe convertido debe ser un número finito."))
    return moneda, float(rate), result


def get_balance(sucursal, moneda, before_date):
    """Include active drafts, as in dashboard period totals; never add currencies."""
    row = frappe.db.sql(
        """SELECT
            COALESCE(SUM(CASE WHEN tipo = 'Ingreso' THEN importe ELSE -importe END), 0) AS importe,
            COALESCE(SUM(CASE WHEN tipo = 'Ingreso' THEN importe_base ELSE -importe_base END), 0) AS importe_base
        FROM `tabMovimiento`
        WHERE sucursal = %s AND moneda = %s AND docstatus < 2 AND fecha_de_registro < %s
        AND COALESCE(turno_pos, '') = '' """,
        (sucursal, moneda, before_date), as_dict=True,
    )[0]
    return flt(row.importe), flt(row.importe_base)


def report_context(filters, start_key="from_date", end_key="to_date"):
    filters = filters or {}
    if not filters.get(start_key) or not filters.get(end_key):
        frappe.throw(_("Debe seleccionar una fecha inicial y una fecha final."))
    if getdate(filters[start_key]) > getdate(filters[end_key]):
        frappe.throw(_("La fecha inicial debe ser menor o igual a la fecha final."))
    currency = filters.get("moneda") or get_base_currency()
    # Without a currency filter all rows are consolidated using stored base amounts.
    field = "importe" if filters.get("moneda") else "importe_base"
    movement_filters = {"docstatus": ["<", 2], "fecha_de_registro": ["between", [filters[start_key], filters[end_key]]]}
    for key in ("sucursal", "moneda", "turno_pos"):
        if filters.get(key):
            movement_filters[key] = filters[key]
    return currency, field, movement_filters


def aggregate(function, field, alias):
    # Frappe v16 requires structured functions; v15 DatabaseQuery uses SQL fields.
    if int(frappe.__version__.split(".")[0]) >= 16:
        return {function.upper(): field, "as": alias}
    return f"{function}({field}) as {alias}"
