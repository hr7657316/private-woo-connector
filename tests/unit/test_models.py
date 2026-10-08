from woo_connector.models import OrderSummary, Page, ProductSummary, StockInfo


def test_order_summary_keeps_what_an_agent_needs(sample_order):
    order = OrderSummary.from_wc(sample_order)
    assert order.id == 1042
    assert order.number == "1042"
    assert order.status == "on-hold"
    assert order.total == "1248.00"
    assert order.currency == "INR"
    assert order.date_created == "2026-10-01T04:45:00"  # GMT variant preferred
    assert order.date_paid is None
    assert order.payment_method == "Direct bank transfer"
    assert order.customer.model_dump() == {"id": 7, "name": "Priya Nair", "email": "priya.nair@example.com"}
    assert order.shipping_city == "Kochi"
    assert [li.sku for li in order.line_items] == ["CB-1L", "TOTE-BLU"]
    assert order.line_items[1].variation_id == 23


def test_order_summary_drops_the_bulk(sample_order):
    dumped = OrderSummary.from_wc(sample_order).model_dump()
    assert "meta_data" not in dumped
    assert "_links" not in dumped
    assert all("meta_data" not in li for li in dumped["line_items"])
    assert len(str(dumped)) < len(str(sample_order)) / 2


def test_order_summary_tolerates_guest_and_missing_fields():
    order = OrderSummary.from_wc({"id": 5, "line_items": []})
    assert order.customer.id == 0
    assert order.customer.name == ""
    assert order.number == "5"
    assert order.total == "0"


def test_product_summary(sample_product):
    product = ProductSummary.from_wc(sample_product)
    assert product.sku == "CB-1L"
    assert product.on_sale is True
    assert product.stock_quantity == 3
    assert product.low_stock_amount == 5
    assert product.categories == ["Beverages"]
    assert product.description == "long html"  # HTML stripped


def test_product_description_is_flattened_and_capped(sample_product):
    noisy = {**sample_product, "short_description": "", "description": "<p>Hello&nbsp;<b>world</b></p>\n<ul><li>" + "x" * 400 + "</li></ul>"}
    description = ProductSummary.from_wc(noisy).description
    assert description.startswith("Hello world x")
    assert "<" not in description and len(description) <= 300


def test_stock_info_handles_untracked_stock(sample_product):
    untracked = {**sample_product, "manage_stock": False, "stock_quantity": None, "low_stock_amount": ""}
    stock = StockInfo.from_wc(untracked)
    assert stock.manage_stock is False
    assert stock.stock_quantity is None
    assert stock.low_stock_amount is None
    assert stock.stock_status == "instock"


def test_page_model_is_generic():
    page = Page[int](items=[1, 2], page=1, per_page=2, total=5, total_pages=3, has_more=True)
    assert page.model_dump()["items"] == [1, 2]
