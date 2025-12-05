"""
Aurora Data API Client Wrapper

This module provides the `DataAPIClient` class, a high-level wrapper around
AWS Aurora Serverless **RDS Data API**, used by the Alex Financial Planner
backend to perform SQL operations without needing persistent database
connections.

The wrapper abstracts away the verbose AWS Data API request format and
exposes a clean Pythonic interface for:

• Executing SQL statements (`execute`)  
• Running queries and returning structured dictionaries (`query`, `query_one`)  
• Inserting, updating, and deleting rows with automatic type handling  
• Managing transactions for multi-step operations  
• Converting Python values to/from the Data API type system  

The class is intentionally lightweight and stateless, allowing it to be
created cheaply inside AWS Lambda while still supporting safe parameter
handling, JSON serialisation, numeric casting, and timestamp formatting.

It acts as the **low-level engine** behind all higher database abstractions
in `models.py` and is used throughout the backend for consistent and secure
database interaction.

Example:
    client = DataAPIClient()
    rows = client.query("SELECT * FROM users WHERE clerk_user_id = :id",
                        [{"name": "id", "value": {"stringValue": "user_123"}}])

Environment Variables:
    AURORA_CLUSTER_ARN – ARN of the Aurora cluster  
    AURORA_SECRET_ARN – ARN of the Secrets Manager secret  
    AURORA_DATABASE – Default database name (optional)  
    DEFAULT_AWS_REGION – Region for RDS Data API client  
"""

import boto3
import json
import os
from typing import List, Dict, Any, Optional
from datetime import date, datetime
from decimal import Decimal
from botocore.exceptions import ClientError
import logging

# Load environment variables if available
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

logger = logging.getLogger(__name__)


