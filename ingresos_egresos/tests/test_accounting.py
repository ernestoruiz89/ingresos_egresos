from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from ingresos_egresos import accounting


class TestMovementAccounting(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        frappe.db.rollback()
        frappe.db.value_cache.clear()
        self.company = "_Test Company"
        self.currency = frappe.db.get_value("Company", self.company, "default_currency")
        frappe.db.set_single_value("IE Configuracion", "moneda_base", self.currency)
        frappe.db.set_single_value("IE Configuracion", "integrar_pos", 0)
        self.branch = frappe.get_doc(dict(doctype="Branch", branch="IE Contab " + frappe.generate_hash(length=7))).insert().name
        self.cash = frappe.db.get_value("Account", dict(company=self.company, account_type="Cash", is_group=0), "name")
        self.income = frappe.db.get_value("Account", dict(company=self.company, root_type="Income", is_group=0), "name")
        self.expense = frappe.db.get_value("Account", dict(company=self.company, root_type="Expense", is_group=0), "name")
        self.receivable = frappe.db.get_value("Account", dict(company=self.company, account_type="Receivable", is_group=0), "name")
        self.cost_center = frappe.db.get_value("Cost Center", dict(company=self.company, is_group=0), "name")
        config = frappe.get_single("IE Configuracion")
        config.set("cuentas_caja", [])
        config.append("cuentas_caja", dict(sucursal=self.branch, moneda=self.currency, company=self.company,
            cuenta_caja=self.cash, centro_de_costos=self.cost_center))
        config.save()

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()
        frappe.db.value_cache.clear()
        frappe.clear_document_cache("Company", self.company)
        super().tearDown()

    def source(self, kind="Ingreso", amount=100, currency=None, rate=1):
        return frappe.get_doc(dict(doctype="Movimiento", sucursal=self.branch, fecha_de_registro=nowdate(), tipo=kind,
            clasificacion="QA contable", moneda=currency or self.currency, tasa_de_cambio=rate, importe=amount)).insert()

    def entry(self, doc, **overrides):
        row = accounting.get_preview([doc.name])[0]
        return dict(name=doc.name, modified=row["modified"], cuenta_contrapartida=self.income if doc.tipo == "Ingreso" else self.expense,
            centro_de_costos=self.cost_center, tasa_empresa=row.get("tasa_empresa"), **overrides)

    def post(self, doc):
        result = accounting.post_movements([self.entry(doc)])
        self.assertEqual(result["status"], "posted", result)
        return frappe.get_doc("Journal Entry", result["results"][0]["asiento_contable"])

    def foreign_cash(self, currency):
        parent = frappe.db.get_value("Account", dict(company=self.company, root_type="Asset", is_group=1), "name")
        name = frappe.get_doc(dict(doctype="Account", company=self.company, account_name="IE Caja " + currency + " " + frappe.generate_hash(length=5),
            parent_account=parent, account_type="Cash", account_currency=currency, is_group=0)).insert().name
        config = frappe.get_single("IE Configuracion")
        config.append("cuentas_caja", dict(sucursal=self.branch, moneda=currency, company=self.company, cuenta_caja=name,
            centro_de_costos=self.cost_center)); config.save()
        return name

    def test_income_posts_cash_debit_income_credit_and_links_both_documents(self):
        doc = self.source(); journal = self.post(doc); doc.reload()
        self.assertEqual(journal.docstatus, 1)
        self.assertEqual(journal.custom_ie_movimiento, doc.name)
        self.assertEqual((doc.asiento_contable, doc.estado_contable, doc.importe_empresa), (journal.name, accounting.POSTED, 100))
        self.assertEqual((journal.accounts[0].debit, journal.accounts[1].credit), (100, 100))
        self.assertEqual(frappe.db.count("GL Entry", {"voucher_no": journal.name, "is_cancelled": 0}), 2)
        self.assertEqual(doc.docstatus, 0)  # Posting does not perform the cashbook closure.

    def test_expense_posts_expense_debit_cash_credit(self):
        journal = self.post(self.source("Egreso", 25))
        self.assertEqual((journal.accounts[0].credit, journal.accounts[1].debit), (25, 25))
        self.assertEqual(journal.accounts[1].account, self.expense)

    def test_repeat_post_is_idempotent_even_with_original_timestamp(self):
        doc = self.source(); entry = self.entry(doc)
        first = accounting.post_movements([entry]); second = accounting.post_movements([entry])
        self.assertEqual(second["results"][0]["resultado"], "Omitido")
        self.assertEqual(first["results"][0]["asiento_contable"], second["results"][0]["asiento_contable"])
        self.assertEqual(frappe.db.count("Journal Entry", {"custom_ie_movimiento": doc.name}), 1)

    def test_foreign_cash_keeps_original_currency_and_saved_rate(self):
        cash = self.foreign_cash("USD")
        doc = self.source(currency="USD", amount=10, rate=80)
        journal = self.post(doc); doc.reload()
        self.assertEqual((journal.accounts[0].account, journal.accounts[0].debit_in_account_currency), (cash, 10))
        self.assertEqual((journal.accounts[0].exchange_rate, journal.total_debit), (80, 800))
        self.assertEqual(doc.importe_base, 800)

    def test_app_and_company_currency_are_converted_independently(self):
        self.foreign_cash("EUR")
        frappe.db.set_single_value("IE Configuracion", "moneda_base", "USD")
        doc = self.source(currency="EUR", amount=10, rate=1.2)
        with patch("erpnext.setup.utils.get_exchange_rate", return_value=90):
            journal = self.post(doc)
        doc.reload()
        self.assertEqual((doc.importe_base, doc.importe_empresa, journal.total_debit), (12, 900, 900))

    def test_missing_exchange_rate_can_be_completed_before_posting(self):
        self.foreign_cash("EUR")
        frappe.db.set_single_value("IE Configuracion", "moneda_base", "USD")
        doc = self.source(currency="EUR", rate=1.2)
        with patch("erpnext.setup.utils.get_exchange_rate", return_value=0):
            entry = self.entry(doc)
            missing = accounting.post_movements([entry])
            self.assertEqual(missing["status"], "needs_input")
            self.assertIn("tasa_empresa", missing["rows"][0]["faltantes"])
            self.assertEqual(frappe.db.count("Journal Entry", {"custom_ie_movimiento": doc.name}), 0)
            entry["tasa_empresa"] = 90
            self.assertEqual(accounting.post_movements([entry])["status"], "posted")

    def test_missing_party_returns_requirements_and_posts_after_completion(self):
        doc = self.source()
        entry = self.entry(doc); entry["cuenta_contrapartida"] = self.receivable
        result = accounting.post_movements([entry])
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("party", result["rows"][0]["faltantes"])
        self.assertEqual(frappe.db.count("Journal Entry", {"custom_ie_movimiento": doc.name}), 0)
        customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
        entry.update(party_type="Customer", party=customer)
        result = accounting.post_movements([entry]); self.assertEqual(result["status"], "posted", result)
        journal = frappe.get_doc("Journal Entry", result["results"][0]["asiento_contable"])
        self.assertEqual((journal.accounts[1].party_type, journal.accounts[1].party), ("Customer", customer))
        doc.reload(); self.assertEqual((doc.party_type, doc.party), ("Customer", customer))

    def test_missing_cost_center_returns_requirements_without_partial_posting(self):
        config = frappe.get_single("IE Configuracion"); config.cuentas_caja[0].centro_de_costos = None; config.save()
        frappe.db.set_value("Company", self.company, "cost_center", None)
        frappe.clear_document_cache("Company", self.company)
        one = self.source(); two = self.source()
        entries = [self.entry(one), self.entry(two)]
        entries[1]["centro_de_costos"] = None
        result = accounting.post_movements(entries)
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("centro_de_costos", result["rows"][1]["faltantes"])
        self.assertEqual(frappe.db.count("Journal Entry", {"custom_ie_movimiento": ["in", [one.name, two.name]]}), 0)
        entries[1]["centro_de_costos"] = self.cost_center
        self.assertEqual(accounting.post_movements(entries)["status"], "posted")

    def test_supplier_payment_requests_party_before_posting(self):
        doc = self.source("Egreso", 75)
        entry = self.entry(doc)
        entry["cuenta_contrapartida"] = frappe.db.get_value("Account", dict(company=self.company, account_type="Payable", is_group=0), "name")
        missing = accounting.post_movements([entry])
        self.assertEqual(missing["status"], "needs_input")
        self.assertIn("party", missing["rows"][0]["faltantes"])
        self.assertEqual(missing["rows"][0]["party_type"], "Supplier")
        self.assertEqual(frappe.db.count("Journal Entry", {"custom_ie_movimiento": doc.name}), 0)
        entry.update(party_type="Supplier", party=frappe.db.get_value("Supplier", {"disabled": 0}, "name"))
        result = accounting.post_movements([entry])
        journal = frappe.get_doc("Journal Entry", result["results"][0]["asiento_contable"])
        self.assertEqual((journal.docstatus, journal.accounts[1].debit, journal.accounts[1].is_advance), (1, 75, "Yes"))

    def test_configured_bank_can_post_without_unavailable_cheque_fields(self):
        bank = frappe.db.get_value("Account", dict(company=self.company, account_type="Bank", is_group=0), "name")
        self.assertTrue(bank)
        config = frappe.get_single("IE Configuracion")
        config.cuentas_caja[0].cuenta_caja = bank
        config.save()
        journal = self.post(self.source())
        self.assertEqual((journal.docstatus, journal.accounts[0].account), (1, bank))
        self.assertFalse(journal.cheque_no)

    def test_bulk_is_one_entry_per_movement_and_skips_existing(self):
        first = self.source(); second = self.source("Egreso", 40)
        self.post(first)
        result = accounting.post_movements([self.entry(first), self.entry(second)])
        self.assertEqual([row["resultado"] for row in result["results"]], ["Omitido", "Contabilizado"])
        self.assertEqual(frappe.db.count("Journal Entry", {"custom_ie_movimiento": ["in", [first.name, second.name]], "docstatus": 1}), 2)

    def test_invalid_counterpart_rolls_back_entire_bulk(self):
        first = self.source(); second = self.source()
        entries = [self.entry(first), self.entry(second)]; entries[1]["cuenta_contrapartida"] = self.expense
        with self.assertRaises(frappe.ValidationError): accounting.post_movements(entries)
        self.assertEqual(frappe.db.count("Journal Entry", {"custom_ie_movimiento": ["in", [first.name, second.name]]}), 0)

    def test_changed_source_requires_new_preview(self):
        doc = self.source(); entry = self.entry(doc)
        doc.importe = 200; doc.save()
        with self.assertRaises(frappe.ValidationError): accounting.post_movements([entry])

    def test_posted_source_cannot_be_changed_detached_or_deleted(self):
        doc = self.source(); self.post(doc); doc.reload()
        doc.importe = 200
        with self.assertRaises(frappe.ValidationError): doc.save()
        doc.reload(); doc.asiento_contable = None
        with self.assertRaises(frappe.ValidationError): doc.save()
        doc.reload()
        with self.assertRaises(frappe.ValidationError): doc.delete()

    def test_cancelling_journal_preserves_history_and_allows_reposting(self):
        doc = self.source(); old = self.post(doc); old.cancel(); doc.reload()
        self.assertEqual((doc.asiento_contable, doc.estado_contable), (old.name, accounting.CANCELLED))
        doc.importe = 150; doc.save()
        new = self.post(doc)
        self.assertNotEqual(old.name, new.name)
        self.assertEqual(frappe.db.count("Journal Entry", {"custom_ie_movimiento": doc.name, "docstatus": 1}), 1)

    def test_pos_invoice_receipts_are_not_posted_twice(self):
        doc = self.source()
        frappe.db.set_value("Movimiento", doc.name, {"origen_pos": "Venta", "estado_contable": accounting.POS})
        result = accounting.post_movements([dict(name=doc.name)])
        self.assertEqual(result["results"][0]["resultado"], "Omitido")
        self.assertEqual(frappe.db.count("Journal Entry", {"custom_ie_movimiento": doc.name}), 0)

    def test_setup_backfills_only_automatic_pos_display_state_idempotently(self):
        from ingresos_egresos.accounting_setup import setup
        manual = self.source()
        automatic = self.source()
        frappe.db.set_value("Movimiento", automatic.name, "origen_pos", "Venta")
        automatic.reload(); before = (automatic.importe, automatic.importe_base, automatic.modified)
        setup(); setup()
        automatic.reload(); manual.reload()
        self.assertEqual(automatic.estado_contable, accounting.POS)
        self.assertEqual((automatic.importe, automatic.importe_base, automatic.modified), before)
        self.assertEqual(manual.estado_contable, "Pendiente")
        self.assertFalse(manual.asiento_contable or automatic.asiento_contable)

    def test_direct_journal_link_and_accounting_status_injection_are_rejected(self):
        doc = self.source(); doc.estado_contable = accounting.POSTED
        with self.assertRaises(frappe.ValidationError): doc.save()
        journal = frappe.get_doc(dict(doctype="Journal Entry", company=self.company, custom_ie_movimiento=doc.name))
        with self.assertRaises(frappe.ValidationError): journal.insert()

    def test_configuration_requires_unique_branch_currency_and_matching_currency(self):
        config = frappe.get_single("IE Configuracion")
        config.append("cuentas_caja", dict(sucursal=self.branch, moneda=self.currency, company=self.company, cuenta_caja=self.cash))
        with self.assertRaises(frappe.ValidationError): config.save()
        config = frappe.get_single("IE Configuracion"); config.cuentas_caja[0].moneda = "USD"
        with self.assertRaises(frappe.ValidationError): config.save()

    def test_guest_cannot_preview_or_post(self):
        doc = self.source(); entry = self.entry(doc); frappe.set_user("Guest")
        try:
            with self.assertRaises(frappe.PermissionError): accounting.get_preview([doc.name])
            with self.assertRaises(frappe.PermissionError): accounting.post_movements([entry])
        finally: frappe.set_user("Administrator")

    def asset_source(self, cwip=True, depreciable=True, amount=1200):
        def account(kind, root):
            existing = frappe.db.get_value("Account", dict(company=self.company, account_type=kind, is_group=0), "name")
            if existing: return existing
            parent = frappe.db.get_value("Account", dict(company=self.company, root_type=root, is_group=1), "name")
            return frappe.get_doc(dict(doctype="Account", company=self.company, parent_account=parent,
                account_name="IE " + kind + " " + frappe.generate_hash(length=5), account_type=kind, is_group=0)).insert().name
        fixed = account("Fixed Asset", "Asset")
        accumulated = account("Accumulated Depreciation", "Asset")
        depreciation = account("Depreciation", "Expense")
        category = frappe.get_doc(dict(doctype="Asset Category", asset_category_name="IE Activos " + frappe.generate_hash(length=6),
            enable_cwip_accounting=cwip, non_depreciable_category=not depreciable,
            accounts=[dict(company_name=self.company, fixed_asset_account=fixed, accumulated_depreciation_account=accumulated,
                depreciation_expense_account=depreciation, capital_work_in_progress_account=account("Capital Work in Progress", "Asset"))])).insert()
        item = frappe.get_doc(dict(doctype="Item", item_code="IE Equipo " + frappe.generate_hash(length=6),
            item_group="All Item Groups", stock_uom="Nos", is_fixed_asset=1, is_stock_item=0,
            is_sales_item=0, asset_category=category.name)).insert()
        location = frappe.get_doc(dict(doctype="Location", location_name="IE Local " + frappe.generate_hash(length=6))).insert()
        doc = frappe.get_doc(dict(doctype="Movimiento", sucursal=self.branch, fecha_de_registro=nowdate(), tipo="Egreso",
            clasificacion="Equipo de tienda", moneda=self.currency, tasa_de_cambio=1, importe=amount,
            es_activo=1, item_activo=item.name, ubicacion_activo=location.name, fecha_uso_activo=nowdate(),
            vida_util_meses=12, valor_residual=0)).insert()
        return doc, fixed, accumulated, depreciation

    def post_asset(self, doc):
        row = accounting.get_preview([doc.name])[0]
        result = accounting.post_movements([dict(name=doc.name, modified=row["modified"],
            cuenta_contrapartida=row["cuenta_contrapartida"], centro_de_costos=self.cost_center, tasa_empresa=row["tasa_empresa"])])
        self.assertEqual(result["status"], "posted", result)
        doc.reload()
        return frappe.get_doc("Asset", doc.activo_fijo), frappe.get_doc("Journal Entry", doc.asiento_contable)

    def test_fixed_asset_acquisition_uses_category_not_expense_and_native_schedule(self):
        doc, fixed, _acc, _expense = self.asset_source()
        asset, journal = self.post_asset(doc)
        self.assertEqual((asset.docstatus, asset.net_purchase_amount, journal.accounts[1].account), (1, 1200, fixed))
        self.assertEqual(asset.asset_type or "", "")  # A new purchase, never a fictitious opening asset.
        self.assertEqual(asset.custom_ie_asiento_contable, journal.name)
        self.assertEqual(frappe.db.count("GL Entry", {"voucher_type": "Asset", "voucher_no": asset.name}), 0)
        schedule = frappe.get_doc("Asset Depreciation Schedule", {"asset": asset.name, "status": "Active"})
        # ERPNext prorates the first/last calendar month for a mid-month acquisition.
        self.assertIn(len(schedule.depreciation_schedule), (12, 13))
        self.assertAlmostEqual(sum(row.depreciation_amount for row in schedule.depreciation_schedule), 1200, places=2)

    def test_first_native_depreciation_posts_category_expense_and_accumulated_account(self):
        from erpnext.assets.doctype.asset.depreciation import make_depreciation_entry
        doc, _fixed, accumulated, expense = self.asset_source()
        asset, journal = self.post_asset(doc)
        schedule = frappe.get_doc("Asset Depreciation Schedule", {"asset": asset.name, "status": "Active"})
        result = make_depreciation_entry(schedule.name, date=schedule.depreciation_schedule[0].schedule_date)
        depreciation = frappe.get_doc("Journal Entry", result.depreciation_schedule[0].journal_entry)
        by_account = {row.account: row for row in depreciation.accounts}
        expected = schedule.depreciation_schedule[0].depreciation_amount
        self.assertGreater(expected, 0)
        self.assertLessEqual(expected, 100)
        self.assertEqual((by_account[expense].debit, by_account[accumulated].credit), (expected, expected))
        with self.assertRaises(frappe.ValidationError): journal.cancel()

    def test_asset_acquisition_can_be_cancelled_before_depreciation_and_reposted(self):
        doc, _fixed, _acc, _expense = self.asset_source()
        asset, journal = self.post_asset(doc)
        journal.cancel(); doc.reload(); asset.reload()
        self.assertEqual((doc.estado_contable, asset.docstatus), (accounting.CANCELLED, 2))
        new_asset, new_journal = self.post_asset(doc)
        self.assertNotEqual(new_asset.name, asset.name)
        self.assertNotEqual(new_journal.name, journal.name)

    def test_correcting_cancelled_acquisition_to_expense_keeps_old_asset_history(self):
        doc, _fixed, _acc, _expense = self.asset_source()
        asset, journal = self.post_asset(doc)
        journal.cancel(); doc.reload()
        doc.es_activo = 0; doc.save()
        expense_journal = self.post(doc); doc.reload(); asset.reload()
        self.assertFalse(doc.activo_fijo)
        self.assertEqual(expense_journal.accounts[1].account, self.expense)
        self.assertEqual((asset.docstatus, asset.custom_ie_movimiento, asset.custom_ie_asiento_contable), (2, doc.name, journal.name))

    def test_asset_cannot_be_redirected_to_an_expense_account(self):
        doc, _fixed, _acc, _expense = self.asset_source()
        entry = self.entry(doc)
        with self.assertRaises(frappe.ValidationError): accounting.post_movements([entry])
        self.assertEqual(frappe.db.count("Journal Entry", {"custom_ie_movimiento": doc.name}), 0)

    def test_non_depreciable_category_creates_asset_without_schedule(self):
        doc, _fixed, _acc, _expense = self.asset_source(cwip=False, depreciable=False)
        asset, _journal = self.post_asset(doc)
        self.assertFalse(asset.calculate_depreciation)
        self.assertFalse(frappe.db.exists("Asset Depreciation Schedule", {"asset": asset.name}))

    def test_fixed_asset_flag_is_only_for_manual_expenses(self):
        doc = self.source()
        doc.es_activo = 1
        with self.assertRaises(frappe.ValidationError): doc.save()

    def test_failure_creating_asset_rolls_back_submitted_journal_and_entire_batch(self):
        ordinary = self.source()
        asset, _fixed, _acc, _expense = self.asset_source()
        row = accounting.get_preview([asset.name])[0]
        entries = [self.entry(ordinary), dict(name=asset.name, modified=row["modified"],
            cuenta_contrapartida=row["cuenta_contrapartida"], centro_de_costos=self.cost_center, tasa_empresa=row["tasa_empresa"])]
        with patch("ingresos_egresos.asset_integration.create_asset", side_effect=RuntimeError("simulated asset failure")):
            with self.assertRaises(RuntimeError): accounting.post_movements(entries)
        self.assertEqual(frappe.db.count("Journal Entry", {"custom_ie_movimiento": ["in", [ordinary.name, asset.name]]}), 0)
        ordinary.reload(); asset.reload()
        self.assertFalse(ordinary.asiento_contable or asset.asiento_contable)
