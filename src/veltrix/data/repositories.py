"""Database repository layer for employees, leave balances, and requests."""

import sqlite3
from typing import cast

from veltrix.domain.models import Employee, LeaveBalance, LeaveRequest, Role


class EmployeeRepository:
    """Repository for querying employee records from veltrix.db."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_by_id(self, employee_id: str) -> Employee | None:
        """Fetch employee by ID, or return None if not found."""
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT employee_id, full_name, email, phone, region, join_date, level, role, manager_id
                FROM employees
                WHERE employee_id = ?
                """,
                (employee_id.strip(),),
            ).fetchone()
            if not row:
                return None
            return Employee(
                employee_id=row["employee_id"],
                full_name=row["full_name"],
                email=row["email"],
                phone=row["phone"],
                region=row["region"],
                join_date=row["join_date"],
                level=row["level"],
                role=cast(Role, row["role"]),
                manager_id=row["manager_id"],
            )

    def get_direct_reports(self, manager_id: str) -> list[Employee]:
        """Fetch all employees whose manager_id matches the given manager."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT employee_id, full_name, email, phone, region, join_date, level, role, manager_id
                FROM employees
                WHERE manager_id = ?
                ORDER BY employee_id
                """,
                (manager_id.strip(),),
            ).fetchall()
            return [
                Employee(
                    employee_id=r["employee_id"],
                    full_name=r["full_name"],
                    email=r["email"],
                    phone=r["phone"],
                    region=r["region"],
                    join_date=r["join_date"],
                    level=r["level"],
                    role=cast(Role, r["role"]),
                    manager_id=r["manager_id"],
                )
                for r in rows
            ]
