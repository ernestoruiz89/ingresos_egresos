from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from ingresos_egresos import currency
from ingresos_egresos.patches.v1_0.add_multicurrency_switch import execute as migrate


class TestCurrencyPolicy(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        frappe.db.set_single_value("IE Configuracion", "moneda_base", "NIO")
        frappe.db.set_single_value("IE Configuracion", "permitir_multimoneda", 0)
        self.company = frappe.db.get_value("Company", {"default_currency": "USD"}, "name")
        if not self.company:
            self.company = frappe.get_doc(dict(doctype="Company", company_name="IE Currency Policy USD",
                abbr="ICPU", default_currency="USD", country="United States",
                create_chart_of_accounts_based_on="Standard Template", chart_of_accounts="Standard")).insert().name
        self.branch = frappe.get_doc(dict(doctype="Branch", branch="IE Moneda " + frappe.generate_hash(length=7))).insert().name
        self.cash = frappe.db.get_value("Account", {"company": self.company, "account_type": "Cash", "is_group": 0}, "name")
        self.mapping(self.company, "USD")

    def mapping(self, company, moneda):
        frappe.get_doc(dict(doctype="IE Cuenta Caja", parent="IE Configuracion", parenttype="IE Configuracion",
            parentfield="cuentas_caja", sucursal=self.branch, company=company, moneda=moneda,
            cuenta_caja=self.cash)).db_insert()

    def movement(self, moneda=None, rate=36.5):
        return frappe.get_doc(dict(doctype="Movimiento", sucursal=self.branch, tipo="Ingreso", clasificacion="Prueba",
            moneda=moneda, importe=10, tasa_de_cambio=rate, fecha_de_registro="2026-01-05")).insert()

    def test_defaults_to_company_currency_and_preserves_distinct_consolidation_base(self):
        doc = self.movement()
        self.assertEqual((doc.moneda, doc.moneda_base, doc.importe_base), ("USD", "NIO", 365))
        settings = currency.get_currency_settings(self.branch)
        self.assertFalse(settings["permitir_multimoneda"])
        self.assertEqual(settings["moneda_empresa"], "USD")

    def test_server_rejects_other_currency_even_if_it_is_the_app_base(self):
        with self.assertRaises(frappe.ValidationError):
            self.movement("NIO", 1)

    def test_enabling_the_switch_keeps_multi_currency_registration_available(self):
        frappe.db.set_single_value("IE Configuracion", "permitir_multimoneda", 1)
        self.assertEqual(self.movement("NIO", 1).moneda, "NIO")

    def test_existing_foreign_records_keep_their_amounts_but_cannot_add_foreign_amounts(self):
        frappe.db.set_single_value("IE Configuracion", "permitir_multimoneda", 1)
        doc = self.movement("NIO", 1)
        frappe.db.set_single_value("IE Configuracion", "permitir_multimoneda", 0)
        doc.descripcion = "Conservar histórico"
        doc.save()
        self.assertEqual((doc.moneda, doc.importe, doc.importe_base), ("NIO", 10, 10))
        doc.importe = 11
        with self.assertRaises(frappe.ValidationError):
            doc.save()

    def test_historical_foreign_movements_can_still_be_closed_without_conversion(self):
        frappe.db.set_single_value("IE Configuracion", "permitir_multimoneda", 1)
        doc = self.movement("NIO", 1)
        frappe.db.set_single_value("IE Configuracion", "permitir_multimoneda", 0)
        closure = frappe.get_doc(dict(doctype="Registro de Cierre de Movimiento", sucursal=self.branch,
            moneda="NIO", fecha_inicio="2026-01-01", fecha_final="2026-01-10")).insert().submit()
        doc.reload()
        self.assertEqual((doc.docstatus, doc.moneda, doc.importe, closure.saldo_final), (1, "NIO", 10, 10))

    def test_ambiguous_branch_company_requires_configuration_instead_of_guessing(self):
        other = frappe.db.get_value("Company", {"name": ["!=", self.company]}, "name")
        self.assertTrue(other)
        self.mapping(other, "NIO")
        with self.assertRaises(frappe.ValidationError):
            self.movement("USD")

    def test_company_fallback_uses_erpnext_default_when_branch_has_no_mapping(self):
        frappe.db.delete("IE Cuenta Caja", {"sucursal": self.branch})
        with patch("frappe.defaults.get_global_default", return_value=self.company):
            self.assertEqual(self.movement().moneda, "USD")

    def test_switch_migration_preserves_explicit_choice_and_is_idempotent(self):
        migrate()
        self.assertFalse(currency.multicurrency_allowed())
        frappe.db.delete("Singles", {"doctype": "IE Configuracion", "field": "permitir_multimoneda"})
        frappe.db.value_cache.clear()
        migrate()
        self.assertTrue(currency.multicurrency_allowed())
        migrate()
        self.assertTrue(currency.multicurrency_allowed())
