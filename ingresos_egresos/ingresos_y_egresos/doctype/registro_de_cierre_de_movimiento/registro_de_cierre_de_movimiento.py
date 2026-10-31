# Copyright (c) 2024, Ernesto Ruiz and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import flt, getdate
from ingresos_egresos.currency import get_balance, get_base_currency


class RegistrodeCierredeMovimiento(Document):
    def autoname(self):
        if self.sucursal:
            branch_abbr, branch_color = frappe.db.get_value(
                "Branch",
                self.sucursal,
                ["custom_abreviatura", "custom_color"],
            ) or ("NA", "#000000")
        else:
            branch_abbr = "NA"
            branch_color = "#000000"

        numeric_part = make_autoname(".####")
        self.name = f"CIERRE-{branch_abbr}-{numeric_part}"
        self.color = branch_color

    def validate(self):
        if self.turno_pos:
            from ingresos_egresos.pos import populate_closure
            populate_closure(self)
            return
        if not self.sucursal or not self.moneda or not self.fecha_inicio or not self.fecha_final:
            frappe.throw(_("Debe definir una sucursal, un rango de fechas y una moneda."))
        self.moneda_base = get_base_currency()
        self.fecha_inicio = getdate(self.fecha_inicio)
        self.fecha_final = getdate(self.fecha_final)

        if self.fecha_inicio > self.fecha_final:
            frappe.throw(_("La fecha inicial debe ser menor o igual a la fecha final."))

        if (self.fecha_inicio.month != self.fecha_final.month) or (
            self.fecha_inicio.year != self.fecha_final.year
        ):
            frappe.throw(
                _(
                    "No se permite un cierre que abarque meses distintos. Este cierre va de {0} a {1}."
                ).format(self.fecha_inicio, self.fecha_final)
            )

        self.validate_date_overlap()
        self.validate_closure_sequence()

        self.populate_entries_and_totals()

    def validate_date_overlap(self):
        overlap = frappe.db.sql(
            """
            SELECT name, fecha_inicio, fecha_final FROM `tabRegistro de Cierre de Movimiento`
            WHERE sucursal = %s
            AND COALESCE(turno_pos, '') = ''
            AND moneda = %s
            AND docstatus = 1
            AND name != %s
            AND (
                (fecha_inicio BETWEEN %s AND %s) OR
                (fecha_final BETWEEN %s AND %s) OR
                (fecha_inicio <= %s AND fecha_final >= %s)
            )
            LIMIT 1
            """,
            (
                self.sucursal,
                self.moneda,
                self.name or "new",
                self.fecha_inicio,
                self.fecha_final,
                self.fecha_inicio,
                self.fecha_final,
                self.fecha_inicio,
                self.fecha_final,
            ),
            as_dict=True,
        )

        if overlap:
            closure = overlap[0]
            frappe.throw(
                _(
                    "El rango de fechas ({0} - {1}) se traslapa con el cierre existente {2} ({3} - {4})."
                ).format(
                    self.fecha_inicio,
                    self.fecha_final,
                    closure.name,
                    closure.fecha_inicio,
                    closure.fecha_final,
                )
            )

    def validate_closure_sequence(self):
        last_closure_date = frappe.db.get_value(
            "Registro de Cierre de Movimiento",
            filters={"sucursal": self.sucursal, "moneda": self.moneda, "docstatus": 1,
                     "turno_pos": ["is", "not set"], "name": ["!=", self.name or "new"]},
            fieldname="fecha_final",
            order_by="fecha_final desc",
        )

        if last_closure_date:
            if self.fecha_inicio <= getdate(last_closure_date):
                frappe.throw(
                    _("El cierre debe ser posterior al último cierre de esta sucursal y moneda ({0}).").format(
                        last_closure_date
                    )
                )

    def populate_entries_and_totals(self):
        if self.turno_pos:
            from ingresos_egresos.pos import populate_closure
            populate_closure(self)
            return
        if self.docstatus == 2:
            return

        existing_rows = {row.registro: row.as_dict() for row in (self.get("ingresos") or []) + (self.get("egresos") or [])}
        self.set("ingresos", [])
        self.set("egresos", [])

        filters = {
            "sucursal": self.sucursal,
            "moneda": self.moneda,
            "turno_pos": ["is", "not set"],
            "docstatus": ["<", 2],
            "fecha_de_registro": ["between", [self.fecha_inicio, self.fecha_final]],
        }

        movements = frappe.get_all(
            "Movimiento",
            filters=filters,
            or_filters={"vinculado": 0, "cierre": self.name or "new"},
            fields=[
                "name",
                "fecha_de_registro",
                "clasificacion",
                "importe",
                "importe_base",
                "moneda",
                "descripcion",
                "tipo",
            ],
        )

        total_income = 0.0
        total_expense = 0.0
        total_income_base = 0.0
        total_expense_base = 0.0

        for movement in movements:
            row = dict(existing_rows.get(movement.name, {}))
            row.update({
                "registro": movement.name,
                "fecha": movement.fecha_de_registro,
                "clasificación": movement.clasificacion,
                "importe": movement.importe,
                "moneda": movement.moneda,
                "moneda_base": self.moneda_base,
                "importe_base": movement.importe_base,
                "descripcion": movement.descripcion,
            })

            if movement.tipo == "Ingreso":
                self.append("ingresos", row)
                total_income += flt(movement.importe)
                total_income_base += flt(movement.importe_base)
            elif movement.tipo == "Egreso":
                self.append("egresos", row)
                total_expense += flt(movement.importe)
                total_expense_base += flt(movement.importe_base)

        self.total_ingresos = total_income
        self.total_egresos = total_expense
        self.total_ingresos_base = total_income_base
        self.total_egresos_base = total_expense_base
        previous, previous_base = get_balance(self.sucursal, self.moneda, self.fecha_inicio)
        self.saldo_final = previous + total_income - total_expense
        self.saldo_final_base = previous_base + total_income_base - total_expense_base

    def get_previous_balance(self, balance_field):
        balances = get_balance(self.sucursal, self.moneda, self.fecha_inicio)
        return balances[1 if balance_field == "saldo_final_base" else 0]

    def before_cancel(self):
        old_turn=frappe.db.get_value(self.doctype,self.name,"turno_pos")
        if self.turno_pos or old_turn:
            if not frappe.flags.ie_pos_internal:
                frappe.throw(_("Utilice la anulación conjunta del turno POS."))
            return
        if frappe.db.exists("Registro de Cierre de Movimiento", {
            "sucursal": self.sucursal, "moneda": self.moneda, "docstatus": 1,
            "turno_pos": ["is", "not set"], "fecha_final": [">", self.fecha_final], "name": ["!=", self.name],
        }):
            frappe.throw(_("Primero debe cancelar los cierres posteriores de esta sucursal y moneda."))

    def before_update_after_submit(self):
        if self.turno_pos or frappe.db.get_value(self.doctype,self.name,"turno_pos"):
            if not frappe.flags.ie_pos_internal:
                frappe.throw(_("Los cierres POS se gestionan desde el turno integrado."))

    def on_trash(self):
        if self.turno_pos:
            frappe.throw(_("Los cierres POS conservan su historial y no pueden eliminarse."))

    def on_submit(self):
        if self.turno_pos:
            from ingresos_egresos.pos import link_closure_movements
            link_closure_movements(self)
            return
        if not self.sucursal or not self.fecha_inicio or not self.fecha_final or not self.moneda:
            frappe.throw(_("Debe definir una sucursal, un rango de fechas y una moneda antes de enviar un cierre."))

        count = frappe.db.count(
            "Movimiento",
            filters={
                "sucursal": self.sucursal,
                "moneda": self.moneda,
                "turno_pos": ["is", "not set"],
                "fecha_de_registro": ["between", [self.fecha_inicio, self.fecha_final]],
                "docstatus": ["<", 2],
                "vinculado": 0,
            },
        )

        if count == 0:
            frappe.msgprint(
                _("No se encontraron movimientos para el rango de fechas seleccionado. Se registró el cierre {0}.").format(
                    self.get_title_auth()
                )
            )
            return

        frappe.db.sql(
            """
            UPDATE `tabMovimiento`
            SET vinculado = 1, cierre = %s, docstatus = 1
            WHERE sucursal = %s
            AND COALESCE(turno_pos, '') = ''
            AND moneda = %s
            AND fecha_de_registro BETWEEN %s AND %s
            AND docstatus < 2
            AND vinculado = 0
            """,
            (self.name, self.sucursal, self.moneda, self.fecha_inicio, self.fecha_final),
        )

        frappe.msgprint(
            _("Se actualizaron {0} movimientos vinculados al cierre {1}.").format(count, self.get_title_auth())
        )

    def get_title_auth(self):
        from frappe.utils import get_link_to_form

        return get_link_to_form(self.doctype, self.name)

    def on_cancel(self):
        self.ignore_linked_doctypes = ["Movimiento"]
        frappe.db.sql(
            """
            UPDATE `tabMovimiento`
            SET vinculado = 0, cierre = NULL, docstatus = 0
            WHERE cierre = %s
            """,
            (self.name,),
        )

        frappe.msgprint(_("Se desvincularon los movimientos del cierre cancelado."))


