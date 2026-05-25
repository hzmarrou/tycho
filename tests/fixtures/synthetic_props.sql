-- Fixture for PR1b Source C persistence — synthetic schema covering
-- PK / FK / NOT NULL / VARCHAR(n) / DECIMAL(p,s) / CHECK IN enum /
-- composite-PK junction table. Used by test_source_c_persistence.py.
-- Intentionally tutorial-grade, not a realistic schema.

CREATE TABLE customer (
    id BIGINT PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    nickname VARCHAR(80),
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE order_record (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT NOT NULL,
    amount DECIMAL(18, 2) NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('open', 'paid', 'closed')),
    placed_at TIMESTAMP NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customer (id)
);

CREATE TABLE product (
    sku VARCHAR(32) PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    weight_kg DECIMAL(6, 3)
);

-- Junction table: composite PK + two FKs, no other non-PK non-FK
-- columns → many-to-many bridge.
CREATE TABLE order_item (
    order_id BIGINT NOT NULL,
    product_sku VARCHAR(32) NOT NULL,
    qty INTEGER NOT NULL,
    PRIMARY KEY (order_id, product_sku),
    FOREIGN KEY (order_id) REFERENCES order_record (id),
    FOREIGN KEY (product_sku) REFERENCES product (sku)
);
