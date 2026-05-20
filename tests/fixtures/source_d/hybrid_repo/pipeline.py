import pandas as pd


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df["amount"] > 0]
    df["risk_band"] = df["score"]
    return df.dropna(subset=["borrower_id"])