class DataAPIClient:
    """
    A high-level wrapper around AWS Aurora Serverless RDS Data API.

    This class simplifies SQL execution by:

    • Handling ARN configuration automatically  
    • Managing parameter type coercion and JSON serialisation  
    • Converting Data API responses into Python dictionaries  
    • Supporting INSERT/UPDATE/DELETE with optional RETURNING clauses  
    • Providing transaction control helpers  
    """

    def __init__(
        self,
        cluster_arn: Optional[str] = None,
        secret_arn: Optional[str] = None,
        database: Optional[str] = None,
        region: Optional[str] = None,
    ) -> None:
        """
        Initialise the Data API client.

        Parameters
        ----------
        cluster_arn : str, optional
            Aurora cluster ARN. Defaults to env `AURORA_CLUSTER_ARN`.
        secret_arn : str, optional
            Secrets Manager ARN. Defaults to env `AURORA_SECRET_ARN`.
        database : str, optional
            Database name. Defaults to env `AURORA_DATABASE` or "alex".
        region : str, optional
            AWS region. Defaults to env `DEFAULT_AWS_REGION` or us-east-1.
        """
        self.cluster_arn = cluster_arn or os.environ.get("AURORA_CLUSTER_ARN")
        self.secret_arn = secret_arn or os.environ.get("AURORA_SECRET_ARN")
        self.database = database or os.environ.get("AURORA_DATABASE", "alex")

        if not self.cluster_arn or not self.secret_arn:
            raise ValueError(
                "Missing required Aurora configuration. "
                "Ensure AURORA_CLUSTER_ARN and AURORA_SECRET_ARN are set."
            )

        self.region = region or os.environ.get("DEFAULT_AWS_REGION", "us-east-1")
        self.client = boto3.client("rds-data", region_name=self.region)

    # ============================================================
    # SQL Execution Methods
    # ============================================================

    def execute(self, sql: str, parameters: Optional[List[Dict]] = None) -> Dict:
        """
        Execute a SQL statement.

        Parameters
        ----------
        sql : str
            SQL statement to run.
        parameters : list of dict, optional
            Prepared-statement parameters.

        Returns
        -------
        dict
            Raw response from the Data API.
        """
        try:
            kwargs = {
                "resourceArn": self.cluster_arn,
                "secretArn": self.secret_arn,
                "database": self.database,
                "sql": sql,
                "includeResultMetadata": True,
            }

            if parameters:
                kwargs["parameters"] = parameters

            return self.client.execute_statement(**kwargs)

        except ClientError as e:
            logger.error(f"Database error: {e}")
            raise

    def query(self, sql: str, parameters: Optional[List[Dict]] = None) -> List[Dict]:
        """
        Execute a SELECT query and return structured results.

        Parameters
        ----------
        sql : str
            SELECT statement.
        parameters : list of dict, optional
            Prepared-statement parameters.

        Returns
        -------
        list of dict
            Rows mapped as `{column_name: value}`.
        """
        response = self.execute(sql, parameters)
        if "records" not in response:
            return []

        columns = [col["name"] for col in response.get("columnMetadata", [])]
        results = []

        for record in response["records"]:
            row = {
                columns[i]: self._extract_value(record[i])
                for i in range(len(columns))
            }
            results.append(row)

        return results

    def query_one(self, sql: str, parameters: Optional[List[Dict]] = None) -> Optional[Dict]:
        """
        Execute a SELECT statement and return the first row.

        Returns
        -------
        dict or None
        """
        results = self.query(sql, parameters)
        return results[0] if results else None

    # ============================================================
    # INSERT / UPDATE / DELETE
    # ============================================================

    def insert(self, table: str, data: Dict, returning: Optional[str] = None) -> Optional[str]:
        """
        Insert a row into a table.

        Parameters
        ----------
        table : str
            Target table name.
        data : dict
            Column → value mapping.
        returning : str, optional
            Column to return (e.g. primary key).

        Returns
        -------
        str or None
            Returned value from RETURNING clause.
        """
        columns = list(data.keys())
        placeholders = []

        for col in columns:
            val = data[col]
            if isinstance(val, (dict, list)):
                placeholders.append(f":{col}::jsonb")
            elif isinstance(val, Decimal):
                placeholders.append(f":{col}::numeric")
            elif isinstance(val, date) and not isinstance(val, datetime):
                placeholders.append(f":{col}::date")
            elif isinstance(val, datetime):
                placeholders.append(f":{col}::timestamp")
            else:
                placeholders.append(f":{col}")

        sql = f"""
            INSERT INTO {table} ({", ".join(columns)})
            VALUES ({", ".join(placeholders)})
        """

        if returning:
            sql += f" RETURNING {returning}"

        parameters = self._build_parameters(data)
        response = self.execute(sql, parameters)

        if returning and response.get("records"):
            return self._extract_value(response["records"][0][0])
        return None

    def update(self, table: str, data: Dict, where: str, where_params: Optional[Dict] = None) -> int:
        """
        Update rows in a table.

        Parameters
        ----------
        table : str
            Target table name.
        data : dict
            Columns and updated values.
        where : str
            SQL WHERE clause (no "WHERE" keyword).
        where_params : dict, optional
            Parameter values for WHERE clause.

        Returns
        -------
        int
            Number of updated rows.
        """
        set_parts = []
        for col, val in data.items():
            if isinstance(val, (dict, list)):
                set_parts.append(f"{col} = :{col}::jsonb")
            elif isinstance(val, Decimal):
                set_parts.append(f"{col} = :{col}::numeric")
            elif isinstance(val, date) and not isinstance(val, datetime):
                set_parts.append(f"{col} = :{col}::date")
            elif isinstance(val, datetime):
                set_parts.append(f"{col} = :{col}::timestamp")
            else:
                set_parts.append(f"{col} = :{col}")

        sql = f"""
            UPDATE {table}
            SET {", ".join(set_parts)}
            WHERE {where}
        """

        all_params = {**data, **(where_params or {})}
        parameters = self._build_parameters(all_params)

        response = self.execute(sql, parameters)
        return response.get("numberOfRecordsUpdated", 0)

    def delete(self, table: str, where: str, where_params: Optional[Dict] = None) -> int:
        """
        Delete rows matching a condition.

        Returns
        -------
        int
            Number of deleted rows.
        """
        sql = f"DELETE FROM {table} WHERE {where}"
        parameters = self._build_parameters(where_params) if where_params else None

        response = self.execute(sql, parameters)
        return response.get("numberOfRecordsUpdated", 0)

    # ============================================================
    # Transaction Helpers
    # ============================================================

    def begin_transaction(self) -> str:
        """Begin a new transaction and return its ID."""
        response = self.client.begin_transaction(
            resourceArn=self.cluster_arn,
            secretArn=self.secret_arn,
            database=self.database,
        )
        return response["transactionId"]

    def commit_transaction(self, transaction_id: str) -> None:
        """Commit a previously started transaction."""
        self.client.commit_transaction(
            resourceArn=self.cluster_arn,
            secretArn=self.secret_arn,
            transactionId=transaction_id,
        )

    def rollback_transaction(self, transaction_id: str) -> None:
        """Rollback a previously started transaction."""
        self.client.rollback_transaction(
            resourceArn=self.cluster_arn,
            secretArn=self.secret_arn,
            transactionId=transaction_id,
        )

    # ============================================================
    # Internal Helpers
    # ============================================================

    def _build_parameters(self, data: Dict) -> List[Dict]:
        """
        Convert a dict of parameters into AWS Data API format.

        Handles JSON, timestamps, Decimals, and ISO formatting.
        """
        if not data:
            return []

        params = []
        for key, value in data.items():
            param = {"name": key}

            if value is None:
                param["value"] = {"isNull": True}
            elif isinstance(value, bool):
                param["value"] = {"booleanValue": value}
            elif isinstance(value, int):
                param["value"] = {"longValue": value}
            elif isinstance(value, float):
                param["value"] = {"doubleValue": value}
            elif isinstance(value, Decimal):
                param["value"] = {"stringValue": str(value)}
            elif isinstance(value, (date, datetime)):
                param["value"] = {"stringValue": value.isoformat()}
            elif isinstance(value, (dict, list)):
                param["value"] = {"stringValue": json.dumps(value)}
            else:
                param["value"] = {"stringValue": str(value)}

            params.append(param)

        return params

    def _extract_value(self, field: Dict) -> Any:
        """
        Convert Data API field values to native Python types.

        Automatically parses JSON-encoded dicts/lists.
        """
        if field.get("isNull"):
            return None
        if "booleanValue" in field:
            return field["booleanValue"]
        if "longValue" in field:
            return field["longValue"]
        if "doubleValue" in field:
            return field["doubleValue"]
        if "stringValue" in field:
            value = field["stringValue"]
            if value and value[0] in ["{", "["]:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return value
        if "blobValue" in field:
            return field["blobValue"]

        return None
