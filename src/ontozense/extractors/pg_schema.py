"""PostgreSQL schema parser.

Connects to a live PostgreSQL database and extracts schema information
(tables, columns, types, primary keys, foreign keys) using information_schema.
No Django, no SQLAlchemy — just psycopg2 and SQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .django_schema import SchemaField, SchemaModel, SchemaRelationship, SchemaResult

# PostgreSQL data_type → Playground property type mapping
PG_TYPE_MAP = {
    "text": "string",
    "character": "string",
    "character varying": "string",
    "varchar": "string",
    "uuid": "string",
    "json": "string",
    "jsonb": "string",
    "integer": "integer",
    "smallint": "integer",
    "bigint": "integer",
    "serial": "integer",
    "bigserial": "integer",
    "numeric": "decimal",
    "decimal": "decimal",
    "real": "double",
    "double precision": "double",
    "float": "double",
    "boolean": "boolean",
    "date": "date",
    "timestamp with time zone": "datetime",
    "timestamp without time zone": "datetime",
    "timestamp": "datetime",
    "time": "string",
    "interval": "string",
    "bytea": "string",
}


class PostgresSchemaParser:
    """Parses schema from a live PostgreSQL database."""

    def __init__(
        self,
        dbname: str,
        schema: str = "public",
        host: str = "localhost",
        port: int = 5432,
        user: str = "postgres",
        password: str = "",
    ):
        self.dbname = dbname
        self.schema = schema
        self.host = host
        self.port = port
        self.user = user
        self.password = password

    def parse(self) -> SchemaResult:
        """Connect to PostgreSQL and extract schema information."""
        import psycopg2

        conn = psycopg2.connect(
            dbname=self.dbname,
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
        )
        try:
            return self._extract_schema(conn)
        finally:
            conn.close()

    def _extract_schema(self, conn) -> SchemaResult:
        """Extract all tables, columns, PKs, FKs, and comments."""
        cur = conn.cursor()

        # 1. Get all tables
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """, (self.schema,))
        table_names = [row[0] for row in cur.fetchall()]

        # 2. Get all columns
        cur.execute("""
            SELECT table_name, column_name, data_type, is_nullable,
                   character_maximum_length, ordinal_position
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position
        """, (self.schema,))
        columns_by_table: dict[str, list[dict]] = {}
        for row in cur.fetchall():
            columns_by_table.setdefault(row[0], []).append({
                "name": row[1],
                "data_type": row[2],
                "is_nullable": row[3] == "YES",
                "max_length": row[4],
            })

        # 3. Get primary keys
        cur.execute("""
            SELECT kcu.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = %s
        """, (self.schema,))
        pk_columns: dict[str, set[str]] = {}
        for row in cur.fetchall():
            pk_columns.setdefault(row[0], set()).add(row[1])

        # 4. Get foreign keys
        cur.execute("""
            SELECT
                kcu.table_name as from_table,
                kcu.column_name as from_column,
                ccu.table_name as to_table,
                ccu.column_name as to_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
                AND tc.table_schema = ccu.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = %s
        """, (self.schema,))
        fk_by_table: dict[str, list[dict]] = {}
        for row in cur.fetchall():
            # Skip self-referential FKs that are clearly wrong (info_schema quirk)
            if row[0] == row[2] and row[1] != row[3]:
                # Could be legit self-reference, keep it
                pass
            fk_by_table.setdefault(row[0], []).append({
                "from_column": row[1],
                "to_table": row[2],
                "to_column": row[3],
            })

        # 5. Get column comments
        cur.execute("""
            SELECT c.relname as table_name, a.attname as column_name,
                   d.description as comment
            FROM pg_catalog.pg_description d
            JOIN pg_catalog.pg_attribute a ON d.objoid = a.attrelid AND d.objsubid = a.attnum
            JOIN pg_catalog.pg_class c ON a.attrelid = c.oid
            JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = %s AND a.attnum > 0
        """, (self.schema,))
        comments: dict[tuple[str, str], str] = {}
        for row in cur.fetchall():
            comments[(row[0], row[1])] = row[2]

        # 6. Get table comments
        cur.execute("""
            SELECT c.relname, d.description
            FROM pg_catalog.pg_description d
            JOIN pg_catalog.pg_class c ON d.objoid = c.oid
            JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = %s AND d.objsubid = 0
        """, (self.schema,))
        table_comments: dict[str, str] = {}
        for row in cur.fetchall():
            table_comments[row[0]] = row[1]

        # 7. Detect enum-like columns (text columns with few distinct values)
        enum_values: dict[tuple[str, str], list[str]] = {}
        for table_name in table_names:
            text_cols = [
                col["name"] for col in columns_by_table.get(table_name, [])
                if col["data_type"] in ("text", "character varying")
            ]
            for col_name in text_cols:
                try:
                    cur.execute(f"""
                        SELECT DISTINCT {col_name}
                        FROM {self.schema}.{table_name}
                        WHERE {col_name} IS NOT NULL
                        ORDER BY {col_name}
                        LIMIT 25
                    """)
                    values = [row[0] for row in cur.fetchall()]
                    # If ≤ 15 distinct values, treat as enum
                    if 2 <= len(values) <= 15:
                        cur.execute(f"SELECT COUNT(DISTINCT {col_name}) FROM {self.schema}.{table_name}")
                        total_distinct = cur.fetchone()[0]
                        if total_distinct <= 15:
                            enum_values[(table_name, col_name)] = values
                except Exception:
                    pass  # Skip columns that cause issues

        cur.close()

        # Build SchemaResult
        result = SchemaResult(source_dir=f"postgresql://{self.host}/{self.dbname}/{self.schema}")

        for table_name in table_names:
            pks = pk_columns.get(table_name, set())
            fks = fk_by_table.get(table_name, [])
            fk_columns = {fk["from_column"] for fk in fks}

            model = SchemaModel(
                name=self._to_class_name(table_name),
                doc=table_comments.get(table_name, ""),
                source_file=table_name,
            )

            for col in columns_by_table.get(table_name, []):
                col_name = col["name"]

                # Skip FK columns — they become relationships
                if col_name in fk_columns:
                    continue

                # Skip auto-generated columns
                if col_name == "created_at":
                    continue

                pg_type = col["data_type"]
                playground_type = PG_TYPE_MAP.get(pg_type, "string")

                # Check if this is an enum column
                enum_vals = enum_values.get((table_name, col_name), [])
                if enum_vals:
                    playground_type = "enum"

                comment = comments.get((table_name, col_name), "")

                model.fields.append(SchemaField(
                    name=col_name,
                    field_type=pg_type,
                    playground_type=playground_type,
                    is_primary_key=col_name in pks,
                    is_nullable=col["is_nullable"],
                    help_text=comment,
                    choices_values=enum_vals,
                    max_length=col["max_length"],
                ))

            # Add relationships from FKs
            for fk in fks:
                to_table = fk["to_table"]
                # Skip self-referential FKs where from_table == to_table
                # (info_schema sometimes reports these incorrectly)
                if to_table == table_name:
                    # Check if it's a real self-reference by looking at column names
                    if fk["from_column"] == fk["to_column"]:
                        continue

                model.relationships.append(SchemaRelationship(
                    field_name=fk["from_column"],
                    from_model=self._to_class_name(table_name),
                    to_model=self._to_class_name(to_table),
                    is_nullable=any(
                        c["is_nullable"] for c in columns_by_table.get(table_name, [])
                        if c["name"] == fk["from_column"]
                    ),
                ))

            result.models.append(model)

        return result

    @staticmethod
    def _to_class_name(table_name: str) -> str:
        """Convert snake_case table name to PascalCase class name."""
        return "".join(word.capitalize() for word in table_name.split("_"))
