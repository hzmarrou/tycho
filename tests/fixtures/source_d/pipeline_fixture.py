"""Pipeline-family fixture: pandas DataFrame ops."""
import pandas as pd


def clean_loans(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df["amount"] > 0]
    df["risk_band"] = df["credit_score"].apply(
        lambda s: "high" if s < 500 else "low"
    )
    return df.dropna(subset=["borrower_id"])
