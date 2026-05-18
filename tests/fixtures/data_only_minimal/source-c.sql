CREATE TABLE customers (
    customer_id INT PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(200),
    birth_date DATE,
    country_code VARCHAR(2),
    FOREIGN KEY (country_code) REFERENCES countries(code)
);

CREATE TABLE countries (
    code VARCHAR(2) PRIMARY KEY,
    name VARCHAR(100)
);

CREATE TABLE orders (
    order_id INT PRIMARY KEY,
    customer_id INT,
    total DECIMAL(10, 2),
    placed_at TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);