@frappe.whitelist()
def get_closure_defaults(sucursal, moneda):
    frappe.has_permission("Registro de Cierre de Movimiento", "read", throw=True)
    if not frappe.has_permission("Branch", "read", sucursal):
        frappe.throw(_("No tiene permisos para acceder a la sucursal seleccionada."))
    from frappe.utils import add_days, nowdate

    rows = frappe.get_list("Registro de Cierre de Movimiento",
        filters={"sucursal": sucursal, "moneda": moneda, "docstatus": 1, "turno_pos": ["is", "not set"]},
        fields=["fecha_final"], order_by="fecha_final desc", limit_page_length=1)
    if rows:
        return {"fecha_inicio": add_days(rows[0].fecha_final, 1), "hay_cierre": True}
    rows = frappe.get_list("Movimiento",
        filters={"sucursal": sucursal, "moneda": moneda, "vinculado": 0, "docstatus": ["<", 2], "turno_pos": ["is", "not set"]},
        fields=["fecha_de_registro"], order_by="fecha_de_registro asc", limit_page_length=1)
    return {"fecha_inicio": rows[0].fecha_de_registro if rows else nowdate(), "hay_cierre": False}


@frappe.whitelist()
def get_events(start, end, filters=None):
    from frappe.desk.reportview import get_filters_cond, get_match_cond

    frappe.has_permission("Registro de Cierre de Movimiento","read",throw=True)
    conditions = get_filters_cond("Registro de Cierre de Movimiento", filters, [])
    conditions += get_match_cond("Registro de Cierre de Movimiento")
    conditions = conditions.replace("`tabRegistro de Cierre de Movimiento`.", "rcm.")
    base = get_base_currency()

    data = frappe.db.sql(
        f"""
        SELECT
            rcm.name,
            COALESCE(rcm.fecha_hora_inicio, CONCAT(rcm.fecha_inicio, ' 00:00:00')) AS fecha_inicio,
            COALESCE(rcm.fecha_hora_final, CONCAT(rcm.fecha_final, ' 23:59:59')) AS fecha_final,
            rcm.sucursal,
            rcm.moneda,
            rcm.total_ingresos,
            rcm.total_egresos,
            ROUND(IFNULL(rcm.total_ingresos_base, 0), 2) AS total_ingresos_base,
            ROUND(IFNULL(rcm.total_egresos_base, 0), 2) AS total_egresos_base,
            0 AS allDay,
            rcm.color AS color,
            CONCAT(
                rcm.name, ' | ', rcm.moneda, ' | Ingresos: ', FORMAT(IFNULL(rcm.total_ingresos, 0), 2),
                ' | Egresos: ', FORMAT(IFNULL(rcm.total_egresos, 0), 2),
                ' | Base ', %s, ': ', FORMAT(IFNULL(rcm.total_ingresos_base, 0), 2),
                ' / ', FORMAT(IFNULL(rcm.total_egresos_base, 0), 2)
            ) AS title
        FROM `tabRegistro de Cierre de Movimiento` rcm
        WHERE rcm.docstatus != 2
        AND rcm.fecha_inicio <= %s AND rcm.fecha_final >= %s
        {conditions}
        """,
        (base, end, start), as_dict=True,
    )

    return data
