# Copyright (c) 2024, Ernesto Ruiz and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import flt, getdate


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

        if not self.moneda:
            frappe.throw(_("Debe especificar la moneda del cierre."))

        self.populate_entries_and_totals()

    def validate_date_overlap(self):
        overlap = frappe.db.sql(
            """
            SELECT name, fecha_inicio, fecha_final FROM `tabRegistro de Cierre de Movimiento`
            WHERE sucursal = %s
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
        first_closure_date = frappe.db.get_value(
            "Registro de Cierre de Movimiento",
            filters={"sucursal": self.sucursal, "docstatus": 1},
            fieldname="fecha_inicio",
            order_by="fecha_inicio asc",
        )

        if first_closure_date:
            first_closure_date = getdate(first_closure_date)
            if self.fecha_inicio < first_closure_date:
                frappe.throw(
                    _("No se puede realizar un cierre antes del primer cierre registrado ({0}).").format(
                        first_closure_date
                    )
                )

    def populate_entries_and_totals(self):
        if self.docstatus == 2:
            return

        self.set("ingresos", [])
        self.set("egresos", [])

        filters = {
            "sucursal": self.sucursal,
            "moneda": self.moneda,
            "docstatus": ["<", 2],
            "fecha_de_registro": ["between", [self.fecha_inicio, self.fecha_final]],
            "vinculado": 0,
        }

        movements = frappe.get_all(
            "Movimiento",
            filters=filters,
            fields=[
                "name",
                "fecha_de_registro",
                "clasificacion",
                "importe",
                "importe_base",
                "descripcion",
                "tipo",
            ],
        )

        total_income = 0.0
        total_expense = 0.0
        total_income_base = 0.0
        total_expense_base = 0.0

        for movement in movements:
            row = {
                "registro": movement.name,
                "fecha": movement.fecha_de_registro,
                "clasificación": movement.clasificacion,
                "importe": movement.importe,
                "descripcion": movement.descripcion,
            }

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
        self.saldo_final = self.get_previous_balance("saldo_final") + total_income - total_expense
        self.saldo_final_base = self.get_previous_balance("saldo_final_base") + total_income_base - total_expense_base

    def get_previous_balance(self, balance_field):
        previous_balance = frappe.db.get_value(
            "Registro de Cierre de Movimiento",
            filters={
                "sucursal": self.sucursal,
                "moneda": self.moneda,
                "docstatus": 1,
                "fecha_final": ["<", self.fecha_inicio],
            },
            fieldname=balance_field,
            order_by="fecha_final desc",
        )

        if previous_balance is not None:
            return flt(previous_balance)

        movement_field = "importe_base" if balance_field == "saldo_final_base" else "importe"
        historical_balance = frappe.db.sql(
            f"""
            SELECT SUM(CASE WHEN tipo = 'Ingreso' THEN {movement_field} ELSE -{movement_field} END)
            FROM `tabMovimiento`
            WHERE sucursal = %s
            AND moneda = %s
            AND docstatus = 1
            AND fecha_de_registro < %s
            """,
            (self.sucursal, self.moneda, self.fecha_inicio),
        )

        if historical_balance and historical_balance[0][0]:
            return flt(historical_balance[0][0])

        return 0.0

    def on_submit(self):
        if not self.sucursal or not self.fecha_inicio or not self.fecha_final or not self.moneda:
            frappe.throw(_("Debe definir una sucursal, un rango de fechas y una moneda antes de enviar un cierre."))

        count = frappe.db.count(
            "Movimiento",
            filters={
                "sucursal": self.sucursal,
                "moneda": self.moneda,
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
def get_events(start, end, filters=None):
    from frappe.desk.reportview import get_filters_cond

    conditions = get_filters_cond("Registro de Cierre de Movimiento", filters, [])
    conditions = conditions.replace("`tabRegistro de Cierre de Movimiento`.", "rcm.")

    data = frappe.db.sql(
        f"""
        SELECT
            rcm.name,
            CONCAT(rcm.fecha_inicio, ' 00:00:00') AS fecha_inicio,
            CONCAT(rcm.fecha_final, ' 23:59:59') AS fecha_final,
            rcm.sucursal,
            ROUND(IFNULL(rcm.total_ingresos_base, 0), 2) AS total_ingresos_base,
            ROUND(IFNULL(rcm.total_egresos_base, 0), 2) AS total_egresos_base,
            0 AS allDay,
            rcm.color AS color,
            CONCAT(
                rcm.name, ' | Ingresos (Base): ', FORMAT(IFNULL(rcm.total_ingresos_base, 0), 2),
                ' | Egresos (Base): ', FORMAT(IFNULL(rcm.total_egresos_base, 0), 2)
            ) AS title
        FROM `tabRegistro de Cierre de Movimiento` rcm
        WHERE rcm.docstatus != 2
        {conditions}
        """,
        as_dict=True,
    )

    return data
