BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;


CREATE TABLE orders (
    order_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,

    CONSTRAINT orders_id_not_blank
        CHECK (length(btrim(order_id)) > 0),
    CONSTRAINT orders_channel_not_blank
        CHECK (length(btrim(channel)) > 0),
    CONSTRAINT orders_amount_non_negative
        CHECK (amount >= 0),
    CONSTRAINT orders_status_valid
        CHECK (status IN (
            'pending',
            'paid',
            'shipped',
            'completed',
            'cancelled'
        ))
);


CREATE TABLE products (
    product_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit_price NUMERIC(12, 2) NOT NULL,

    CONSTRAINT products_id_not_blank
        CHECK (length(btrim(product_id)) > 0),
    CONSTRAINT products_name_not_blank
        CHECK (length(btrim(name)) > 0),
    CONSTRAINT products_category_not_blank
        CHECK (length(btrim(category)) > 0),
    CONSTRAINT products_unit_price_non_negative
        CHECK (unit_price >= 0)
);


CREATE TABLE order_items (
    order_item_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(12, 2) NOT NULL,

    CONSTRAINT order_items_id_not_blank
        CHECK (length(btrim(order_item_id)) > 0),
    CONSTRAINT order_items_quantity_positive
        CHECK (quantity > 0),
    CONSTRAINT order_items_price_non_negative
        CHECK (unit_price >= 0),
    CONSTRAINT order_items_order_fk
        FOREIGN KEY (order_id)
        REFERENCES orders(order_id)
        ON DELETE RESTRICT,
    CONSTRAINT order_items_product_fk
        FOREIGN KEY (product_id)
        REFERENCES products(product_id)
        ON DELETE RESTRICT
);


CREATE TABLE refunds (
    refund_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    refund_amount NUMERIC(12, 2) NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,

    CONSTRAINT refunds_id_not_blank
        CHECK (length(btrim(refund_id)) > 0),
    CONSTRAINT refunds_amount_positive
        CHECK (refund_amount > 0),
    CONSTRAINT refunds_reason_not_blank
        CHECK (length(btrim(reason)) > 0),
    CONSTRAINT refunds_status_valid
        CHECK (status IN (
            'requested',
            'approved',
            'rejected',
            'completed'
        )),
    CONSTRAINT refunds_order_fk
        FOREIGN KEY (order_id)
        REFERENCES orders(order_id)
        ON DELETE RESTRICT
);


CREATE INDEX idx_orders_status_created_at
    ON orders(status, created_at);

CREATE INDEX idx_order_items_order_id
    ON order_items(order_id);

CREATE INDEX idx_order_items_product_id
    ON order_items(product_id);

CREATE INDEX idx_refunds_order_id
    ON refunds(order_id);

CREATE INDEX idx_refunds_created_at
    ON refunds(created_at);


COMMIT;
