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
        frappe.db.set_single_value("IE Configuracion", "procesar_diferidos_automaticamente", 0)
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

    def deferred_source(self, kind="Egreso", amount=100, months=3, future=False):
        from frappe.utils import add_months, get_first_day
        start = get_first_day(add_months(nowdate(), 1 if future else -3))
        source = self.source(kind, amount)
        source.update(dict(fecha_de_registro=start, es_diferido=1, inicio_diferimiento=start, meses_diferimiento=months))
        source.save()
        root = "Asset" if kind == "Egreso" else "Liability"
        parent = frappe.db.get_value("Account", dict(company=self.company, root_type=root, is_group=1), "name")
        account = frappe.get_doc(dict(doctype="Account", company=self.company, account_name="IE Diferido " + frappe.generate_hash(length=7),
            parent_account=parent, is_group=0)).insert().name
        return source, account

    def post_deferred(self, source, account):
        options = self.entry(source); options["cuenta_diferida"] = account
        result = accounting.post_movements([options])
        self.assertEqual(result["status"], "posted", result)
        source.reload()
        return frappe.get_doc("IE Diferimiento", source.diferimiento), frappe.get_doc("Journal Entry", source.asiento_contable)

    def test_deferred_expense_initial_posts_balance_not_expense_and_preserves_cash(self):
        source, account = self.deferred_source()
        plan, initial = self.post_deferred(source, account)
        self.assertEqual((initial.accounts[0].credit, initial.accounts[1].account, initial.accounts[1].debit), (100, account, 100))
        self.assertEqual((plan.importe, plan.importe_pendiente, plan.importe_reconocido), (100, 100, 0))
        self.assertEqual([row.importe for row in plan.cuotas], [33.33, 33.33, 33.34])
        self.assertEqual(frappe.db.count("Movimiento", {"sucursal": self.branch}), 1)
        self.assertEqual(frappe.db.count("Sales Invoice", {"remarks": source.name}), 0)

    def test_deferred_income_recognizes_all_due_months_with_native_balanced_journals(self):
        from ingresos_egresos import deferred
        source, account = self.deferred_source("Ingreso")
        plan, initial = self.post_deferred(source, account)
        self.assertEqual((initial.accounts[0].debit, initial.accounts[1].credit, initial.accounts[1].account), (100, 100, account))
        result = deferred.process(plan.name)
        self.assertEqual((result["status"], len(result["asientos"])), ("posted", 3))
        plan.reload()
        self.assertEqual((plan.estado, plan.importe_reconocido, plan.importe_pendiente), ("Completado", 100, 0))
        for name in result["asientos"]:
            journal = frappe.get_doc("Journal Entry", name)
            self.assertEqual((journal.docstatus, journal.total_debit), (1, journal.total_credit))
            self.assertEqual((journal.accounts[0].account, journal.accounts[1].account), (account, self.income))
            self.assertFalse(any(row.account == self.cash for row in journal.accounts))
        self.assertEqual(deferred.process(plan.name)["asientos"], [])
        self.assertEqual(frappe.db.count("Movimiento", {"sucursal": self.branch}), 1)

    def test_deferred_never_posts_future_quota_and_can_pause_resume(self):
        from ingresos_egresos import deferred
        source, account = self.deferred_source(future=True)
        plan, _initial = self.post_deferred(source, account)
        self.assertEqual(deferred.process(plan.name)["asientos"], [])
        self.assertEqual(deferred.set_paused(plan.name, 1), "Pausado")
        self.assertEqual(deferred.process(plan.name)["asientos"], [])
        self.assertEqual(deferred.set_paused(plan.name, 0), "Activo")

    def test_deferred_foreign_cash_is_converted_once_then_recognized_in_company_currency(self):
        from ingresos_egresos import deferred
        self.foreign_cash("USD")
        source, account = self.deferred_source(amount=10)
        source.update(dict(moneda="USD", tasa_de_cambio=80)); source.save()
        plan, initial = self.post_deferred(source, account)
        self.assertEqual((initial.total_debit, plan.importe, source.importe_base), (800, 800, 800))
        self.assertEqual(deferred.process(plan.name)["status"], "posted")
        plan.reload(); self.assertEqual(plan.importe_reconocido, 800)

    def test_deferred_missing_balance_account_returns_modal_requirements_without_posting(self):
        source, _account = self.deferred_source()
        frappe.db.set_value("Company", self.company, "default_deferred_expense_account", None)
        frappe.clear_document_cache("Company", self.company)
        result = accounting.post_movements([self.entry(source)])
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("cuenta_diferida", result["rows"][0]["faltantes"])
        self.assertEqual(frappe.db.count("Journal Entry", {"custom_ie_movimiento": source.name}), 0)

    def test_deferred_uses_native_company_default_account(self):
        source, account = self.deferred_source()
        frappe.db.set_value("Company", self.company, "default_deferred_expense_account", account)
        frappe.clear_document_cache("Company", self.company)
        result = accounting.post_movements([self.entry(source)])
        self.assertEqual(result["status"], "posted", result)
        source.reload(); self.assertEqual(frappe.db.get_value("IE Diferimiento", source.diferimiento, "cuenta_diferida"), account)

    def test_deferred_rejects_wrong_account_and_invalid_periods(self):
        source, _account = self.deferred_source()
        options = self.entry(source); options["cuenta_diferida"] = self.cash
        with self.assertRaises(frappe.ValidationError): accounting.post_movements([options])
        for months in (0, -1, 121):
            source.meses_diferimiento = months
            with self.assertRaises(frappe.ValidationError): source.save()
        source.meses_diferimiento = 3; source.es_activo = 1
        with self.assertRaises(frappe.ValidationError): source.save()

    def test_deferred_recognition_failure_rolls_back_all_due_quota_and_persists_error(self):
        from ingresos_egresos import deferred
        source, account = self.deferred_source()
        plan, _initial = self.post_deferred(source, account)
        frappe.db.set_value("Account", self.expense, "disabled", 1)
        result = deferred.process(plan.name)
        self.assertEqual(result["status"], "error")
        self.assertEqual(frappe.db.count("Journal Entry", {"custom_ie_diferimiento": plan.name}), 0)
        plan.reload(); self.assertTrue(plan.ultimo_error)
        self.assertEqual((plan.importe_reconocido, plan.importe_pendiente), (0, 100))

    def test_deferred_cancellation_pauses_and_requires_reverse_order_before_initial(self):
        from ingresos_egresos import deferred
        source, account = self.deferred_source()
        plan, initial = self.post_deferred(source, account)
        names = deferred.process(plan.name)["asientos"]
        with self.assertRaises(frappe.ValidationError): initial.cancel()
        with self.assertRaises(frappe.ValidationError): frappe.get_doc("Journal Entry", names[0]).cancel()
        for name in reversed(names): frappe.get_doc("Journal Entry", name).cancel()
        plan.reload(); self.assertEqual((plan.estado, plan.importe_pendiente), ("Pausado", 100))
        self.assertEqual(deferred.process(plan.name)["asientos"], [])
        initial.reload(); initial.cancel(); plan.reload(); source.reload()
        self.assertEqual((plan.estado, source.estado_contable), ("Anulado", accounting.CANCELLED))
        with self.assertRaises(frappe.ValidationError): deferred.set_paused(plan.name, 0)
        new, _journal = self.post_deferred(source, account)
        self.assertNotEqual(plan.name, new.name)

    def test_deferred_cancelled_quota_can_be_explicitly_reprocessed_without_losing_old_journal(self):
        from ingresos_egresos import deferred
        source, account = self.deferred_source()
        plan, _initial = self.post_deferred(source, account)
        names = deferred.process(plan.name)["asientos"]
        old = frappe.get_doc("Journal Entry", names[-1]); old.cancel()
        deferred.set_paused(plan.name, 0)
        new = deferred.process(plan.name)["asientos"]
        self.assertEqual(len(new), 1)
        self.assertNotEqual(old.name, new[0]); old.reload(); self.assertEqual(old.docstatus, 2)
        self.assertEqual(frappe.db.count("Journal Entry", {"custom_ie_diferimiento": plan.name, "docstatus": 1}), 3)

    def test_deferred_plan_and_recognition_links_cannot_be_forged_or_removed(self):
        from ingresos_egresos import deferred
        source, account = self.deferred_source()
        plan, _initial = self.post_deferred(source, account)
        plan.meses = 10
        with self.assertRaises((frappe.PermissionError, frappe.ValidationError)): plan.save()
        journal = frappe.get_doc("Journal Entry", deferred.process(plan.name)["asientos"][0])
        journal.custom_ie_diferimiento = None
        with self.assertRaises(frappe.ValidationError): journal.save()
        source.diferimiento = None
        with self.assertRaises(frappe.ValidationError): source.save()

    def test_deferred_automatic_processing_is_opt_in_and_respects_original_permissions(self):
        from ingresos_egresos import deferred
        source, account = self.deferred_source()
        plan, _initial = self.post_deferred(source, account)
        deferred.process_due(); plan.reload(); self.assertEqual(plan.importe_reconocido, 0)
        frappe.db.set_single_value("IE Configuracion", "procesar_diferidos_automaticamente", 1)
        deferred.process_due(); plan.reload(); self.assertEqual(plan.estado, "Completado")
        self.assertEqual(frappe.session.user, "Administrator")

    def test_deferred_guest_cannot_process_or_read_calendar(self):
        from ingresos_egresos import deferred
        source, account = self.deferred_source()
        plan, _initial = self.post_deferred(source, account)
        frappe.set_user("Guest")
        try:
            self.assertFalse(frappe.has_permission("IE Diferimiento", "read", doc=plan))
            with self.assertRaises(frappe.PermissionError): deferred.process(plan.name)
        finally: frappe.set_user("Administrator")

    def test_deferred_recognition_second_failure_rolls_back_first_submitted_quota(self):
        from ingresos_egresos import deferred
        from erpnext.accounts.doctype.journal_entry.journal_entry import JournalEntry
        source, account = self.deferred_source()
        plan, _initial = self.post_deferred(source, account)
        real_submit = JournalEntry.submit
        calls = []
        def fail_second(journal, *args, **kwargs):
            calls.append(journal.name)
            if len(calls) == 2: raise RuntimeError("simulated second quota failure")
            return real_submit(journal, *args, **kwargs)
        with patch.object(JournalEntry, "submit", fail_second):
            result = deferred.process(plan.name)
        self.assertEqual(result["status"], "error")
        self.assertEqual(frappe.db.count("Journal Entry", {"custom_ie_diferimiento": plan.name}), 0)
        plan.reload(); self.assertTrue(all(row.estado == "Pendiente" and not row.asiento_contable for row in plan.cuotas))
        self.assertEqual(deferred.process(plan.name)["status"], "posted")

    def test_deferred_small_amount_plan_failure_rolls_back_initial_cash_journal(self):
        source, account = self.deferred_source(amount=0.01, months=12)
        options = self.entry(source); options["cuenta_diferida"] = account
        with self.assertRaises(frappe.ValidationError): accounting.post_movements([options])
        self.assertEqual(frappe.db.count("Journal Entry", {"custom_ie_movimiento": source.name}), 0)
        self.assertEqual(frappe.db.count("IE Diferimiento", {"movimiento": source.name}), 0)

    def test_deferred_list_and_automatic_job_respect_movement_specific_branch_permissions(self):
        from ingresos_egresos import deferred
        source, account = self.deferred_source()
        first, _initial = self.post_deferred(source, account)
        other = frappe.get_doc(dict(doctype="Branch", branch="IE Otro " + frappe.generate_hash(length=7))).insert().name
        config = frappe.get_single("IE Configuracion")
        config.append("cuentas_caja", dict(sucursal=other, moneda=self.currency, company=self.company, cuenta_caja=self.cash, centro_de_costos=self.cost_center))
        config.save()
        second_source, second_account = self.deferred_source()
        second_source.sucursal = other; second_source.save()
        second, _initial = self.post_deferred(second_source, second_account)
        user = frappe.get_doc(dict(doctype="User", email="ie-diferido-" + frappe.generate_hash(length=7) + "@example.invalid",
            first_name="IE Contabilidad", user_type="System User", send_welcome_email=0,
            roles=[dict(role=r) for r in ("System Manager", "Accounts Manager")])).insert()
        frappe.get_doc(dict(doctype="User Permission", user=user.name, allow="Branch", for_value=self.branch,
            apply_to_all_doctypes=0, applicable_for="Movimiento")).insert()
        frappe.set_user(user.name)
        try:
            self.assertEqual(frappe.get_list("IE Diferimiento", pluck="name"), [first.name])
            self.assertFalse(frappe.has_permission("IE Diferimiento", "read", doc=second))
            with self.assertRaises(frappe.PermissionError): deferred.process(second.name)
        finally: frappe.set_user("Administrator")
        for plan in (first, second): frappe.db.set_value("IE Diferimiento", plan.name, "autorizado_por", user.name)
        frappe.db.set_single_value("IE Configuracion", "procesar_diferidos_automaticamente", 1)
        deferred.process_due(); first.reload(); second.reload()
        self.assertEqual(first.estado, "Completado")
        self.assertEqual(second.importe_reconocido, 0)
        self.assertTrue(second.ultimo_error)

    def test_upgrading_preserves_custom_concepts_and_their_account_defaults(self):
        from frappe.utils.fixtures import sync_fixtures
        from ingresos_egresos.pos_setup import seed_concepts
        doc = frappe.get_doc("IE Codigo", "Egreso")
        doc.code_values[0].cuenta_contable = self.expense
        doc.code_values[0].active = 0
        doc.append("code_values", dict(code_value="Seguro anual QA", cuenta_contable=self.expense, active=1))
        doc.save()
        before = [(row.name, row.code_value, row.active, row.cuenta_contable) for row in doc.code_values]
        sync_fixtures("ingresos_egresos"); seed_concepts(); doc.reload()
        self.assertEqual([(row.name, row.code_value, row.active, row.cuenta_contable) for row in doc.code_values], before)

    def test_existing_independent_journal_cannot_be_attached_to_a_calendar_or_movement(self):
        ordinary = self.post(self.source())
        generic = frappe.copy_doc(ordinary, ignore_no_copy=False)
        generic.docstatus = 0
        generic.posting_date = nowdate()
        generic.custom_ie_movimiento = None
        generic.insert(); generic.submit()
        source, account = self.deferred_source()
        plan, _initial = self.post_deferred(source, account)
        generic.custom_ie_diferimiento = plan.name
        generic.custom_ie_cuota = plan.cuotas[0].name
        with self.assertRaises(frappe.ValidationError): generic.save()
        generic.reload(); generic.custom_ie_movimiento = source.name
        with self.assertRaises(frappe.ValidationError): generic.save()
