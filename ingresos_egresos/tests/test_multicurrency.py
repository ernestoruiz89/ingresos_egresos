from unittest.mock import patch

import frappe
try:
    from frappe.tests import IntegrationTestCase as FrappeTestCase
except ImportError:  # Frappe v15
    from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from ingresos_egresos.currency import calculate_amounts
from ingresos_egresos.patches.v1_0.complete_multicurrency import execute as migrate
from ingresos_egresos.ingresos_y_egresos.page.dashboard_movimientos.dashboard_movimientos import get_dashboard_data
from ingresos_egresos.ingresos_y_egresos.report.reporte_de_flujo_de_caja.reporte_de_flujo_de_caja import execute as cash_flow
from ingresos_egresos.ingresos_y_egresos.report.reporte_de_movimientos_por_concepto.reporte_de_movimientos_por_concepto import execute as concepts
from ingresos_egresos.ingresos_y_egresos.report.reporte_de_movimientos.reporte_de_movimientos import execute as movements_report
from ingresos_egresos.ingresos_y_egresos.doctype.registro_de_cierre_de_movimiento.registro_de_cierre_de_movimiento import get_closure_defaults, get_events


class TestMulticurrency(FrappeTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        frappe.db.set_single_value("IE Configuracion", "moneda_base", "NIO")
        self.branch = frappe.get_doc({"doctype": "Branch", "branch": "IE Multi " + frappe.generate_hash(length=8)}).insert().name

    def movement(self, currency="NIO", amount=100, rate=None, date="2026-01-05", kind="Ingreso"):
        return frappe.get_doc(dict(doctype="Movimiento", sucursal=self.branch, moneda=currency,
            importe=amount, tasa_de_cambio=rate, fecha_de_registro=date, tipo=kind, clasificacion="Prueba")).insert()

    def closure(self, currency="NIO", start="2026-01-01", end="2026-01-10"):
        return frappe.get_doc(dict(doctype="Registro de Cierre de Movimiento", sucursal=self.branch,
            moneda=currency, fecha_inicio=start, fecha_final=end)).insert().submit()

    def test_base_rate_and_server_recalculation(self):
        doc = self.movement(rate=999)
        self.assertEqual((doc.tasa_de_cambio, doc.importe_base, doc.moneda_base), (1, 100, "NIO"))
        doc.importe_base = 9999
        doc.importe = 25
        doc.save()
        self.assertEqual(doc.importe_base, 25)

    def test_foreign_manual_and_automatic_rates(self):
        doc = self.movement("USD", 10, 36.5)
        self.assertEqual(doc.importe_base, 365)
        doc.tasa_de_cambio = 37
        doc.save()
        self.assertEqual(doc.importe_base, 370)
        with patch("erpnext.setup.utils.get_exchange_rate", return_value=36.6) as lookup:
            auto = self.movement("USD", 10)
            self.assertEqual(auto.importe_base, 366)
            self.assertEqual(getdate(lookup.call_args.args[2]), getdate("2026-01-05"))

    def test_invalid_rates_are_rejected(self):
        for rate in (-1, float("nan"), float("inf")):
            with self.assertRaises(frappe.ValidationError):
                calculate_amounts("USD", rate, 10, "2026-01-05")
        with patch("erpnext.setup.utils.get_exchange_rate", return_value=0):
            with self.assertRaises(frappe.ValidationError):
                self.movement("USD", 10)

    def test_closures_are_independent_by_currency(self):
        nio = self.movement()
        usd = self.movement("USD", 10, 36.5)
        first = self.closure()
        self.assertEqual(first.total_ingresos, 100)
        usd.reload()
        self.assertEqual(usd.docstatus, 0)
        self.movement("USD", 1, 36.5, date="2026-01-06")
        with self.assertRaises(frappe.ValidationError):
            self.movement(date="2026-01-06")
        second = self.closure("USD")
        self.assertEqual(second.total_ingresos, 11)
        self.assertEqual(second.total_ingresos_base, 401.5)
        with self.assertRaises(frappe.ValidationError):
            self.closure("NIO", "2026-01-05", "2026-01-15")
        second.cancel()
        nio.reload()
        self.assertEqual(nio.docstatus, 1)
        usd.reload()
        self.assertEqual(usd.docstatus, 0)

    def test_opening_balance_includes_gaps_and_zero_balances(self):
        self.movement(amount=100)
        self.closure()
        self.movement(amount=100, kind="Egreso", date="2026-01-11")
        self.movement(amount=20, date="2026-01-15")
        doc = self.closure(start="2026-01-15", end="2026-01-20")
        self.assertEqual(doc.saldo_final, 20)
        with self.assertRaises(frappe.ValidationError):
            self.closure(start="2026-01-11", end="2026-01-14")

    def test_cannot_cancel_a_closure_with_later_closures(self):
        self.movement()
        first = self.closure()
        self.closure(start="2026-01-11", end="2026-01-20")
        with self.assertRaises(frappe.ValidationError):
            first.cancel()

    def test_dashboard_original_and_base_totals(self):
        self.movement(amount=50, date="2026-01-01")
        self.movement("USD", 10, 36.5, date="2026-01-01")
        self.movement(amount=20)
        self.movement("USD", 2, 37, kind="Egreso")
        data = get_dashboard_data(self.branch, "2026-01-02", "2026-01-10")
        self.assertEqual(data["totales"]["saldo_anterior"], 415)
        self.assertEqual(data["totales"]["saldo"], 361)
        by_currency = {row["moneda"]: row for row in data["por_moneda"]}
        self.assertEqual(by_currency["NIO"]["saldo"], 70)
        self.assertEqual(by_currency["USD"]["saldo"], 8)
        selected = get_dashboard_data(self.branch, "2026-01-02", "2026-01-10", "USD")
        self.assertEqual(selected["totales"]["saldo"], 291)
        self.assertEqual(len(selected["por_moneda"]), 1)

    def test_reports_keep_currency_and_exclude_cancelled(self):
        self.movement(amount=100)
        usd = self.movement("USD", 10, 36.5)
        cancelled = self.movement(amount=999)
        frappe.db.set_value("Movimiento", cancelled.name, "docstatus", 2)
        filters = dict(sucursal=self.branch, from_date="2026-01-01", to_date="2026-01-31")
        self.assertEqual(cash_flow(filters)[1][-1]["saldo_acumulado"], 465)
        self.assertEqual(sum(row.total for row in concepts(filters)[1]), 465)
        self.assertEqual(cash_flow(dict(filters, moneda="USD"))[1][-1]["saldo_acumulado"], 10)
        self.assertEqual(concepts(dict(filters, moneda="USD"))[1][0].moneda, "USD")
        rows = movements_report(dict(sucursal=self.branch, fecha_inicio="2026-01-01", fecha_final="2026-01-31", moneda="USD"))[1]
        self.assertEqual([row.movimiento for row in rows], [usd.name])
        self.assertEqual(rows[0].moneda_base, "NIO")

    def test_closure_defaults_and_calendar_use_currency(self):
        self.movement()
        self.closure()
        self.movement("USD", 10, 36.5, date="2026-01-03")
        self.assertEqual(getdate(get_closure_defaults(self.branch, "NIO")["fecha_inicio"]), getdate("2026-01-11"))
        self.assertEqual(getdate(get_closure_defaults(self.branch, "USD")["fecha_inicio"]), getdate("2026-01-03"))
        events = get_events("2026-01-01", "2026-01-31", {"sucursal": self.branch})
        self.assertTrue(any("NIO" in event.title for event in events))

    def test_cannot_change_base_currency(self):
        self.movement()
        config = frappe.get_single("IE Configuracion")
        config.moneda_base = "USD"
        with self.assertRaises(frappe.ValidationError):
            config.save()

    def test_migration_preserves_valid_currency_and_is_idempotent(self):
        legacy = self.movement(amount=100)
        usd = self.movement("USD", 10, 36.5)
        doc = self.closure()
        frappe.db.set_value("Movimiento", legacy.name, {"moneda": None, "tasa_de_cambio": 0, "importe_base": 0})
        frappe.db.set_value(doc.doctype, doc.name, {"moneda": None, "saldo_final_base": 0})
        migrate()
        legacy.reload(); usd.reload(); doc.reload()
        self.assertEqual((legacy.moneda, legacy.tasa_de_cambio, legacy.importe_base), ("NIO", 1, 100))
        self.assertEqual((usd.moneda, usd.tasa_de_cambio, usd.importe_base), ("USD", 36.5, 365))
        self.assertEqual((doc.moneda, doc.saldo_final_base, len(doc.ingresos)), ("NIO", 100, 1))
        row_names = [row.name for row in doc.ingresos]
        migrate()
        doc.reload()
        self.assertEqual([row.name for row in doc.ingresos], row_names)
        self.assertEqual((doc.total_ingresos, doc.saldo_final_base, len(doc.ingresos)), (100, 100, 1))

    def test_migration_rejects_mixed_legacy_closure(self):
        nio = self.movement()
        doc = self.closure()
        usd = self.movement("USD", 10, 36.5)
        frappe.db.set_value("Movimiento", usd.name, {"cierre": doc.name, "vinculado": 1})
        with self.assertRaises(frappe.ValidationError):
            migrate()
        nio.reload()
        self.assertEqual(nio.importe_base, 100)

    def test_legacy_missing_rate_is_assumed_base(self):
        legacy = self.movement("USD", 25, 36.5)
        frappe.db.set_value("Movimiento", legacy.name, "tasa_de_cambio", 0)
        migrate()
        legacy.reload()
        self.assertEqual((legacy.moneda, legacy.importe, legacy.importe_base), ("NIO", 25, 25))

    def test_currency_precision_is_applied_on_server(self):
        doc = self.movement("USD", 3, 36.666666667)
        self.assertAlmostEqual(doc.importe_base, 110, places=2)

    def test_closed_snapshots_cannot_be_changed_through_an_earlier_gap(self):
        self.movement()
        self.closure()
        gap = self.movement(date="2026-01-12")
        self.closure(start="2026-01-15", end="2026-01-20")
        with self.assertRaises(frappe.ValidationError):
            self.movement(date="2026-01-13")
        with self.assertRaises(frappe.ValidationError):
            gap.delete()

    def test_print_format_identifies_original_and_base_currency(self):
        self.movement("USD", 10, 36.5)
        doc = self.closure("USD")
        html = frappe.get_print(doc.doctype, doc.name, print_format="Formato Cierre Oficial")
        self.assertIn("USD", html)
        self.assertIn("NIO", html)
        self.assertIn("365", html)
