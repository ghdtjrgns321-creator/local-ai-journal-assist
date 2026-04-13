"""DuckDB DDL 정의 — 보조 데이터 테이블 26개.

카테고리:
  - Document Flow P2P: purchase_order_headers/lines, goods_receipt_headers/lines,
    vendor_invoice_headers/lines, payment_headers, payment_allocations (8)
  - Document Flow O2C: sales_order_headers/lines, delivery_headers/lines,
    customer_invoice_headers/lines (6)
  - Document References: document_references (1)
  - Master Data: vendors, customers, employees, materials, fixed_assets (5)
  - Labels: anomaly_labels, fraud_red_flags (2)
  - P1 Subledgers: subledger_ap, subledger_ar, ic_matched_pairs, change_log (4)
"""

from __future__ import annotations

import logging

import duckdb

logger = logging.getLogger(__name__)

# ── DDL ──────────────────────────────────────────────────────

SUPPLEMENTARY_DDL: dict[str, str] = {
    # ── Document Flow (P2P) ──────────────────────────────────
    "purchase_order_headers": """
        CREATE TABLE IF NOT EXISTS purchase_order_headers (
            document_id         VARCHAR PRIMARY KEY,
            document_type       VARCHAR,
            company_code        VARCHAR,
            fiscal_year         INTEGER,
            fiscal_period       INTEGER,
            document_date       TIMESTAMP,
            posting_date        TIMESTAMP,
            entry_date          TIMESTAMP,
            status              VARCHAR,
            created_by          VARCHAR,
            changed_by          VARCHAR,
            changed_at          TIMESTAMP,
            currency            VARCHAR,
            reference           VARCHAR,
            header_text         VARCHAR,
            journal_entry_id    VARCHAR,
            upload_batch_id     VARCHAR,
            po_type             VARCHAR,
            vendor_id           VARCHAR,
            vendor_name         VARCHAR,
            purchasing_org      VARCHAR,
            purchasing_group    VARCHAR,
            payment_terms       VARCHAR,
            total_net_amount    DOUBLE,
            total_gross_amount  DOUBLE,
            is_complete         BOOLEAN,
            is_closed           BOOLEAN,
            created_at          TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "purchase_order_lines": """
        CREATE TABLE IF NOT EXISTS purchase_order_lines (
            document_id         VARCHAR NOT NULL,
            line_number         INTEGER NOT NULL,
            material_id         VARCHAR,
            description         VARCHAR,
            quantity            DOUBLE,
            uom                 VARCHAR,
            unit_price          DOUBLE,
            net_amount          DOUBLE,
            tax_amount          DOUBLE,
            gross_amount        DOUBLE,
            gl_account          VARCHAR,
            cost_center         VARCHAR,
            profit_center       VARCHAR,
            item_category       VARCHAR,
            gr_indicator        BOOLEAN,
            ir_indicator        BOOLEAN,
            gr_based_iv         BOOLEAN,
            quantity_received   DOUBLE,
            quantity_invoiced   DOUBLE,
            is_fully_received   BOOLEAN,
            is_fully_invoiced   BOOLEAN,
            plant               VARCHAR,
            storage_location    VARCHAR,
            upload_batch_id     VARCHAR,
            created_at          TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (document_id, line_number)
        )
    """,
    "goods_receipt_headers": """
        CREATE TABLE IF NOT EXISTS goods_receipt_headers (
            document_id         VARCHAR PRIMARY KEY,
            document_type       VARCHAR,
            company_code        VARCHAR,
            fiscal_year         INTEGER,
            fiscal_period       INTEGER,
            document_date       TIMESTAMP,
            posting_date        TIMESTAMP,
            entry_date          TIMESTAMP,
            status              VARCHAR,
            created_by          VARCHAR,
            changed_by          VARCHAR,
            changed_at          TIMESTAMP,
            currency            VARCHAR,
            reference           VARCHAR,
            header_text         VARCHAR,
            journal_entry_id    VARCHAR,
            upload_batch_id     VARCHAR,
            gr_type             VARCHAR,
            purchase_order_id   VARCHAR,
            vendor_id           VARCHAR,
            plant               VARCHAR,
            storage_location    VARCHAR,
            total_quantity      DOUBLE,
            total_value         DOUBLE,
            is_posted           BOOLEAN,
            is_cancelled        BOOLEAN,
            created_at          TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "goods_receipt_lines": """
        CREATE TABLE IF NOT EXISTS goods_receipt_lines (
            document_id         VARCHAR NOT NULL,
            line_number         INTEGER NOT NULL,
            material_id         VARCHAR,
            description         VARCHAR,
            quantity            DOUBLE,
            uom                 VARCHAR,
            unit_price          DOUBLE,
            net_amount          DOUBLE,
            tax_amount          DOUBLE,
            gross_amount        DOUBLE,
            movement_type       VARCHAR,
            po_number           VARCHAR,
            po_item             INTEGER,
            batch               VARCHAR,
            plant               VARCHAR,
            storage_location    VARCHAR,
            stock_type          VARCHAR,
            upload_batch_id     VARCHAR,
            created_at          TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (document_id, line_number)
        )
    """,
    "vendor_invoice_headers": """
        CREATE TABLE IF NOT EXISTS vendor_invoice_headers (
            document_id             VARCHAR PRIMARY KEY,
            document_type           VARCHAR,
            company_code            VARCHAR,
            fiscal_year             INTEGER,
            fiscal_period           INTEGER,
            document_date           TIMESTAMP,
            posting_date            TIMESTAMP,
            entry_date              TIMESTAMP,
            status                  VARCHAR,
            created_by              VARCHAR,
            changed_by              VARCHAR,
            changed_at              TIMESTAMP,
            currency                VARCHAR,
            reference               VARCHAR,
            header_text             VARCHAR,
            journal_entry_id        VARCHAR,
            upload_batch_id         VARCHAR,
            invoice_type            VARCHAR,
            vendor_id               VARCHAR,
            vendor_name             VARCHAR,
            vendor_invoice_number   VARCHAR,
            invoice_date            TIMESTAMP,
            net_amount              DOUBLE,
            tax_amount              DOUBLE,
            gross_amount            DOUBLE,
            withholding_tax_amount  DOUBLE,
            payable_amount          DOUBLE,
            payment_terms           VARCHAR,
            due_date                TIMESTAMP,
            verification_status     VARCHAR,
            payment_block           BOOLEAN,
            purchase_order_id       VARCHAR,
            goods_receipt_id        VARCHAR,
            is_paid                 BOOLEAN,
            amount_paid             DOUBLE,
            balance                 DOUBLE,
            created_at              TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "vendor_invoice_lines": """
        CREATE TABLE IF NOT EXISTS vendor_invoice_lines (
            document_id         VARCHAR NOT NULL,
            line_number         INTEGER NOT NULL,
            material_id         VARCHAR,
            description         VARCHAR,
            quantity            DOUBLE,
            uom                 VARCHAR,
            unit_price          DOUBLE,
            net_amount          DOUBLE,
            tax_amount          DOUBLE,
            gross_amount        DOUBLE,
            gl_account          VARCHAR,
            cost_center         VARCHAR,
            profit_center       VARCHAR,
            po_number           VARCHAR,
            po_item             INTEGER,
            gr_number           VARCHAR,
            gr_item             INTEGER,
            match_status        VARCHAR,
            price_variance      DOUBLE,
            quantity_variance   DOUBLE,
            tax_code            VARCHAR,
            upload_batch_id     VARCHAR,
            created_at          TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (document_id, line_number)
        )
    """,
    "payment_headers": """
        CREATE TABLE IF NOT EXISTS payment_headers (
            document_id         VARCHAR PRIMARY KEY,
            document_type       VARCHAR,
            company_code        VARCHAR,
            fiscal_year         INTEGER,
            fiscal_period       INTEGER,
            document_date       TIMESTAMP,
            posting_date        TIMESTAMP,
            entry_date          TIMESTAMP,
            status              VARCHAR,
            created_by          VARCHAR,
            changed_by          VARCHAR,
            changed_at          TIMESTAMP,
            currency            VARCHAR,
            reference           VARCHAR,
            header_text         VARCHAR,
            journal_entry_id    VARCHAR,
            upload_batch_id     VARCHAR,
            payment_type        VARCHAR,
            business_partner_id VARCHAR,
            is_vendor           BOOLEAN,
            payment_method      VARCHAR,
            payment_status      VARCHAR,
            amount              DOUBLE,
            house_bank          VARCHAR,
            bank_account_id     VARCHAR,
            value_date          TIMESTAMP,
            total_discount      DOUBLE,
            bank_charges        DOUBLE,
            exchange_rate       DOUBLE,
            fx_gain_loss        DOUBLE,
            is_bank_cleared     BOOLEAN,
            is_voided           BOOLEAN,
            created_at          TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "payment_allocations": """
        CREATE TABLE IF NOT EXISTS payment_allocations (
            document_id         VARCHAR NOT NULL,
            invoice_id          VARCHAR,
            invoice_type        VARCHAR,
            amount              DOUBLE,
            discount_taken      DOUBLE,
            withholding_tax     DOUBLE,
            write_off           DOUBLE,
            is_cleared          BOOLEAN,
            upload_batch_id     VARCHAR,
            created_at          TIMESTAMP DEFAULT current_timestamp
        )
    """,
    # ── Document Flow (O2C) ──────────────────────────────────
    "sales_order_headers": """
        CREATE TABLE IF NOT EXISTS sales_order_headers (
            document_id             VARCHAR PRIMARY KEY,
            document_type           VARCHAR,
            company_code            VARCHAR,
            fiscal_year             INTEGER,
            fiscal_period           INTEGER,
            document_date           TIMESTAMP,
            posting_date            TIMESTAMP,
            entry_date              TIMESTAMP,
            status                  VARCHAR,
            created_by              VARCHAR,
            changed_by              VARCHAR,
            changed_at              TIMESTAMP,
            currency                VARCHAR,
            reference               VARCHAR,
            header_text             VARCHAR,
            journal_entry_id        VARCHAR,
            upload_batch_id         VARCHAR,
            so_type                 VARCHAR,
            customer_id             VARCHAR,
            customer_name           VARCHAR,
            sales_org               VARCHAR,
            distribution_channel    VARCHAR,
            division                VARCHAR,
            total_net_amount        DOUBLE,
            total_gross_amount      DOUBLE,
            payment_terms           VARCHAR,
            requested_delivery_date TIMESTAMP,
            is_complete             BOOLEAN,
            credit_status           VARCHAR,
            created_at              TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "sales_order_lines": """
        CREATE TABLE IF NOT EXISTS sales_order_lines (
            document_id         VARCHAR NOT NULL,
            line_number         INTEGER NOT NULL,
            material_id         VARCHAR,
            description         VARCHAR,
            quantity            DOUBLE,
            uom                 VARCHAR,
            unit_price          DOUBLE,
            net_amount          DOUBLE,
            tax_amount          DOUBLE,
            gross_amount        DOUBLE,
            gl_account          VARCHAR,
            cost_center         VARCHAR,
            profit_center       VARCHAR,
            item_category       VARCHAR,
            plant               VARCHAR,
            quantity_delivered   DOUBLE,
            quantity_invoiced   DOUBLE,
            is_fully_delivered  BOOLEAN,
            is_fully_invoiced   BOOLEAN,
            is_rejected         BOOLEAN,
            upload_batch_id     VARCHAR,
            created_at          TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (document_id, line_number)
        )
    """,
    "delivery_headers": """
        CREATE TABLE IF NOT EXISTS delivery_headers (
            document_id         VARCHAR PRIMARY KEY,
            document_type       VARCHAR,
            company_code        VARCHAR,
            fiscal_year         INTEGER,
            fiscal_period       INTEGER,
            document_date       TIMESTAMP,
            posting_date        TIMESTAMP,
            entry_date          TIMESTAMP,
            status              VARCHAR,
            created_by          VARCHAR,
            changed_by          VARCHAR,
            changed_at          TIMESTAMP,
            currency            VARCHAR,
            reference           VARCHAR,
            header_text         VARCHAR,
            journal_entry_id    VARCHAR,
            upload_batch_id     VARCHAR,
            delivery_type       VARCHAR,
            delivery_status     VARCHAR,
            customer_id         VARCHAR,
            sales_order_id      VARCHAR,
            shipping_point      VARCHAR,
            planned_gi_date     TIMESTAMP,
            actual_gi_date      TIMESTAMP,
            total_quantity      DOUBLE,
            total_cogs          DOUBLE,
            is_goods_issued     BOOLEAN,
            is_complete         BOOLEAN,
            is_cancelled        BOOLEAN,
            created_at          TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "delivery_lines": """
        CREATE TABLE IF NOT EXISTS delivery_lines (
            document_id         VARCHAR NOT NULL,
            line_number         INTEGER NOT NULL,
            material_id         VARCHAR,
            description         VARCHAR,
            quantity            DOUBLE,
            uom                 VARCHAR,
            unit_price          DOUBLE,
            net_amount          DOUBLE,
            tax_amount          DOUBLE,
            gross_amount        DOUBLE,
            sales_order_id      VARCHAR,
            so_item             INTEGER,
            quantity_picked     DOUBLE,
            quantity_issued     DOUBLE,
            cogs_amount         DOUBLE,
            plant               VARCHAR,
            storage_location    VARCHAR,
            is_fully_picked     BOOLEAN,
            is_fully_issued     BOOLEAN,
            upload_batch_id     VARCHAR,
            created_at          TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (document_id, line_number)
        )
    """,
    "customer_invoice_headers": """
        CREATE TABLE IF NOT EXISTS customer_invoice_headers (
            document_id             VARCHAR PRIMARY KEY,
            document_type           VARCHAR,
            company_code            VARCHAR,
            fiscal_year             INTEGER,
            fiscal_period           INTEGER,
            document_date           TIMESTAMP,
            posting_date            TIMESTAMP,
            entry_date              TIMESTAMP,
            status                  VARCHAR,
            created_by              VARCHAR,
            changed_by              VARCHAR,
            changed_at              TIMESTAMP,
            currency                VARCHAR,
            reference               VARCHAR,
            header_text             VARCHAR,
            journal_entry_id        VARCHAR,
            upload_batch_id         VARCHAR,
            invoice_type            VARCHAR,
            customer_id             VARCHAR,
            customer_name           VARCHAR,
            sales_org               VARCHAR,
            distribution_channel    VARCHAR,
            division                VARCHAR,
            total_net_amount        DOUBLE,
            total_tax_amount        DOUBLE,
            total_gross_amount      DOUBLE,
            total_cogs              DOUBLE,
            payment_terms           VARCHAR,
            due_date                TIMESTAMP,
            amount_paid             DOUBLE,
            amount_open             DOUBLE,
            payment_status          VARCHAR,
            sales_order_id          VARCHAR,
            delivery_id             VARCHAR,
            is_posted               BOOLEAN,
            is_intercompany         BOOLEAN,
            dunning_level           INTEGER,
            is_cancelled            BOOLEAN,
            created_at              TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "customer_invoice_lines": """
        CREATE TABLE IF NOT EXISTS customer_invoice_lines (
            document_id         VARCHAR NOT NULL,
            line_number         INTEGER NOT NULL,
            material_id         VARCHAR,
            description         VARCHAR,
            quantity            DOUBLE,
            uom                 VARCHAR,
            unit_price          DOUBLE,
            net_amount          DOUBLE,
            tax_amount          DOUBLE,
            gross_amount        DOUBLE,
            gl_account          VARCHAR,
            cost_center         VARCHAR,
            profit_center       VARCHAR,
            revenue_account     VARCHAR,
            cogs_account        VARCHAR,
            cogs_amount         DOUBLE,
            sales_order_id      VARCHAR,
            so_item             INTEGER,
            delivery_id         VARCHAR,
            delivery_item       INTEGER,
            upload_batch_id     VARCHAR,
            created_at          TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (document_id, line_number)
        )
    """,
    # ── Document References ──────────────────────────────────
    "document_references": """
        CREATE TABLE IF NOT EXISTS document_references (
            reference_id        VARCHAR PRIMARY KEY,
            source_doc_type     VARCHAR NOT NULL,
            source_doc_id       VARCHAR NOT NULL,
            target_doc_type     VARCHAR NOT NULL,
            target_doc_id       VARCHAR NOT NULL,
            reference_type      VARCHAR,
            company_code        VARCHAR,
            reference_date      TIMESTAMP,
            description         VARCHAR,
            reference_amount    DOUBLE,
            upload_batch_id     VARCHAR,
            created_at          TIMESTAMP DEFAULT current_timestamp
        )
    """,
    # ── Master Data ──────────────────────────────────────────
    "vendors": """
        CREATE TABLE IF NOT EXISTS vendors (
            vendor_id                   VARCHAR PRIMARY KEY,
            name                        VARCHAR,
            vendor_type                 VARCHAR,
            country                     VARCHAR,
            payment_terms               VARCHAR,
            payment_terms_days          INTEGER,
            is_active                   BOOLEAN,
            account_number              VARCHAR,
            tax_id                      VARCHAR,
            is_intercompany             BOOLEAN,
            intercompany_code           VARCHAR,
            currency                    VARCHAR,
            reconciliation_account      VARCHAR,
            is_one_time                 BOOLEAN,
            withholding_tax_applicable  BOOLEAN,
            withholding_tax_rate        DOUBLE,
            purchasing_org              VARCHAR,
            upload_batch_id             VARCHAR,
            created_at                  TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "customers": """
        CREATE TABLE IF NOT EXISTS customers (
            customer_id             VARCHAR PRIMARY KEY,
            name                    VARCHAR,
            customer_type           VARCHAR,
            country                 VARCHAR,
            credit_rating           VARCHAR,
            credit_limit            DOUBLE,
            credit_exposure         DOUBLE,
            payment_terms           VARCHAR,
            payment_terms_days      INTEGER,
            payment_behavior        VARCHAR,
            is_active               BOOLEAN,
            account_number          VARCHAR,
            tax_id                  VARCHAR,
            is_intercompany         BOOLEAN,
            intercompany_code       VARCHAR,
            currency                VARCHAR,
            reconciliation_account  VARCHAR,
            credit_blocked          BOOLEAN,
            dunning_level           INTEGER,
            sales_org               VARCHAR,
            distribution_channel    VARCHAR,
            upload_batch_id         VARCHAR,
            created_at              TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "employees": """
        CREATE TABLE IF NOT EXISTS employees (
            employee_id             VARCHAR PRIMARY KEY,
            user_id                 VARCHAR,
            display_name            VARCHAR,
            first_name              VARCHAR,
            last_name               VARCHAR,
            email                   VARCHAR,
            persona                 VARCHAR,
            job_level               VARCHAR,
            job_title               VARCHAR,
            department_id           VARCHAR,
            cost_center             VARCHAR,
            manager_id              VARCHAR,
            status                  VARCHAR,
            company_code            VARCHAR,
            approval_limit          DOUBLE,
            can_approve_pr          BOOLEAN,
            can_approve_po          BOOLEAN,
            can_approve_invoice     BOOLEAN,
            can_approve_je          BOOLEAN,
            can_release_payment     BOOLEAN,
            hire_date               TIMESTAMP,
            termination_date        TIMESTAMP,
            is_shared_services      BOOLEAN,
            location                VARCHAR,
            upload_batch_id         VARCHAR,
            created_at              TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "materials": """
        CREATE TABLE IF NOT EXISTS materials (
            material_id         VARCHAR PRIMARY KEY,
            description         VARCHAR,
            material_type       VARCHAR,
            material_group      VARCHAR,
            base_uom            VARCHAR,
            valuation_method    VARCHAR,
            standard_cost       DOUBLE,
            list_price          DOUBLE,
            purchase_price      DOUBLE,
            is_active           BOOLEAN,
            company_code        VARCHAR,
            abc_classification  VARCHAR,
            weight_kg           DOUBLE,
            lead_time_days      INTEGER,
            safety_stock        DOUBLE,
            reorder_point       DOUBLE,
            preferred_vendor_id VARCHAR,
            upload_batch_id     VARCHAR,
            created_at          TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "fixed_assets": """
        CREATE TABLE IF NOT EXISTS fixed_assets (
            asset_id                VARCHAR PRIMARY KEY,
            sub_number              INTEGER,
            description             VARCHAR,
            asset_class             VARCHAR,
            company_code            VARCHAR,
            cost_center             VARCHAR,
            location                VARCHAR,
            acquisition_date        TIMESTAMP,
            acquisition_type        VARCHAR,
            acquisition_cost        DOUBLE,
            depreciation_method     VARCHAR,
            useful_life_months      INTEGER,
            salvage_value           DOUBLE,
            accumulated_depreciation DOUBLE,
            net_book_value          DOUBLE,
            status                  VARCHAR,
            disposal_date           TIMESTAMP,
            disposal_proceeds       DOUBLE,
            serial_number           VARCHAR,
            vendor_id               VARCHAR,
            purchase_order          VARCHAR,
            upload_batch_id         VARCHAR,
            created_at              TIMESTAMP DEFAULT current_timestamp
        )
    """,
    # ── Labels ───────────────────────────────────────────────
    "anomaly_labels": """
        CREATE TABLE IF NOT EXISTS anomaly_labels (
            anomaly_id          VARCHAR PRIMARY KEY,
            anomaly_type        VARCHAR,
            anomaly_category    VARCHAR,
            anomaly_subtype     VARCHAR,
            document_id         VARCHAR,
            document_type       VARCHAR,
            company_code        VARCHAR,
            anomaly_date        TIMESTAMP,
            detection_timestamp TIMESTAMP,
            confidence          DOUBLE,
            severity            INTEGER,
            description         VARCHAR,
            monetary_impact     DOUBLE,
            is_injected         BOOLEAN,
            injection_strategy  VARCHAR,
            cluster_id          VARCHAR,
            upload_batch_id     VARCHAR,
            created_at          TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "fraud_red_flags": """
        CREATE TABLE IF NOT EXISTS fraud_red_flags (
            document_id         VARCHAR NOT NULL,
            pattern_name        VARCHAR NOT NULL,
            category            VARCHAR,
            strength            VARCHAR,
            is_fraudulent       BOOLEAN,
            confidence          DOUBLE,
            details_json        VARCHAR,
            upload_batch_id     VARCHAR,
            created_at          TIMESTAMP DEFAULT current_timestamp
        )
    """,
    # ── P1 Subledgers ────────────────────────────────────────
    "subledger_ap": """
        CREATE TABLE IF NOT EXISTS subledger_ap (
            invoice_number          VARCHAR PRIMARY KEY,
            company_code            VARCHAR,
            vendor_id               VARCHAR,
            vendor_name             VARCHAR,
            vendor_invoice_number   VARCHAR,
            invoice_date            TIMESTAMP,
            posting_date            TIMESTAMP,
            due_date                TIMESTAMP,
            baseline_date           TIMESTAMP,
            invoice_type            VARCHAR,
            status                  VARCHAR,
            net_amount              DOUBLE,
            tax_amount              DOUBLE,
            gross_amount            DOUBLE,
            amount_paid             DOUBLE,
            amount_remaining        DOUBLE,
            payment_terms           VARCHAR,
            match_status            VARCHAR,
            payment_block           BOOLEAN,
            reference_po            VARCHAR,
            reference_gr            VARCHAR,
            gl_reference            VARCHAR,
            created_by              VARCHAR,
            created_at_source       TIMESTAMP,
            upload_batch_id         VARCHAR,
            created_at              TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "subledger_ar": """
        CREATE TABLE IF NOT EXISTS subledger_ar (
            invoice_number          VARCHAR PRIMARY KEY,
            company_code            VARCHAR,
            customer_id             VARCHAR,
            customer_name           VARCHAR,
            invoice_date            TIMESTAMP,
            posting_date            TIMESTAMP,
            due_date                TIMESTAMP,
            baseline_date           TIMESTAMP,
            invoice_type            VARCHAR,
            status                  VARCHAR,
            net_amount              DOUBLE,
            tax_amount              DOUBLE,
            gross_amount            DOUBLE,
            amount_paid             DOUBLE,
            amount_remaining        DOUBLE,
            payment_terms           VARCHAR,
            sales_org               VARCHAR,
            distribution_channel    VARCHAR,
            division                VARCHAR,
            cost_center             VARCHAR,
            profit_center           VARCHAR,
            gl_reference            VARCHAR,
            created_by              VARCHAR,
            created_at_source       TIMESTAMP,
            upload_batch_id         VARCHAR,
            created_at              TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "ic_matched_pairs": """
        CREATE TABLE IF NOT EXISTS ic_matched_pairs (
            ic_reference            VARCHAR PRIMARY KEY,
            transaction_type        VARCHAR,
            seller_company          VARCHAR,
            buyer_company           VARCHAR,
            amount                  DOUBLE,
            currency                VARCHAR,
            transaction_date        TIMESTAMP,
            posting_date            TIMESTAMP,
            seller_document         VARCHAR,
            buyer_document          VARCHAR,
            description             VARCHAR,
            transfer_pricing_policy VARCHAR,
            withholding_tax         DOUBLE,
            settlement_status       VARCHAR,
            settlement_date         TIMESTAMP,
            netting_reference       VARCHAR,
            upload_batch_id         VARCHAR,
            created_at              TIMESTAMP DEFAULT current_timestamp
        )
    """,
    "change_log": """
        CREATE TABLE IF NOT EXISTS change_log (
            document_id         VARCHAR NOT NULL,
            changed_by          VARCHAR,
            change_date         TIMESTAMP,
            changed_field       VARCHAR,
            old_value           VARCHAR,
            new_value           VARCHAR,
            upload_batch_id     VARCHAR,
            created_at          TIMESTAMP DEFAULT current_timestamp
        )
    """,
}

# ── 컬럼 상수 (reindex용, created_at 제외) ──────────────────

PURCHASE_ORDER_HEADERS_COLUMNS: list[str] = [
    "document_id", "document_type", "company_code", "fiscal_year",
    "fiscal_period", "document_date", "posting_date", "entry_date",
    "status", "created_by", "changed_by", "changed_at", "currency",
    "reference", "header_text", "journal_entry_id", "upload_batch_id",
    "po_type", "vendor_id", "vendor_name", "purchasing_org",
    "purchasing_group", "payment_terms", "total_net_amount",
    "total_gross_amount", "is_complete", "is_closed",
]

PURCHASE_ORDER_LINES_COLUMNS: list[str] = [
    "document_id", "line_number", "material_id", "description",
    "quantity", "uom", "unit_price", "net_amount", "tax_amount",
    "gross_amount", "gl_account", "cost_center", "profit_center",
    "item_category", "gr_indicator", "ir_indicator", "gr_based_iv",
    "quantity_received", "quantity_invoiced", "is_fully_received",
    "is_fully_invoiced", "plant", "storage_location", "upload_batch_id",
]

GOODS_RECEIPT_HEADERS_COLUMNS: list[str] = [
    "document_id", "document_type", "company_code", "fiscal_year",
    "fiscal_period", "document_date", "posting_date", "entry_date",
    "status", "created_by", "changed_by", "changed_at", "currency",
    "reference", "header_text", "journal_entry_id", "upload_batch_id",
    "gr_type", "purchase_order_id", "vendor_id", "plant",
    "storage_location", "total_quantity", "total_value",
    "is_posted", "is_cancelled",
]

GOODS_RECEIPT_LINES_COLUMNS: list[str] = [
    "document_id", "line_number", "material_id", "description",
    "quantity", "uom", "unit_price", "net_amount", "tax_amount",
    "gross_amount", "movement_type", "po_number", "po_item",
    "batch", "plant", "storage_location", "stock_type",
    "upload_batch_id",
]

VENDOR_INVOICE_HEADERS_COLUMNS: list[str] = [
    "document_id", "document_type", "company_code", "fiscal_year",
    "fiscal_period", "document_date", "posting_date", "entry_date",
    "status", "created_by", "changed_by", "changed_at", "currency",
    "reference", "header_text", "journal_entry_id", "upload_batch_id",
    "invoice_type", "vendor_id", "vendor_name", "vendor_invoice_number",
    "invoice_date", "net_amount", "tax_amount", "gross_amount",
    "withholding_tax_amount", "payable_amount", "payment_terms",
    "due_date", "verification_status", "payment_block",
    "purchase_order_id", "goods_receipt_id", "is_paid",
    "amount_paid", "balance",
]

VENDOR_INVOICE_LINES_COLUMNS: list[str] = [
    "document_id", "line_number", "material_id", "description",
    "quantity", "uom", "unit_price", "net_amount", "tax_amount",
    "gross_amount", "gl_account", "cost_center", "profit_center",
    "po_number", "po_item", "gr_number", "gr_item", "match_status",
    "price_variance", "quantity_variance", "tax_code",
    "upload_batch_id",
]

PAYMENT_HEADERS_COLUMNS: list[str] = [
    "document_id", "document_type", "company_code", "fiscal_year",
    "fiscal_period", "document_date", "posting_date", "entry_date",
    "status", "created_by", "changed_by", "changed_at", "currency",
    "reference", "header_text", "journal_entry_id", "upload_batch_id",
    "payment_type", "business_partner_id", "is_vendor",
    "payment_method", "payment_status", "amount", "house_bank",
    "bank_account_id", "value_date", "total_discount", "bank_charges",
    "exchange_rate", "fx_gain_loss", "is_bank_cleared", "is_voided",
]

PAYMENT_ALLOCATIONS_COLUMNS: list[str] = [
    "document_id", "invoice_id", "invoice_type", "amount",
    "discount_taken", "withholding_tax", "write_off", "is_cleared",
    "upload_batch_id",
]

SALES_ORDER_HEADERS_COLUMNS: list[str] = [
    "document_id", "document_type", "company_code", "fiscal_year",
    "fiscal_period", "document_date", "posting_date", "entry_date",
    "status", "created_by", "changed_by", "changed_at", "currency",
    "reference", "header_text", "journal_entry_id", "upload_batch_id",
    "so_type", "customer_id", "customer_name", "sales_org",
    "distribution_channel", "division", "total_net_amount",
    "total_gross_amount", "payment_terms", "requested_delivery_date",
    "is_complete", "credit_status",
]

SALES_ORDER_LINES_COLUMNS: list[str] = [
    "document_id", "line_number", "material_id", "description",
    "quantity", "uom", "unit_price", "net_amount", "tax_amount",
    "gross_amount", "gl_account", "cost_center", "profit_center",
    "item_category", "plant", "quantity_delivered", "quantity_invoiced",
    "is_fully_delivered", "is_fully_invoiced", "is_rejected",
    "upload_batch_id",
]

DELIVERY_HEADERS_COLUMNS: list[str] = [
    "document_id", "document_type", "company_code", "fiscal_year",
    "fiscal_period", "document_date", "posting_date", "entry_date",
    "status", "created_by", "changed_by", "changed_at", "currency",
    "reference", "header_text", "journal_entry_id", "upload_batch_id",
    "delivery_type", "delivery_status", "customer_id", "sales_order_id",
    "shipping_point", "planned_gi_date", "actual_gi_date",
    "total_quantity", "total_cogs", "is_goods_issued",
    "is_complete", "is_cancelled",
]

DELIVERY_LINES_COLUMNS: list[str] = [
    "document_id", "line_number", "material_id", "description",
    "quantity", "uom", "unit_price", "net_amount", "tax_amount",
    "gross_amount", "sales_order_id", "so_item", "quantity_picked",
    "quantity_issued", "cogs_amount", "plant", "storage_location",
    "is_fully_picked", "is_fully_issued", "upload_batch_id",
]

CUSTOMER_INVOICE_HEADERS_COLUMNS: list[str] = [
    "document_id", "document_type", "company_code", "fiscal_year",
    "fiscal_period", "document_date", "posting_date", "entry_date",
    "status", "created_by", "changed_by", "changed_at", "currency",
    "reference", "header_text", "journal_entry_id", "upload_batch_id",
    "invoice_type", "customer_id", "customer_name", "sales_org",
    "distribution_channel", "division", "total_net_amount",
    "total_tax_amount", "total_gross_amount", "total_cogs",
    "payment_terms", "due_date", "amount_paid", "amount_open",
    "payment_status", "sales_order_id", "delivery_id", "is_posted",
    "is_intercompany", "dunning_level", "is_cancelled",
]

CUSTOMER_INVOICE_LINES_COLUMNS: list[str] = [
    "document_id", "line_number", "material_id", "description",
    "quantity", "uom", "unit_price", "net_amount", "tax_amount",
    "gross_amount", "gl_account", "cost_center", "profit_center",
    "revenue_account", "cogs_account", "cogs_amount",
    "sales_order_id", "so_item", "delivery_id", "delivery_item",
    "upload_batch_id",
]

DOCUMENT_REFERENCES_COLUMNS: list[str] = [
    "reference_id", "source_doc_type", "source_doc_id",
    "target_doc_type", "target_doc_id", "reference_type",
    "company_code", "reference_date", "description",
    "reference_amount", "upload_batch_id",
]

VENDORS_COLUMNS: list[str] = [
    "vendor_id", "name", "vendor_type", "country", "payment_terms",
    "payment_terms_days", "is_active", "account_number", "tax_id",
    "is_intercompany", "intercompany_code", "currency",
    "reconciliation_account", "is_one_time",
    "withholding_tax_applicable", "withholding_tax_rate",
    "purchasing_org", "upload_batch_id",
]

CUSTOMERS_COLUMNS: list[str] = [
    "customer_id", "name", "customer_type", "country", "credit_rating",
    "credit_limit", "credit_exposure", "payment_terms",
    "payment_terms_days", "payment_behavior", "is_active",
    "account_number", "tax_id", "is_intercompany", "intercompany_code",
    "currency", "reconciliation_account", "credit_blocked",
    "dunning_level", "sales_org", "distribution_channel",
    "upload_batch_id",
]

EMPLOYEES_COLUMNS: list[str] = [
    "employee_id", "user_id", "display_name", "first_name",
    "last_name", "email", "persona", "job_level", "job_title",
    "department_id", "cost_center", "manager_id", "status",
    "company_code", "approval_limit", "can_approve_pr",
    "can_approve_po", "can_approve_invoice", "can_approve_je",
    "can_release_payment", "hire_date", "termination_date",
    "is_shared_services", "location", "upload_batch_id",
]

MATERIALS_COLUMNS: list[str] = [
    "material_id", "description", "material_type", "material_group",
    "base_uom", "valuation_method", "standard_cost", "list_price",
    "purchase_price", "is_active", "company_code",
    "abc_classification", "weight_kg", "lead_time_days",
    "safety_stock", "reorder_point", "preferred_vendor_id",
    "upload_batch_id",
]

FIXED_ASSETS_COLUMNS: list[str] = [
    "asset_id", "sub_number", "description", "asset_class",
    "company_code", "cost_center", "location", "acquisition_date",
    "acquisition_type", "acquisition_cost", "depreciation_method",
    "useful_life_months", "salvage_value", "accumulated_depreciation",
    "net_book_value", "status", "disposal_date", "disposal_proceeds",
    "serial_number", "vendor_id", "purchase_order", "upload_batch_id",
]

ANOMALY_LABELS_COLUMNS: list[str] = [
    "anomaly_id", "anomaly_type", "anomaly_category", "anomaly_subtype",
    "document_id", "document_type", "company_code", "anomaly_date",
    "detection_timestamp", "confidence", "severity", "description",
    "monetary_impact", "is_injected", "injection_strategy",
    "cluster_id", "upload_batch_id",
]

FRAUD_RED_FLAGS_COLUMNS: list[str] = [
    "document_id", "pattern_name", "category", "strength",
    "is_fraudulent", "confidence", "details_json", "upload_batch_id",
]

SUBLEDGER_AP_COLUMNS: list[str] = [
    "invoice_number", "company_code", "vendor_id", "vendor_name",
    "vendor_invoice_number", "invoice_date", "posting_date", "due_date",
    "baseline_date", "invoice_type", "status", "net_amount",
    "tax_amount", "gross_amount", "amount_paid", "amount_remaining",
    "payment_terms", "match_status", "payment_block", "reference_po",
    "reference_gr", "gl_reference", "created_by", "created_at_source",
    "upload_batch_id",
]

SUBLEDGER_AR_COLUMNS: list[str] = [
    "invoice_number", "company_code", "customer_id", "customer_name",
    "invoice_date", "posting_date", "due_date", "baseline_date",
    "invoice_type", "status", "net_amount", "tax_amount",
    "gross_amount", "amount_paid", "amount_remaining", "payment_terms",
    "sales_org", "distribution_channel", "division", "cost_center",
    "profit_center", "gl_reference", "created_by", "created_at_source",
    "upload_batch_id",
]

IC_MATCHED_PAIRS_COLUMNS: list[str] = [
    "ic_reference", "transaction_type", "seller_company",
    "buyer_company", "amount", "currency", "transaction_date",
    "posting_date", "seller_document", "buyer_document", "description",
    "transfer_pricing_policy", "withholding_tax", "settlement_status",
    "settlement_date", "netting_reference", "upload_batch_id",
]

CHANGE_LOG_COLUMNS: list[str] = [
    "document_id", "changed_by", "change_date", "changed_field",
    "old_value", "new_value", "upload_batch_id",
]


# ── 초기화 ───────────────────────────────────────────────────


def initialize_supplementary_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """모든 보조 테이블 DDL 실행. 멱등성 보장."""
    for name, ddl in SUPPLEMENTARY_DDL.items():
        conn.execute(ddl)
    logger.info(
        "DuckDB 보조 스키마 초기화 완료 (%d개 테이블)", len(SUPPLEMENTARY_DDL)
    )
