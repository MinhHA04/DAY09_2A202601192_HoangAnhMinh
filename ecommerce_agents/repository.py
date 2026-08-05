"""Read-only, targeted indexes over the Olist CSV files."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Iterator


class DataIntegrityError(RuntimeError):
    """Raised when a requested entity cannot be verified in the source CSVs."""


class OlistRepository:
    """Loads only case-relevant facts while retaining customer-history indexes."""

    FILES = {
        "orders": "olist_orders_dataset.csv",
        "customers": "olist_customers_dataset.csv",
        "items": "olist_order_items_dataset.csv",
        "payments": "olist_order_payments_dataset.csv",
        "products": "olist_products_dataset.csv",
        "sellers": "olist_sellers_dataset.csv",
    }

    def __init__(self, data_dir: Path | str, target_order_ids: Iterable[str]):
        self.data_dir = Path(data_dir)
        self.target_order_ids = set(target_order_ids)
        if not self.target_order_ids:
            raise ValueError("At least one target order_id is required")

        self.orders: dict[str, dict[str, str]] = {}
        self.customers: dict[str, dict[str, str]] = {}
        self.items_by_order: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.payments_by_order: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.products: dict[str, dict[str, str]] = {}
        self.sellers: dict[str, dict[str, str]] = {}
        self._orders_by_customer: dict[str, list[str]] = defaultdict(list)
        self._customer_ids_by_unique: dict[str, list[str]] = defaultdict(list)
        self._load()

    def _rows(self, table: str) -> Iterator[dict[str, str]]:
        path = self.data_dir / self.FILES[table]
        if not path.is_file():
            raise FileNotFoundError(f"Missing Olist table: {path}")
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            yield from csv.DictReader(handle)

    def _load(self) -> None:
        target_customer_ids: set[str] = set()
        for row in self._rows("orders"):
            order_id = row["order_id"]
            customer_id = row["customer_id"]
            self._orders_by_customer[customer_id].append(order_id)
            if order_id in self.target_order_ids:
                self.orders[order_id] = row
                target_customer_ids.add(customer_id)

        missing = sorted(self.target_order_ids - self.orders.keys())
        if missing:
            raise DataIntegrityError(f"Orders not found in CSV: {missing}")

        for row in self._rows("customers"):
            customer_id = row["customer_id"]
            self._customer_ids_by_unique[row["customer_unique_id"]].append(customer_id)
            if customer_id in target_customer_ids:
                self.customers[customer_id] = row

        missing_customers = sorted(target_customer_ids - self.customers.keys())
        if missing_customers:
            raise DataIntegrityError(f"Customers not found in CSV: {missing_customers}")

        product_ids: set[str] = set()
        seller_ids: set[str] = set()
        for row in self._rows("items"):
            if row["order_id"] in self.target_order_ids:
                self.items_by_order[row["order_id"]].append(row)
                product_ids.add(row["product_id"])
                seller_ids.add(row["seller_id"])

        for row in self._rows("payments"):
            if row["order_id"] in self.target_order_ids:
                self.payments_by_order[row["order_id"]].append(row)

        for row in self._rows("products"):
            if row["product_id"] in product_ids:
                self.products[row["product_id"]] = row

        for row in self._rows("sellers"):
            if row["seller_id"] in seller_ids:
                self.sellers[row["seller_id"]] = row

        missing_products = sorted(product_ids - self.products.keys())
        missing_sellers = sorted(seller_ids - self.sellers.keys())
        if missing_products or missing_sellers:
            raise DataIntegrityError(
                f"Unresolved foreign keys: products={missing_products}, sellers={missing_sellers}"
            )

    def order(self, order_id: str) -> dict[str, str]:
        return self.orders[order_id]

    def customer_for_order(self, order_id: str) -> dict[str, str]:
        return self.customers[self.orders[order_id]["customer_id"]]

    def related_order_ids(self, order_id: str) -> list[str]:
        customer = self.customer_for_order(order_id)
        related: list[str] = []
        for customer_id in self._customer_ids_by_unique[customer["customer_unique_id"]]:
            for candidate in self._orders_by_customer.get(customer_id, []):
                if candidate != order_id:
                    related.append(candidate)
        return related

    def order_items(self, order_id: str) -> list[dict[str, str]]:
        return list(self.items_by_order.get(order_id, []))

    def order_payments(self, order_id: str) -> list[dict[str, str]]:
        return list(self.payments_by_order.get(order_id, []))

    def product(self, product_id: str) -> dict[str, str]:
        return self.products[product_id]

    def seller(self, seller_id: str) -> dict[str, str]:
        return self.sellers[seller_id]
