CREATE TABLE customers (
    customer_id INT PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(200),
    birth_date DATE,
    created_at TIMESTAMP
);

CREATE TABLE loans (
    loan_id INT PRIMARY KEY,
    customer_id INT,
    amount DECIMAL(10, 2),
    term_months INT,
    status_code VARCHAR(10),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (status_code) REFERENCES loan_status(code)
);

CREATE TABLE loan_status (
    code VARCHAR(10) PRIMARY KEY,
    description VARCHAR(200)
);

CREATE TABLE customer_audit (
    audit_id INT PRIMARY KEY,
    customer_id INT,
    event VARCHAR(50),
    occurred_at TIMESTAMP
);
