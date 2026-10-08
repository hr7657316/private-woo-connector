"""Shared fixtures. Payload shapes mirror WooCommerce REST v3 responses (trimmed)."""

from __future__ import annotations

from typing import Any

import pytest

from woo_connector.config import Settings


def make_settings(**overrides: Any) -> Settings:
    base = dict(
        woo_base_url="https://shop.example.com",
        woo_consumer_key="ck_test",
        woo_consumer_secret="cs_test",
        woo_rps=10_000,  # tests never want to wait on the bucket
        woo_burst=1_000,
        woo_max_retries=2,
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def sample_order() -> dict[str, Any]:
    return {
        "id": 1042,
        "number": "1042",
        "status": "on-hold",
        "currency": "INR",
        "date_created": "2026-10-01T10:15:00",
        "date_created_gmt": "2026-10-01T04:45:00",
        "date_paid": None,
        "date_paid_gmt": None,
        "discount_total": "100.00",
        "shipping_total": "49.00",
        "total_tax": "0.00",
        "total": "1248.00",
        "customer_id": 7,
        "customer_note": "Leave at the gate",
        "payment_method": "bacs",
        "payment_method_title": "Direct bank transfer",
        "billing": {
            "first_name": "Priya",
            "last_name": "Nair",
            "email": "priya.nair@example.com",
            "city": "Kochi",
            "postcode": "682001",
        },
        "shipping": {"first_name": "Priya", "last_name": "Nair", "city": "Kochi", "postcode": "682001"},
        "line_items": [
            {
                "id": 1,
                "name": "Cold Brew Coffee 1L",
                "product_id": 11,
                "variation_id": 0,
                "quantity": 2,
                "sku": "CB-1L",
                "total": "1198.00",
                "meta_data": [{"id": 1, "key": "_irrelevant", "value": "x"}],
            },
            {
                "id": 2,
                "name": "Tote Bag - Blue",
                "product_id": 21,
                "variation_id": 23,
                "quantity": 1,
                "sku": "TOTE-BLU",
                "total": "150.00",
            },
        ],
        "meta_data": [{"id": 9, "key": "_big_blob", "value": "x" * 500}],
        "_links": {"self": [{"href": "https://shop.example.com/wp-json/wc/v3/orders/1042"}]},
    }


@pytest.fixture
def sample_product() -> dict[str, Any]:
    return {
        "id": 11,
        "name": "Cold Brew Coffee 1L",
        "slug": "cold-brew-coffee-1l",
        "permalink": "https://shop.example.com/product/cold-brew-coffee-1l/",
        "type": "simple",
        "status": "publish",
        "sku": "CB-1L",
        "price": "599",
        "regular_price": "649",
        "sale_price": "599",
        "on_sale": True,
        "manage_stock": True,
        "stock_quantity": 3,
        "low_stock_amount": 5,
        "stock_status": "instock",
        "backorders": "no",
        "categories": [{"id": 3, "name": "Beverages", "slug": "beverages"}],
        "variations": [],
        "description": "<p>long html</p>",
        "meta_data": [],
    }
