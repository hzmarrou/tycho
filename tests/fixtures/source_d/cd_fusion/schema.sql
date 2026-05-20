CREATE TABLE loan (
  loan_id VARCHAR(32) PRIMARY KEY,
  amount NUMERIC NOT NULL CHECK (amount > 0)
);
