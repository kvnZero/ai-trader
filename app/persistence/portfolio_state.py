from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.persistence.db import Database


DEFAULT_CASH_ACCOUNT_KEY = "default"


@dataclass(frozen=True, slots=True)
class PortfolioHoldingRow:
    symbol: str
    name: str
    shares: float
    avg_cost: float
    last_price: float | None
    notes: str | None
    created_at: str
    updated_at: str

    @property
    def market_value(self) -> float | None:
        if self.last_price is None:
            return None
        return self.shares * self.last_price

    @property
    def cost_basis(self) -> float:
        return self.shares * self.avg_cost


@dataclass(frozen=True, slots=True)
class PortfolioCashBalanceRow:
    account_key: str
    balance: float
    updated_at: str


@dataclass(frozen=True, slots=True)
class PortfolioStateSummary:
    generated_at: str
    holdings_count: int
    total_shares: float
    total_cost_basis: float
    total_market_value: float
    cash_balance: float
    net_liquidation_value: float


class PortfolioHoldingRepository:
    def __init__(self, database: Database):
        self.database = database

    def list_rows(self) -> list[PortfolioHoldingRow]:
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT symbol, name, shares, avg_cost, last_price, notes, created_at, updated_at
                FROM portfolio_holdings
                ORDER BY symbol ASC
                """
            ).fetchall()
        return [self._row_to_holding(row) for row in rows]

    def get_row(self, symbol: str) -> PortfolioHoldingRow | None:
        normalized_symbol = symbol.strip()
        if not normalized_symbol:
            return None
        with self.database.connection() as conn:
            row = conn.execute(
                """
                SELECT symbol, name, shares, avg_cost, last_price, notes, created_at, updated_at
                FROM portfolio_holdings
                WHERE symbol = ?
                LIMIT 1
                """,
                (normalized_symbol,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_holding(row)

    def upsert_holding(
        self,
        *,
        symbol: str,
        name: str,
        shares: float,
        avg_cost: float,
        last_price: float | None = None,
        notes: str | None = None,
    ) -> bool:
        normalized_symbol = symbol.strip()
        normalized_name = name.strip()
        if not normalized_symbol or not normalized_name:
            return False

        with self.database.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO portfolio_holdings (
                    symbol, name, shares, avg_cost, last_price, notes
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    name = excluded.name,
                    shares = excluded.shares,
                    avg_cost = excluded.avg_cost,
                    last_price = excluded.last_price,
                    notes = excluded.notes,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    normalized_symbol,
                    normalized_name,
                    float(shares),
                    float(avg_cost),
                    float(last_price) if last_price is not None else None,
                    notes.strip() if isinstance(notes, str) and notes.strip() else None,
                ),
            )
            conn.commit()
        return cursor.rowcount > 0

    def delete_holding(self, symbol: str) -> bool:
        normalized_symbol = symbol.strip()
        if not normalized_symbol:
            return False
        with self.database.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM portfolio_holdings WHERE symbol = ?",
                (normalized_symbol,),
            )
            conn.commit()
        return cursor.rowcount > 0

    def build_summary(
        self,
        *,
        cash_balance: float = 0.0,
        generated_at: datetime | None = None,
    ) -> PortfolioStateSummary:
        holdings = self.list_rows()
        total_shares = sum(row.shares for row in holdings)
        total_cost_basis = sum(row.cost_basis for row in holdings)
        total_market_value = sum(row.market_value or 0.0 for row in holdings)
        timestamp = (generated_at or datetime.now(UTC)).isoformat(timespec="minutes")
        return PortfolioStateSummary(
            generated_at=timestamp,
            holdings_count=len(holdings),
            total_shares=total_shares,
            total_cost_basis=total_cost_basis,
            total_market_value=total_market_value,
            cash_balance=float(cash_balance),
            net_liquidation_value=total_market_value + float(cash_balance),
        )

    def _row_to_holding(self, row) -> PortfolioHoldingRow:
        return PortfolioHoldingRow(
            symbol=row["symbol"],
            name=row["name"],
            shares=float(row["shares"]),
            avg_cost=float(row["avg_cost"]),
            last_price=float(row["last_price"]) if row["last_price"] is not None else None,
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class PortfolioCashRepository:
    def __init__(self, database: Database):
        self.database = database

    def list_rows(self) -> list[PortfolioCashBalanceRow]:
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT account_key, balance, updated_at
                FROM portfolio_cash_balances
                ORDER BY account_key ASC
                """
            ).fetchall()
        return [self._row_to_cash_balance(row) for row in rows]

    def get_balance(
        self,
        account_key: str = DEFAULT_CASH_ACCOUNT_KEY,
    ) -> PortfolioCashBalanceRow | None:
        normalized_account_key = account_key.strip()
        if not normalized_account_key:
            return None
        with self.database.connection() as conn:
            row = conn.execute(
                """
                SELECT account_key, balance, updated_at
                FROM portfolio_cash_balances
                WHERE account_key = ?
                LIMIT 1
                """,
                (normalized_account_key,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_cash_balance(row)

    def upsert_balance(
        self,
        *,
        balance: float,
        account_key: str = DEFAULT_CASH_ACCOUNT_KEY,
    ) -> bool:
        normalized_account_key = account_key.strip()
        if not normalized_account_key:
            return False
        with self.database.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO portfolio_cash_balances (account_key, balance)
                VALUES (?, ?)
                ON CONFLICT(account_key) DO UPDATE SET
                    balance = excluded.balance,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (normalized_account_key, float(balance)),
            )
            conn.commit()
        return cursor.rowcount > 0

    def delete_balance(self, account_key: str = DEFAULT_CASH_ACCOUNT_KEY) -> bool:
        normalized_account_key = account_key.strip()
        if not normalized_account_key:
            return False
        with self.database.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM portfolio_cash_balances WHERE account_key = ?",
                (normalized_account_key,),
            )
            conn.commit()
        return cursor.rowcount > 0

    def _row_to_cash_balance(self, row) -> PortfolioCashBalanceRow:
        return PortfolioCashBalanceRow(
            account_key=row["account_key"],
            balance=float(row["balance"]),
            updated_at=row["updated_at"],
        )
