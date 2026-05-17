# # """
# # Database layer for the pipeline.

# # Provides:
# # - Connection pooling via DBUtils.PooledDB + pymysql
# # - Pure snapshot functions (apply_eta_snapshot, apply_actual_snapshot)
# # - Shipment CRUD operations against cargowise_containers_new
# # - Job-run tracking (job_runs, shipment_tracking tables)
# # - Excel import metadata persistence
# # """

# # import uuid
# # from contextlib import contextmanager
# # from typing import Any, Dict, List, Optional, Set

# # from dotenv.main import logger
# # import pymysql
# # from dbutils.pooled_db import PooledDB


# # # ------------------------------------------------------------------ #
# # # SQL query templates (class constants defined below the class)
# # # ------------------------------------------------------------------ #

# # AIR_SYNC_QUERY = """
# #     # SELECT JS_UniqueConsignRef FROM cargowise_containers_new
# #     # WHERE JS_TransportMode = %(mode)s AND primary_status = %(status)s
# #     # AND (do_not_query IS NULL OR do_not_query != 1)

# # """

# # # SEA_SYNC_QUERY = """
# # #     SELECT JS_UniqueConsignRef FROM cargowise_containers_new
# # #     WHERE JS_TransportMode = %(mode)s AND primary_status = %(status)s
# # #     AND (do_not_query IS NULL OR do_not_query != 1)
# # #     AND (
# # #         (currentETD IS NOT NULL
# # #          AND COALESCE(
# # #              STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%dT%%H:%%i:%%s'),
# # #              STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%d %%H:%%i:%%s')
# # #          ) IS NULL)
# # #         OR DATE(currentETA) = CURRENT_DATE + INTERVAL %(window)s DAY
# # #     )
# # # """

# # SEA_SYNC_QUERY = """
# #     SELECT JS_UniqueConsignRef
# #     FROM cargowise_containers_new
# #     WHERE JS_TransportMode = %(mode)s
# #       AND primary_status = %(status)s
# #       AND (do_not_query IS NULL OR do_not_query != 1)
# #       AND (
# #             (
# #                 currentETD IS NOT NULL
# #                 AND COALESCE(
# #                       STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%dT%%H:%%i:%%s'),
# #                       STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%d %%H:%%i:%%s')
# #                     ) IS NULL
# #             )
# #             OR DATE(currentETA) = CURRENT_DATE + INTERVAL %(window)s DAY
# #           )
# # """


# # # SEA_REVERSE_QUERY = """
# # #     SELECT JS_UniqueConsignRef FROM cargowise_containers_new
# # #     WHERE JS_TransportMode = %(mode)s AND primary_status = %(status)s
# # #     AND (do_not_query IS NULL OR do_not_query != 1)
# # #     AND (
# # #         (currentETD IS NULL
# # #          OR COALESCE(
# # #              STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%dT%%H:%%i:%%s'),
# # #              STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%d %%H:%%i:%%s')
# # #          ) IS NOT NULL)
# # #         AND (currentETA IS NULL
# # #              OR DATE(currentETA) <> CURRENT_DATE + INTERVAL %(window)s DAY)
# # #     )
# # # """

# # SEA_REVERSE_QUERY = """
# #     SELECT JS_UniqueConsignRef
# #     FROM cargowise_containers_new
# #     WHERE JS_TransportMode = %(mode)s
# #       AND primary_status = %(status)s
# #       AND (do_not_query IS NULL OR do_not_query != 1)
# #       AND (
# #             (
# #                 currentETD IS NULL
# #                 OR COALESCE(
# #                       STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%dT%%H:%%i:%%s'),
# #                       STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%d %%H:%%i:%%s')
# #                     ) IS NOT NULL
# #             )
# #             AND (
# #                   currentETA IS NULL
# #                   AND DATE(currentETA) <> CURRENT_DATE + INTERVAL %(window)s DAY
# #                 )
# #           )
# # """


# # # ------------------------------------------------------------------ #
# # # Pure snapshot functions — no DB, fully testable
# # # ------------------------------------------------------------------ #

# # def _normalize(val: Any) -> Optional[str]:
# #     """Return None for empty-ish values, otherwise the string as-is."""
# #     if val is None:
# #         return None
# #     if isinstance(val, str) and val.strip() == "":
# #         return None
# #     return val


# # def apply_eta_snapshot(
# #     existing: Dict[str, Optional[str]],
# #     new_eta: Optional[str],
# # ) -> Dict[str, Optional[str]]:
# #     """
# #     Dual-column snapshot logic for ETA (mirrors ETD identically).

# #     Rules (from new_milestones5.py lines 3152-3178):
# #     - First insert (both current & updated are None): set both to new_eta.
# #     - Subsequent: if new_eta differs from current, update current; keep updated
# #       frozen.  If updated was still None, freeze it to the old current value.
# #     - If new_eta is None/empty, do nothing.
# #     """
# #     current = _normalize(existing.get("currentETA"))
# #     updated = _normalize(existing.get("updatedETA"))
# #     new_eta = _normalize(new_eta)

# #     if new_eta is None:
# #         # No new value provided — leave everything as-is
# #         return {"currentETA": current, "updatedETA": updated}

# #     if current is None and updated is None:
# #         # First insert
# #         return {"currentETA": new_eta, "updatedETA": new_eta}

# #     # Existing record
# #     if new_eta != current:
# #         if updated is None:
# #             updated = current  # freeze snapshot
# #         current = new_eta

# #     return {"currentETA": current, "updatedETA": updated}


# # def apply_actual_snapshot(
# #     existing: Dict[str, Optional[str]],
# #     new_value: Optional[str],
# #     kind: str,
# # ) -> Dict[str, Optional[str]]:
# #     """
# #     Dual-column snapshot logic for Actual Arrival / Actual Departure.

# #     Rules (from new_milestones5.py lines 3192-3207):
# #     - First insert or updated is None: set both to new_value.
# #     - Subsequent: only update current when value changes; keep updated frozen.
# #     - If new_value is None, do nothing.

# #     kind: "Arrival" or "Departure"
# #     """
# #     cur_key = f"currentActual{kind}"
# #     upd_key = f"updatedActual{kind}"

# #     current = _normalize(existing.get(cur_key))
# #     updated = _normalize(existing.get(upd_key))
# #     new_value = _normalize(new_value)

# #     if new_value is None:
# #         return {cur_key: current, upd_key: updated}

# #     if current is None and updated is None:
# #         # First insert — snapshot both
# #         return {cur_key: new_value, upd_key: new_value}

# #     if updated is None:
# #         # Snapshot missing — lock it, then update current
# #         return {cur_key: new_value, upd_key: current}

# #     # updated already frozen — only change current if different
# #     if new_value != current:
# #         current = new_value

# #     return {cur_key: current, upd_key: updated}


# # # ------------------------------------------------------------------ #
# # # Database class
# # # ------------------------------------------------------------------ #

# # class Database:
# #     """Pooled MySQL connection manager and query executor."""

# #     # Class-level query constants
# #     AIR_SYNC_QUERY = AIR_SYNC_QUERY
# #     SEA_SYNC_QUERY = SEA_SYNC_QUERY
# #     SEA_REVERSE_QUERY = SEA_REVERSE_QUERY

# #     def __init__(self, settings):
# #         self._settings = settings
# #         self._pool = PooledDB(
# #             creator=pymysql,
# #             maxconnections=settings.DB_POOL_SIZE,
# #             mincached=1,
# #             maxcached=settings.DB_POOL_SIZE,
# #             blocking=True,
# #             # blocking=False, 
# #             host=settings.DB_HOST,
# #             user=settings.DB_USER,
# #             password=settings.DB_PASSWORD,
# #             database=settings.DB_NAME,
# #             charset="utf8mb4",
# #             cursorclass=pymysql.cursors.DictCursor,
# #             autocommit=True,
            
# #         )

# #     # ---- connection context manager -------------------------------- #

# #     @contextmanager
# #     def get_connection(self):
# #         """Yield a pooled connection; return it to the pool on exit."""
# #         print("⏳ Trying to get DB connection...")
# #         conn = self._pool.connection()
# #         print("✅ DB connection successful")
# #         try:
# #             yield conn
# #         finally:
# #             conn.close()

# #     # ================================================================ #
# #     # Shipment operations
# #     # ================================================================ #

# #     def get_existing_shipment_ids(self) -> Set[str]:
# #         """Return set of all JS_UniqueConsignRef values."""
# #         conn = self._pool.connection()
# #         try:
# #             with conn.cursor() as cur:
# #                 cur.execute(
# #                     "SELECT JS_UniqueConsignRef FROM cargowise_containers_new"
# #                 )
# #                 rows = cur.fetchall()
# #                 return {
# #                     r["JS_UniqueConsignRef"]
# #                     for r in rows
# #                     if r.get("JS_UniqueConsignRef")
# #                 }
# #         finally:
# #             conn.close()

# #     def fetch_eta_etd(self, shipment_id: str) -> Optional[Dict]:
# #         """Return {currentETA, updatedETA, currentETD, updatedETD} or None."""
# #         conn = self._pool.connection()
# #         try:
# #             with conn.cursor() as cur:
# #                 cur.execute(
# #                     """
# #                     SELECT currentETA, updatedETA, currentETD, updatedETD
# #                     FROM cargowise_containers_new
# #                     WHERE JS_UniqueConsignRef = %s
# #                     LIMIT 1
# #                     """,
# #                     (shipment_id,),
# #                 )
# #                 row = cur.fetchone()
# #                 return row if row else None
# #         finally:
# #             conn.close()

# #     def fetch_actuals(self, shipment_id: str) -> Optional[Dict]:
# #         """Return {currentActualArrival, updatedActualArrival, ...} or None."""
# #         conn = self._pool.connection()
# #         try:
# #             with conn.cursor() as cur:
# #                 cur.execute(
# #                     """
# #                     SELECT currentActualArrival, updatedActualArrival,
# #                            currentActualDeparture, updatedActualDeparture
# #                     FROM cargowise_containers_new
# #                     WHERE JS_UniqueConsignRef = %s
# #                     LIMIT 1
# #                     """,
# #                     (shipment_id,),
# #                 )
# #                 row = cur.fetchone()
# #                 return row if row else None
# #         finally:
# #             conn.close()

# #     def upsert_shipment(self, record: Dict) -> None:
# #         """
# #         Check if shipment exists by JS_UniqueConsignRef.
# #         UPDATE if it does, INSERT if it does not.
# #         """
# #         shipment_id = record.get("JS_UniqueConsignRef")
# #         columns = list(record.keys())

# #         conn = self._pool.connection()
# #         try:
# #             with conn.cursor() as cur:
# #                 cur.execute(
# #                     """
# #                     SELECT COUNT(*) AS cnt
# #                     FROM cargowise_containers_new
# #                     WHERE JS_UniqueConsignRef = %s
# #                     """,
# #                     (shipment_id,),
# #                 )
# #                 exists = cur.fetchone()["cnt"] > 0

# #                 if exists:
# #                     update_cols = [c for c in columns if c != "JS_UniqueConsignRef"]
# #                     set_clause = ", ".join(f"{c} = %s" for c in update_cols)
# #                     values = [record.get(c) for c in update_cols] + [shipment_id]
# #                     cur.execute(
# #                         f"UPDATE cargowise_containers_new SET {set_clause} "
# #                         f"WHERE JS_UniqueConsignRef = %s",
# #                         values,
# #                     )
# #                 else:
# #                     placeholders = ", ".join(["%s"] * len(columns))
# #                     col_names = ", ".join(columns)
# #                     values = [record.get(c) for c in columns]
# #                     cur.execute(
# #                         f"INSERT INTO cargowise_containers_new ({col_names}) "
# #                         f"VALUES ({placeholders})",
# #                         values,
# #                     )
# #             conn.commit()
# #         finally:
# #             conn.close()

# #     def get_active_shipments(
# #         self,
# #         mode: str,
# #         status: str,
# #         extra_where: str = "",
# #         params: Optional[Dict] = None,
# #     ) -> List[str]:
# #         """Return list of JS_UniqueConsignRef matching mode + status + extras."""
# #         print(extra_where , " : extra wher")
# #         sql = (
# #             "SELECT JS_UniqueConsignRef FROM cargowise_containers_new "
# #             "WHERE JS_TransportMode = %(mode)s AND primary_status = %(status)s "
# #             "AND (do_not_query IS NULL OR do_not_query != 1)"
# #         )
# #         if extra_where:
# #             sql += f" AND ({extra_where})"
# #             logger.info(f"SQL ashish: {sql}")

        
        
# #         query_params: Dict = {"mode": mode, "status": status}
        
     
# #         if params:
# #             query_params.update(params)

# #         conn = self._pool.connection()
        
        
# #         try:
# #             with conn.cursor() as cur:
# #                 cur.execute(sql, query_params)
# #                 rows = cur.fetchall()
# #                 return [r["JS_UniqueConsignRef"] for r in rows]
# #         finally:
# #             conn.close()
            
            
            

# #     def mark_do_not_query(self, shipment_id: str) -> None:
# #         """Set do_not_query = 1 for a shipment."""
# #         conn = self._pool.connection()
# #         try:
# #             with conn.cursor() as cur:
# #                 cur.execute(
# #                     "UPDATE cargowise_containers_new "
# #                     "SET do_not_query = 1 WHERE JS_UniqueConsignRef = %s",
# #                     (shipment_id,),
# #                 )
# #             conn.commit()
# #         finally:
# #             conn.close()

# #     # ================================================================ #
# #     # Job tracking
# #     # ================================================================ #

# #     def create_job_run(self, job_type: str) -> str:
# #         """Insert a new job_runs row and return its UUID."""
# #         job_id = str(uuid.uuid4())
# #         conn = self._pool.connection()
# #         try:
# #             with conn.cursor() as cur:
# #                 cur.execute(
# #                     "INSERT INTO job_runs (id, job_type, status) "
# #                     "VALUES (%s, %s, 'running')",
# #                     (job_id, job_type),
# #                 )
# #             conn.commit()
# #         finally:
# #             conn.close()
# #         return job_id

# #     def complete_job_run(
# #         self,
# #         job_run_id: str,
# #         processed: int,
# #         failed: int,
# #         error_summary: Optional[str] = None,
# #     ) -> None:
# #         """Mark a job_run as completed (or failed if failed > 0)."""
# #         status = "failed" if failed > 0 and processed == 0 else "completed"
# #         conn = self._pool.connection()
# #         try:
# #             with conn.cursor() as cur:
# #                 cur.execute(
# #                     "UPDATE job_runs "
# #                     "SET status = %s, processed_count = %s, failed_count = %s, "
# #                     "    error_summary = %s, completed_at = NOW() "
# #                     "WHERE id = %s",
# #                     (status, processed, failed, error_summary, job_run_id),
# #                 )
# #             conn.commit()
# #         finally:
# #             conn.close()

# #     def track_shipment(
# #         self,
# #         shipment_id: str,
# #         job_run_id: str,
# #         job_type: str,
# #         status: str = "pending",
# #     ) -> None:
# #         """Insert a single shipment_tracking row."""
# #         conn = self._pool.connection()
# #         try:
# #             with conn.cursor() as cur:
# #                 cur.execute(
# #                     "INSERT INTO shipment_tracking "
# #                     "(shipment_id, job_run_id, job_type, status) "
# #                     "VALUES (%s, %s, %s, %s)",
# #                     (shipment_id, job_run_id, job_type, status),
# #                 )
# #             conn.commit()
# #         finally:
# #             conn.close()

# #     def bulk_track_shipments(
# #         self,
# #         shipment_ids: List[str],
# #         job_run_id: str,
# #         job_type: str,
# #     ) -> None:
# #         """Bulk-insert shipment_tracking rows for a list of shipment IDs."""
# #         if not shipment_ids:
# #             return
# #         conn = self._pool.connection()
# #         try:
# #             with conn.cursor() as cur:
# #                 cur.executemany(
# #                     "INSERT INTO shipment_tracking "
# #                     "(shipment_id, job_run_id, job_type, status) "
# #                     "VALUES (%s, %s, %s, 'pending')",
# #                     [(sid, job_run_id, job_type) for sid in shipment_ids],
# #                 )
# #             conn.commit()
# #         finally:
# #             conn.close()

# #     def update_tracking(
# #         self,
# #         shipment_id: str,
# #         job_run_id: str,
# #         status: str,
# #         error: Optional[str] = None,
# #         retry_count: Optional[int] = None,
# #     ) -> None:
# #         """Update shipment_tracking row status (and optionally error / retry)."""
# #         parts = ["status = %s", "error_message = %s"]
# #         values: list = [status, error]

# #         if status == "in_progress":
# #             parts.append("started_at = NOW()")
# #         if status in ("completed", "failed"):
# #             parts.append("completed_at = NOW()")
# #         if retry_count is not None:
# #             parts.append("retry_count = %s")
# #             values.append(retry_count)

# #         values.extend([shipment_id, job_run_id])

# #         conn = self._pool.connection()
# #         try:
# #             with conn.cursor() as cur:
# #                 cur.execute(
# #                     f"UPDATE shipment_tracking SET {', '.join(parts)} "
# #                     f"WHERE shipment_id = %s AND job_run_id = %s",
# #                     values,
# #                 )
# #             conn.commit()
# #         finally:
# #             conn.close()

# #     def get_interrupted(self) -> List[Dict]:
# #         """
# #         Return shipments that were in_progress or pending when a job_run
# #         was still 'running' (i.e. interrupted).
# #         """
# #         conn = self._pool.connection()
# #         try:
# #             with conn.cursor() as cur:
# #                 cur.execute(
# #                     """
# #                     SELECT st.shipment_id, st.job_run_id, st.job_type,
# #                            st.retry_count, st.lifetime_retry_count
# #                     FROM shipment_tracking st
# #                     JOIN job_runs jr ON jr.id = st.job_run_id
# #                     WHERE jr.status = 'running'
# #                       AND st.status IN ('in_progress', 'pending')
# #                     """
# #                 )
# #                 return cur.fetchall()
# #         finally:
# #             conn.close()

# #     def get_failed_shipments(self) -> List[Dict]:
# #         """
# #         Return shipments that failed in the last 24 hours and whose
# #         lifetime_retry_count is below the threshold.
# #         """
# #         threshold = self._settings.SHIPMENT_MAX_LIFETIME_RETRIES
# #         conn = self._pool.connection()
# #         try:
# #             with conn.cursor() as cur:
# #                 cur.execute(
# #                     """
# #                     SELECT shipment_id, job_run_id, job_type,
# #                            retry_count, lifetime_retry_count, error_message
# #                     FROM shipment_tracking
# #                     WHERE status = 'failed'
# #                       AND completed_at >= NOW() - INTERVAL 24 HOUR
# #                       AND lifetime_retry_count < %s
# #                     """,
# #                     (threshold,),
# #                 )
# #                 return cur.fetchall()
# #         finally:
# #             conn.close()

# #     def get_dead_letter_shipments(self) -> List[Dict]:
# #         """
# #         Return shipments whose lifetime_retry_count has reached
# #         the max threshold — candidates for dead-letter alerting.
# #         """
# #         threshold = self._settings.SHIPMENT_MAX_LIFETIME_RETRIES
# #         conn = self._pool.connection()
# #         try:
# #             with conn.cursor() as cur:
# #                 cur.execute(
# #                     """
# #                     SELECT shipment_id, job_run_id, job_type,
# #                            lifetime_retry_count, error_message
# #                     FROM shipment_tracking
# #                     WHERE status = 'failed'
# #                       AND lifetime_retry_count >= %s
# #                     """,
# #                     (threshold,),
# #                 )
# #                 return cur.fetchall()
# #         finally:
# #             conn.close()

# #     def was_processed_in_cycle(
# #         self, shipment_id: str, parent_job_run_id: str
# #     ) -> bool:
# #         """Check if shipment was already completed in a given job run."""
# #         conn = self._pool.connection()
# #         try:
# #             with conn.cursor() as cur:
# #                 cur.execute(
# #                     """
# #                     SELECT COUNT(*) AS cnt FROM shipment_tracking
# #                     WHERE shipment_id = %s
# #                       AND job_run_id = %s
# #                       AND status = 'completed'
# #                     """,
# #                     (shipment_id, parent_job_run_id),
# #                 )
# #                 return cur.fetchone()["cnt"] > 0
# #         finally:
# #             conn.close()

# #     # ================================================================ #
# #     # Excel imports
# #     # ================================================================ #

# #     def save_excel_metadata(self, metadata: Dict) -> int:
# #         """Insert excel_imports row and return the auto-increment id."""
# #         conn = self._pool.connection()
# #         try:
# #             with conn.cursor() as cur:
# #                 cur.execute(
# #                     """
# #                     INSERT INTO excel_imports
# #                         (filename, sftp_path, file_size_bytes, file_modified_at,
# #                          row_count, new_shipment_count, job_run_id, status,
# #                          local_path, s3_archive_path)
# #                     VALUES
# #                         (%(filename)s, %(sftp_path)s, %(file_size_bytes)s,
# #                          %(file_modified_at)s, %(row_count)s,
# #                          %(new_shipment_count)s, %(job_run_id)s,
# #                          %(status)s, %(local_path)s, %(s3_archive_path)s)
# #                     """,
# #                     {
# #                         "filename": metadata.get("filename"),
# #                         "sftp_path": metadata.get("sftp_path"),
# #                         "file_size_bytes": metadata.get("file_size_bytes"),
# #                         "file_modified_at": metadata.get("file_modified_at"),
# #                         "row_count": metadata.get("row_count", 0),
# #                         "new_shipment_count": metadata.get("new_shipment_count", 0),
# #                         "job_run_id": metadata.get("job_run_id"),
# #                         "status": metadata.get("status", "downloaded"),
# #                         "local_path": metadata.get("local_path"),
# #                         "s3_archive_path": metadata.get("s3_archive_path"),
# #                     },
# #                 )
# #                 import_id = cur.lastrowid
# #             conn.commit()
# #             return import_id
# #         finally:
# #             conn.close()

# #     def save_excel_rows(self, import_id: int, rows: List[Dict]) -> None:
# #         """Bulk-insert excel_import_rows."""
# #         if not rows:
# #             return
# #         conn = self._pool.connection()
# #         try:
# #             with conn.cursor() as cur:
# #                 cur.executemany(
# #                     """
# #                     INSERT INTO excel_import_rows
# #                         (excel_import_id, shipment_id, raw_row_data, is_new)
# #                     VALUES (%s, %s, %s, %s)
# #                     """,
# #                     [
# #                         (
# #                             import_id,
# #                             r.get("shipment_id"),
# #                             r.get("raw_row_data"),
# #                             r.get("is_new", False),
# #                         )
# #                         for r in rows
# #                     ],
# #                 )
# #             conn.commit()
# #         finally:
# #             conn.close()

# #     # ================================================================ #
# #     # Maintenance
# #     # ================================================================ #

# #     def purge_old_tracking(self, retention_days: int) -> None:
# #         """
# #         Delete job_runs older than retention_days.
# #         CASCADE handles shipment_tracking, excel_imports, excel_import_rows.
# #         """
# #         conn = self._pool.connection()
# #         try:
# #             with conn.cursor() as cur:
# #                 cur.execute(
# #                     "DELETE FROM job_runs "
# #                     "WHERE started_at < NOW() - INTERVAL %s DAY",
# #                     (retention_days,),
# #                 )
# #             conn.commit()
# #         finally:
# #             conn.close()





# """
# Database layer for the pipeline.

# Provides:
# - Connection pooling via DBUtils.PooledDB + pymysql
# - Pure snapshot functions (apply_eta_snapshot, apply_actual_snapshot)
# - Shipment CRUD operations against cargowise_containers_new
# - Job-run tracking (job_runs, shipment_tracking tables)
# - Excel import metadata persistence
# """

# import uuid
# from contextlib import contextmanager
# from typing import Any, Dict, List, Optional, Set

# from dotenv.main import logger
# import pymysql
# from dbutils.pooled_db import PooledDB


# # ------------------------------------------------------------------ #
# # SQL query templates (class constants defined below the class)
# # ------------------------------------------------------------------ #

# AIR_SYNC_QUERY = """
#     # SELECT JS_UniqueConsignRef FROM cargowise_containers_new
#     # WHERE JS_TransportMode = %(mode)s AND primary_status = %(status)s
#     # AND (do_not_query IS NULL OR do_not_query != 1)

# """

# # SEA_SYNC_QUERY = """
# #     SELECT JS_UniqueConsignRef FROM cargowise_containers_new
# #     WHERE JS_TransportMode = %(mode)s AND primary_status = %(status)s
# #     AND (do_not_query IS NULL OR do_not_query != 1)
# #     AND (
# #         (currentETD IS NOT NULL
# #          AND COALESCE(
# #              STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%dT%%H:%%i:%%s'),
# #              STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%d %%H:%%i:%%s')
# #          ) IS NULL)
# #         OR DATE(currentETA) = CURRENT_DATE + INTERVAL %(window)s DAY
# #     )
# # """

# SEA_SYNC_QUERY = """
#     SELECT JS_UniqueConsignRef
#     FROM cargowise_containers_new
#     WHERE JS_TransportMode = %(mode)s
#       AND primary_status = %(status)s
#       AND (do_not_query IS NULL OR do_not_query != 1)
#       AND (
#             (
#                 currentETD IS NOT NULL
#                 AND COALESCE(
#                       STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%dT%%H:%%i:%%s'),
#                       STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%d %%H:%%i:%%s')
#                     ) IS NULL
#             )
#             OR DATE(currentETA) = CURRENT_DATE + INTERVAL %(window)s DAY
#           )
# """


# # SEA_REVERSE_QUERY = """
# #     SELECT JS_UniqueConsignRef FROM cargowise_containers_new
# #     WHERE JS_TransportMode = %(mode)s AND primary_status = %(status)s
# #     AND (do_not_query IS NULL OR do_not_query != 1)
# #     AND (
# #         (currentETD IS NULL
# #          OR COALESCE(
# #              STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%dT%%H:%%i:%%s'),
# #              STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%d %%H:%%i:%%s')
# #          ) IS NOT NULL)
# #         AND (currentETA IS NULL
# #              OR DATE(currentETA) <> CURRENT_DATE + INTERVAL %(window)s DAY)
# #     )
# # """

# SEA_REVERSE_QUERY = """
#     SELECT JS_UniqueConsignRef
#     FROM cargowise_containers_new
#     WHERE JS_TransportMode = %(mode)s
#       AND primary_status = %(status)s
#       AND (do_not_query IS NULL OR do_not_query != 1)
#       AND (
#             (
#                 currentETD IS NULL
#                 OR COALESCE(
#                       STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%dT%%H:%%i:%%s'),
#                       STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%d %%H:%%i:%%s')
#                     ) IS NOT NULL
#             )
#             AND (
#                   currentETA IS NULL
#                   AND DATE(currentETA) <> CURRENT_DATE + INTERVAL %(window)s DAY
#                 )
#           )
# """


# # ------------------------------------------------------------------ #
# # Pure snapshot functions — no DB, fully testable
# # ------------------------------------------------------------------ #

# def _normalize(val: Any) -> Optional[str]:
#     """Return None for empty-ish values, otherwise the string as-is."""
#     if val is None:
#         return None
#     if isinstance(val, str) and val.strip() == "":
#         return None
#     return val


# def apply_eta_snapshot(
#     existing: Dict[str, Optional[str]],
#     new_eta: Optional[str],
# ) -> Dict[str, Optional[str]]:
#     """
#     Dual-column snapshot logic for ETA (mirrors ETD identically).

#     Rules (from new_milestones5.py lines 3152-3178):
#     - First insert (both current & updated are None): set both to new_eta.
#     - Subsequent: if new_eta differs from current, update current; keep updated
#       frozen.  If updated was still None, freeze it to the old current value.
#     - If new_eta is None/empty, do nothing.
#     """
#     current = _normalize(existing.get("currentETA"))
#     updated = _normalize(existing.get("updatedETA"))
#     new_eta = _normalize(new_eta)

#     if new_eta is None:
#         # No new value provided — leave everything as-is
#         return {"currentETA": current, "updatedETA": updated}

#     if current is None and updated is None:
#         # First insert
#         return {"currentETA": new_eta, "updatedETA": new_eta}

#     # Existing record
#     if new_eta != current:
#         if updated is None:
#             updated = current  # freeze snapshot
#         current = new_eta

#     return {"currentETA": current, "updatedETA": updated}


# def apply_actual_snapshot(
#     existing: Dict[str, Optional[str]],
#     new_value: Optional[str],
#     kind: str,
# ) -> Dict[str, Optional[str]]:
#     """
#     Dual-column snapshot logic for Actual Arrival / Actual Departure.

#     Rules (from new_milestones5.py lines 3192-3207):
#     - First insert or updated is None: set both to new_value.
#     - Subsequent: only update current when value changes; keep updated frozen.
#     - If new_value is None, do nothing.

#     kind: "Arrival" or "Departure"
#     """
#     cur_key = f"currentActual{kind}"
#     upd_key = f"updatedActual{kind}"

#     current = _normalize(existing.get(cur_key))
#     updated = _normalize(existing.get(upd_key))
#     new_value = _normalize(new_value)

#     if new_value is None:
#         return {cur_key: current, upd_key: updated}

#     if current is None and updated is None:
#         # First insert — snapshot both
#         return {cur_key: new_value, upd_key: new_value}

#     if updated is None:
#         # Snapshot missing — lock it, then update current
#         return {cur_key: new_value, upd_key: current}

#     # updated already frozen — only change current if different
#     if new_value != current:
#         current = new_value

#     return {cur_key: current, upd_key: updated}


# # ------------------------------------------------------------------ #
# # Database class
# # ------------------------------------------------------------------ #

# class Database:
#     """Pooled MySQL connection manager and query executor."""

#     # Class-level query constants
#     AIR_SYNC_QUERY = AIR_SYNC_QUERY
#     SEA_SYNC_QUERY = SEA_SYNC_QUERY
#     SEA_REVERSE_QUERY = SEA_REVERSE_QUERY

#     def __init__(self, settings):
#         self._settings = settings
#         self._pool = PooledDB(
#             creator=pymysql,
#             maxconnections=settings.DB_POOL_SIZE,
#             mincached=1,
#             maxcached=settings.DB_POOL_SIZE,
#             blocking=True,           # wait for a free connection instead of failing
#             maxusage=100,            # recycle connections after 100 uses (prevents stale conns to RDS)
#             host=settings.DB_HOST,
#             user=settings.DB_USER,
#             password=settings.DB_PASSWORD,
#             database=settings.DB_NAME,
#             charset="utf8mb4",
#             cursorclass=pymysql.cursors.DictCursor,
#             autocommit=True,
#             connect_timeout=30,      # 30s timeout for establishing new connections to RDS
#             read_timeout=60,         # 60s timeout for read operations
#             write_timeout=60,        # 60s timeout for write operations
#         )

#     # ---- connection context manager -------------------------------- #

#     @contextmanager
#     def get_connection(self):
#         """Yield a pooled connection; return it to the pool on exit."""
#         print("⏳ Trying to get DB connection...")
#         conn = self._pool.connection()
#         print("✅ DB connection successful")
#         try:
#             yield conn
#         finally:
#             conn.close()

#     # ================================================================ #
#     # Shipment operations
#     # ================================================================ #

#     def get_existing_shipment_ids(self) -> Set[str]:
#         """Return set of all JS_UniqueConsignRef values."""
#         conn = self._pool.connection()
#         try:
#             with conn.cursor() as cur:
#                 cur.execute(
#                     "SELECT JS_UniqueConsignRef FROM cargowise_containers_new"
#                 )
#                 rows = cur.fetchall()
#                 return {
#                     r["JS_UniqueConsignRef"]
#                     for r in rows
#                     if r.get("JS_UniqueConsignRef")
#                 }
#         finally:
#             conn.close()

#     def fetch_eta_etd(self, shipment_id: str) -> Optional[Dict]:
#         """Return {currentETA, updatedETA, currentETD, updatedETD} or None."""
#         conn = self._pool.connection()
#         try:
#             with conn.cursor() as cur:
#                 cur.execute(
#                     """
#                     SELECT currentETA, updatedETA, currentETD, updatedETD
#                     FROM cargowise_containers_new
#                     WHERE JS_UniqueConsignRef = %s
#                     LIMIT 1
#                     """,
#                     (shipment_id,),
#                 )
#                 row = cur.fetchone()
#                 return row if row else None
#         finally:
#             conn.close()

#     def fetch_actuals(self, shipment_id: str) -> Optional[Dict]:
#         """Return {currentActualArrival, updatedActualArrival, ...} or None."""
#         conn = self._pool.connection()
#         try:
#             with conn.cursor() as cur:
#                 cur.execute(
#                     """
#                     SELECT currentActualArrival, updatedActualArrival,
#                            currentActualDeparture, updatedActualDeparture
#                     FROM cargowise_containers_new
#                     WHERE JS_UniqueConsignRef = %s
#                     LIMIT 1
#                     """,
#                     (shipment_id,),
#                 )
#                 row = cur.fetchone()
#                 return row if row else None
#         finally:
#             conn.close()

#     def upsert_shipment(self, record: Dict) -> None:
#         """
#         Check if shipment exists by JS_UniqueConsignRef.
#         UPDATE if it does, INSERT if it does not.
#         """
#         shipment_id = record.get("JS_UniqueConsignRef")
#         columns = list(record.keys())

#         conn = self._pool.connection()
#         try:
#             with conn.cursor() as cur:
#                 cur.execute(
#                     """
#                     SELECT COUNT(*) AS cnt
#                     FROM cargowise_containers_new
#                     WHERE JS_UniqueConsignRef = %s
#                     """,
#                     (shipment_id,),
#                 )
#                 exists = cur.fetchone()["cnt"] > 0

#                 if exists:
#                     update_cols = [c for c in columns if c != "JS_UniqueConsignRef"]
#                     set_clause = ", ".join(f"{c} = %s" for c in update_cols)
#                     values = [record.get(c) for c in update_cols] + [shipment_id]
#                     cur.execute(
#                         f"UPDATE cargowise_containers_new SET {set_clause} "
#                         f"WHERE JS_UniqueConsignRef = %s",
#                         values,
#                     )
#                 else:
#                     placeholders = ", ".join(["%s"] * len(columns))
#                     col_names = ", ".join(columns)
#                     values = [record.get(c) for c in columns]
#                     cur.execute(
#                         f"INSERT INTO cargowise_containers_new ({col_names}) "
#                         f"VALUES ({placeholders})",
#                         values,
#                     )
#             conn.commit()
#         finally:
#             conn.close()

#     def get_active_shipments(
#         self,
#         mode: str,
#         status: str,
#         extra_where: str = "",
#         params: Optional[Dict] = None,
#     ) -> List[str]:
#         """Return list of JS_UniqueConsignRef matching mode + status + extras."""
#         print(extra_where , " : extra wher")
#         sql = (
#             "SELECT JS_UniqueConsignRef FROM cargowise_containers_new "
#             "WHERE JS_TransportMode = %(mode)s AND primary_status = %(status)s "
#             "AND (do_not_query IS NULL OR do_not_query != 1)"
#         )
#         if extra_where:
#             sql += f" AND ({extra_where})"
#             logger.info(f"SQL ashish: {sql}")

        
        
#         query_params: Dict = {"mode": mode, "status": status}
        
     
#         if params:
#             query_params.update(params)

#         conn = self._pool.connection()
        
        
#         try:
#             with conn.cursor() as cur:
#                 cur.execute(sql, query_params)
#                 rows = cur.fetchall()
#                 return [r["JS_UniqueConsignRef"] for r in rows]
#         finally:
#             conn.close()
            
            
            

#     def mark_do_not_query(self, shipment_id: str) -> None:
#         """Set do_not_query = 1 for a shipment."""
#         conn = self._pool.connection()
#         try:
#             with conn.cursor() as cur:
#                 cur.execute(
#                     "UPDATE cargowise_containers_new "
#                     "SET do_not_query = 1 WHERE JS_UniqueConsignRef = %s",
#                     (shipment_id,),
#                 )
#             conn.commit()
#         finally:
#             conn.close()

#     # ================================================================ #
#     # Job tracking
#     # ================================================================ #

#     def create_job_run(self, job_type: str) -> str:
#         """Insert a new job_runs row and return its UUID."""
#         job_id = str(uuid.uuid4())
#         conn = self._pool.connection()
#         try:
#             with conn.cursor() as cur:
#                 cur.execute(
#                     "INSERT INTO job_runs (id, job_type, status) "
#                     "VALUES (%s, %s, 'running')",
#                     (job_id, job_type),
#                 )
#             conn.commit()
#         finally:
#             conn.close()
#         return job_id

#     def complete_job_run(
#         self,
#         job_run_id: str,
#         processed: int,
#         failed: int,
#         error_summary: Optional[str] = None,
#     ) -> None:
#         """Mark a job_run as completed (or failed if failed > 0)."""
#         status = "failed" if failed > 0 and processed == 0 else "completed"
#         conn = self._pool.connection()
#         try:
#             with conn.cursor() as cur:
#                 cur.execute(
#                     "UPDATE job_runs "
#                     "SET status = %s, processed_count = %s, failed_count = %s, "
#                     "    error_summary = %s, completed_at = NOW() "
#                     "WHERE id = %s",
#                     (status, processed, failed, error_summary, job_run_id),
#                 )
#             conn.commit()
#         finally:
#             conn.close()

#     def track_shipment(
#         self,
#         shipment_id: str,
#         job_run_id: str,
#         job_type: str,
#         status: str = "pending",
#     ) -> None:
#         """Insert a single shipment_tracking row."""
#         conn = self._pool.connection()
#         try:
#             with conn.cursor() as cur:
#                 cur.execute(
#                     "INSERT INTO shipment_tracking "
#                     "(shipment_id, job_run_id, job_type, status) "
#                     "VALUES (%s, %s, %s, %s)",
#                     (shipment_id, job_run_id, job_type, status),
#                 )
#             conn.commit()
#         finally:
#             conn.close()

#     def bulk_track_shipments(
#         self,
#         shipment_ids: List[str],
#         job_run_id: str,
#         job_type: str,
#     ) -> None:
#         """Bulk-insert shipment_tracking rows for a list of shipment IDs."""
#         if not shipment_ids:
#             return
#         conn = self._pool.connection()
#         try:
#             with conn.cursor() as cur:
#                 cur.executemany(
#                     "INSERT INTO shipment_tracking "
#                     "(shipment_id, job_run_id, job_type, status) "
#                     "VALUES (%s, %s, %s, 'pending')",
#                     [(sid, job_run_id, job_type) for sid in shipment_ids],
#                 )
#             conn.commit()
#         finally:
#             conn.close()

#     def update_tracking(
#         self,
#         shipment_id: str,
#         job_run_id: str,
#         status: str,
#         error: Optional[str] = None,
#         retry_count: Optional[int] = None,
#     ) -> None:
#         """Update shipment_tracking row status (and optionally error / retry)."""
#         parts = ["status = %s", "error_message = %s"]
#         values: list = [status, error]

#         if status == "in_progress":
#             parts.append("started_at = NOW()")
#         if status in ("completed", "failed"):
#             parts.append("completed_at = NOW()")
#         if retry_count is not None:
#             parts.append("retry_count = %s")
#             values.append(retry_count)

#         values.extend([shipment_id, job_run_id])

#         conn = self._pool.connection()
#         try:
#             with conn.cursor() as cur:
#                 cur.execute(
#                     f"UPDATE shipment_tracking SET {', '.join(parts)} "
#                     f"WHERE shipment_id = %s AND job_run_id = %s",
#                     values,
#                 )
#             conn.commit()
#         finally:
#             conn.close()

#     def get_interrupted(self) -> List[Dict]:
#         """
#         Return shipments that were in_progress or pending when a job_run
#         was still 'running' (i.e. interrupted).
#         """
#         conn = self._pool.connection()
#         try:
#             with conn.cursor() as cur:
#                 cur.execute(
#                     """
#                     SELECT st.shipment_id, st.job_run_id, st.job_type,
#                            st.retry_count, st.lifetime_retry_count
#                     FROM shipment_tracking st
#                     JOIN job_runs jr ON jr.id = st.job_run_id
#                     WHERE jr.status = 'running'
#                       AND st.status IN ('in_progress', 'pending')
#                     """
#                 )
#                 return cur.fetchall()
#         finally:
#             conn.close()

#     def get_failed_shipments(self) -> List[Dict]:
#         """
#         Return shipments that failed in the last 24 hours and whose
#         lifetime_retry_count is below the threshold.
#         """
#         threshold = self._settings.SHIPMENT_MAX_LIFETIME_RETRIES
#         conn = self._pool.connection()
#         try:
#             with conn.cursor() as cur:
#                 cur.execute(
#                     """
#                     SELECT shipment_id, job_run_id, job_type,
#                            retry_count, lifetime_retry_count, error_message
#                     FROM shipment_tracking
#                     WHERE status = 'failed'
#                       AND completed_at >= NOW() - INTERVAL 24 HOUR
#                       AND lifetime_retry_count < %s
#                     """,
#                     (threshold,),
#                 )
#                 return cur.fetchall()
#         finally:
#             conn.close()

#     def get_dead_letter_shipments(self) -> List[Dict]:
#         """
#         Return shipments whose lifetime_retry_count has reached
#         the max threshold — candidates for dead-letter alerting.
#         """
#         threshold = self._settings.SHIPMENT_MAX_LIFETIME_RETRIES
#         conn = self._pool.connection()
#         try:
#             with conn.cursor() as cur:
#                 cur.execute(
#                     """
#                     SELECT shipment_id, job_run_id, job_type,
#                            lifetime_retry_count, error_message
#                     FROM shipment_tracking
#                     WHERE status = 'failed'
#                       AND lifetime_retry_count >= %s
#                     """,
#                     (threshold,),
#                 )
#                 return cur.fetchall()
#         finally:
#             conn.close()

#     def was_processed_in_cycle(
#         self, shipment_id: str, parent_job_run_id: str
#     ) -> bool:
#         """Check if shipment was already completed in a given job run."""
#         conn = self._pool.connection()
#         try:
#             with conn.cursor() as cur:
#                 cur.execute(
#                     """
#                     SELECT COUNT(*) AS cnt FROM shipment_tracking
#                     WHERE shipment_id = %s
#                       AND job_run_id = %s
#                       AND status = 'completed'
#                     """,
#                     (shipment_id, parent_job_run_id),
#                 )
#                 return cur.fetchone()["cnt"] > 0
#         finally:
#             conn.close()

#     # ================================================================ #
#     # Excel imports
#     # ================================================================ #

#     def save_excel_metadata(self, metadata: Dict) -> int:
#         """Insert excel_imports row and return the auto-increment id."""
#         conn = self._pool.connection()
#         try:
#             with conn.cursor() as cur:
#                 cur.execute(
#                     """
#                     INSERT INTO excel_imports
#                         (filename, sftp_path, file_size_bytes, file_modified_at,
#                          row_count, new_shipment_count, job_run_id, status,
#                          local_path, s3_archive_path)
#                     VALUES
#                         (%(filename)s, %(sftp_path)s, %(file_size_bytes)s,
#                          %(file_modified_at)s, %(row_count)s,
#                          %(new_shipment_count)s, %(job_run_id)s,
#                          %(status)s, %(local_path)s, %(s3_archive_path)s)
#                     """,
#                     {
#                         "filename": metadata.get("filename"),
#                         "sftp_path": metadata.get("sftp_path"),
#                         "file_size_bytes": metadata.get("file_size_bytes"),
#                         "file_modified_at": metadata.get("file_modified_at"),
#                         "row_count": metadata.get("row_count", 0),
#                         "new_shipment_count": metadata.get("new_shipment_count", 0),
#                         "job_run_id": metadata.get("job_run_id"),
#                         "status": metadata.get("status", "downloaded"),
#                         "local_path": metadata.get("local_path"),
#                         "s3_archive_path": metadata.get("s3_archive_path"),
#                     },
#                 )
#                 import_id = cur.lastrowid
#             conn.commit()
#             return import_id
#         finally:
#             conn.close()

#     def save_excel_rows(self, import_id: int, rows: List[Dict], batch_size: int = 500) -> None:
#         """Bulk-insert excel_import_rows in batches to avoid timeout on remote DB."""
#         if not rows:
#             return
#         conn = self._pool.connection()
#         try:
#             with conn.cursor() as cur:
#                 data = [
#                     (
#                         import_id,
#                         r.get("shipment_id"),
#                         r.get("raw_row_data"),
#                         r.get("is_new", False),
#                     )
#                     for r in rows
#                 ]
#                 for i in range(0, len(data), batch_size):
#                     batch = data[i : i + batch_size]
#                     cur.executemany(
#                         """
#                         INSERT INTO excel_import_rows
#                             (excel_import_id, shipment_id, raw_row_data, is_new)
#                         VALUES (%s, %s, %s, %s)
#                         """,
#                         batch,
#                     )
#                     conn.commit()
#         finally:
#             conn.close()

#     # ================================================================ #
#     # Maintenance
#     # ================================================================ #

#     def purge_old_tracking(self, retention_days: int) -> None:
#         """
#         Delete job_runs older than retention_days.
#         CASCADE handles shipment_tracking, excel_imports, excel_import_rows.
#         """
#         conn = self._pool.connection()
#         try:
#             with conn.cursor() as cur:
#                 cur.execute(
#                     "DELETE FROM job_runs "
#                     "WHERE started_at < NOW() - INTERVAL %s DAY",
#                     (retention_days,),
#                 )
#             conn.commit()
#         finally:
#             conn.close()

"""
Database layer for the pipeline.

Provides:
- Connection pooling via DBUtils.PooledDB + pymysql
- Pure snapshot functions (apply_eta_snapshot, apply_actual_snapshot)
- Shipment CRUD operations against cargowise_containers_new
- Job-run tracking (job_runs, shipment_tracking tables)
- Excel import metadata persistence
"""

import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Set

from dotenv.main import logger
import pymysql
from dbutils.pooled_db import PooledDB


# ------------------------------------------------------------------ #
# SQL query templates (class constants defined below the class)
# ------------------------------------------------------------------ #

AIR_SYNC_QUERY = """
    # SELECT JS_UniqueConsignRef FROM cargowise_containers_new
    # WHERE JS_TransportMode = %(mode)s AND primary_status = %(status)s
    # AND (do_not_query IS NULL OR do_not_query != 1)

"""

# SEA_SYNC_QUERY = """
#     SELECT JS_UniqueConsignRef FROM cargowise_containers_new
#     WHERE JS_TransportMode = %(mode)s AND primary_status = %(status)s
#     AND (do_not_query IS NULL OR do_not_query != 1)
#     AND (
#         (currentETD IS NOT NULL
#          AND COALESCE(
#              STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%dT%%H:%%i:%%s'),
#              STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%d %%H:%%i:%%s')
#          ) IS NULL)
#         OR DATE(currentETA) = CURRENT_DATE + INTERVAL %(window)s DAY
#     )
# """

SEA_SYNC_QUERY = """
    SELECT JS_UniqueConsignRef
    FROM cargowise_containers_new
    WHERE JS_TransportMode = %(mode)s
      AND primary_status = %(status)s
      AND (do_not_query IS NULL OR do_not_query != 1)
      AND (
            (
                currentETD IS NOT NULL
                AND COALESCE(
                      STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%dT%%H:%%i:%%s'),
                      STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%d %%H:%%i:%%s')
                    ) IS NULL
            )
            OR DATE(currentETA) = CURRENT_DATE + INTERVAL %(window)s DAY
          )
"""


# SEA_REVERSE_QUERY = """
#     SELECT JS_UniqueConsignRef FROM cargowise_containers_new
#     WHERE JS_TransportMode = %(mode)s AND primary_status = %(status)s
#     AND (do_not_query IS NULL OR do_not_query != 1)
#     AND (
#         (currentETD IS NULL
#          OR COALESCE(
#              STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%dT%%H:%%i:%%s'),
#              STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%d %%H:%%i:%%s')
#          ) IS NOT NULL)
#         AND (currentETA IS NULL
#              OR DATE(currentETA) <> CURRENT_DATE + INTERVAL %(window)s DAY)
#     )
# """

SEA_REVERSE_QUERY = """
    SELECT JS_UniqueConsignRef
    FROM cargowise_containers_new
    WHERE JS_TransportMode = %(mode)s
      AND primary_status = %(status)s
      AND (do_not_query IS NULL OR do_not_query != 1)
      AND (
            (
                currentETD IS NULL
                OR COALESCE(
                      STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%dT%%H:%%i:%%s'),
                      STR_TO_DATE(currentActualDeparture, '%%Y-%%m-%%d %%H:%%i:%%s')
                    ) IS NOT NULL
            )
            AND (
                  currentETA IS NULL
                  AND DATE(currentETA) <> CURRENT_DATE + INTERVAL %(window)s DAY
                )
          )
"""


# ------------------------------------------------------------------ #
# Pure snapshot functions — no DB, fully testable
# ------------------------------------------------------------------ #



def _normalize(val: Any) -> Optional[str]:
    """Return None for empty-ish values, otherwise the string as-is."""
    if val is None:
        return None
    if isinstance(val, str) and val.strip() == "":
        return None
    return val


def apply_eta_snapshot(
    existing: Dict[str, Optional[str]],
    new_eta: Optional[str],
) -> Dict[str, Optional[str]]:
    """
    Dual-column snapshot logic for ETA (mirrors ETD identically).

    Rules (from new_milestones5.py lines 3152-3178):
    - First insert (both current & updated are None): set both to new_eta.
    - Subsequent: if new_eta differs from current, update current; keep updated
      frozen.  If updated was still None, freeze it to the old current value.
    - If new_eta is None/empty, do nothing.
    """
    current = _normalize(existing.get("currentETA"))
    updated = _normalize(existing.get("updatedETA"))
    new_eta = _normalize(new_eta)

    if new_eta is None:
        # No new value provided — leave everything as-is
        return {"currentETA": current, "updatedETA": updated}

    if current is None and updated is None:
        # First insert
        return {"currentETA": new_eta, "updatedETA": new_eta}

    # Existing record
    if new_eta != current:
        if updated is None:
            updated = current  # freeze snapshot
        current = new_eta

    return {"currentETA": current, "updatedETA": updated}


def apply_actual_snapshot(
    existing: Dict[str, Optional[str]],
    new_value: Optional[str],
    kind: str,
) -> Dict[str, Optional[str]]:
    """
    Dual-column snapshot logic for Actual Arrival / Actual Departure.

    Rules (from new_milestones5.py lines 3192-3207):
    - First insert or updated is None: set both to new_value.
    - Subsequent: only update current when value changes; keep updated frozen.
    - If new_value is None, do nothing.

    kind: "Arrival" or "Departure"
    """
    cur_key = f"currentActual{kind}"
    upd_key = f"updatedActual{kind}"

    current = _normalize(existing.get(cur_key))
    updated = _normalize(existing.get(upd_key))
    new_value = _normalize(new_value)

    if new_value is None:
        return {cur_key: current, upd_key: updated}

    if current is None and updated is None:
        # First insert — snapshot both
        return {cur_key: new_value, upd_key: new_value}

    if updated is None:
        # Snapshot missing — lock it, then update current
        return {cur_key: new_value, upd_key: current}

    # updated already frozen — only change current if different
    if new_value != current:
        current = new_value

    return {cur_key: current, upd_key: updated}


# ------------------------------------------------------------------ #
# Database class
# ------------------------------------------------------------------ #

class Database:
    """Pooled MySQL connection manager and query executor."""

    # Class-level query constants
    AIR_SYNC_QUERY = AIR_SYNC_QUERY
    SEA_SYNC_QUERY = SEA_SYNC_QUERY
    SEA_REVERSE_QUERY = SEA_REVERSE_QUERY

    def __init__(self, settings):
        self._settings = settings
        self._pool = PooledDB(
            creator=pymysql,
            maxconnections=settings.DB_POOL_SIZE,
            mincached=1,
            maxcached=settings.DB_POOL_SIZE,
            blocking=True,           # wait for a free connection instead of failing
            maxusage=100,            # recycle connections after 100 uses (prevents stale conns to RDS)
            host=settings.DB_HOST,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database=settings.DB_NAME,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
            connect_timeout=30,      # 30s timeout for establishing new connections to RDS
            read_timeout=60,         # 60s timeout for read operations
            write_timeout=60,        # 60s timeout for write operations
        )

    # ---- connection context manager -------------------------------- #

    @contextmanager
    def get_connection(self):
        """Yield a pooled connection; return it to the pool on exit."""
        print("⏳ Trying to get DB connection...")
        conn = self._pool.connection()
        print("✅ DB connection successful")
        try:
            yield conn
        finally:
            conn.close()

    # ================================================================ #
    # Shipment operations
    # ================================================================ #
    
    def get_excel_row(self, shipment_id):
        conn = self._pool.connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT raw_row_data
                    FROM excel_import_rows
                    WHERE shipment_id = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (shipment_id,),
                )
                return cur.fetchone()
        finally:
            conn.close()

    def get_existing_shipment_ids(self) -> Set[str]:
        """Return set of all JS_UniqueConsignRef values."""
        conn = self._pool.connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT JS_UniqueConsignRef FROM cargowise_containers_new"
                )
                rows = cur.fetchall()
                return {
                    r["JS_UniqueConsignRef"]
                    for r in rows
                    if r.get("JS_UniqueConsignRef")
                }
        finally:
            conn.close()

    def fetch_eta_etd(self, shipment_id: str) -> Optional[Dict]:
        """Return {currentETA, updatedETA, currentETD, updatedETD} or None."""
        conn = self._pool.connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT currentETA, updatedETA, currentETD, updatedETD
                    FROM cargowise_containers_new
                    WHERE JS_UniqueConsignRef = %s
                    LIMIT 1
                    """,
                    (shipment_id,),
                )
                row = cur.fetchone()
                return row if row else None
        finally:
            conn.close()

    def fetch_actuals(self, shipment_id: str) -> Optional[Dict]:
        """Return {currentActualArrival, updatedActualArrival, ...} or None."""
        conn = self._pool.connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT currentActualArrival, updatedActualArrival,
                           currentActualDeparture, updatedActualDeparture
                    FROM cargowise_containers_new
                    WHERE JS_UniqueConsignRef = %s
                    LIMIT 1
                    """,
                    (shipment_id,),
                )
                row = cur.fetchone()
                return row if row else None
        finally:
            conn.close()

    def upsert_shipment(self, record: Dict) -> None:
        """
        Check if shipment exists by JS_UniqueConsignRef.
        UPDATE if it does, INSERT if it does not.
        """
        shipment_id = record.get("JS_UniqueConsignRef")
        columns = list(record.keys())

        conn = self._pool.connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM cargowise_containers_new
                    WHERE JS_UniqueConsignRef = %s
                    """,
                    (shipment_id,),
                )
                exists = cur.fetchone()["cnt"] > 0

                if exists:
                    update_cols = [c for c in columns if c != "JS_UniqueConsignRef"]
                    set_clause = ", ".join(f"{c} = %s" for c in update_cols)
                    values = [record.get(c) for c in update_cols] + [shipment_id]
                    cur.execute(
                        f"UPDATE cargowise_containers_new SET {set_clause} "
                        f"WHERE JS_UniqueConsignRef = %s",
                        values,
                    )
                else:
                    placeholders = ", ".join(["%s"] * len(columns))
                    col_names = ", ".join(columns)
                    values = [record.get(c) for c in columns]
                    cur.execute(
                        f"INSERT INTO cargowise_containers_new ({col_names}) "
                        f"VALUES ({placeholders})",
                        values,
                    )
            conn.commit()
        finally:
            conn.close()

    def get_active_shipments(
        self,
        mode: str,
        status: str,
        extra_where: str = "",
        params: Optional[Dict] = None,
    ) -> List[str]:
        """Return list of JS_UniqueConsignRef matching mode + status + extras."""
        print(extra_where , " : extra wher")
        sql = (
            "SELECT JS_UniqueConsignRef FROM cargowise_containers_new "
            "WHERE JS_TransportMode = %(mode)s AND primary_status = %(status)s "
            "AND (do_not_query IS NULL OR do_not_query != 1) AND show_shipment = 1"
        )
        if extra_where:
            sql += f" AND ({extra_where})"
            logger.info(f"SQL ashish: {sql}")

        
        
        query_params: Dict = {"mode": mode, "status": status}
        
     
        if params:
            query_params.update(params)

        conn = self._pool.connection()
        
        
        try:
            with conn.cursor() as cur:
                cur.execute(sql, query_params)
                rows = cur.fetchall()
                return [r["JS_UniqueConsignRef"] for r in rows]
        finally:
            conn.close()
            
            
            

    def mark_do_not_query(self, shipment_id: str) -> None:
        """Set do_not_query = 1 for a shipment."""
        conn = self._pool.connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE cargowise_containers_new "
                    "SET do_not_query = 1 WHERE JS_UniqueConsignRef = %s",
                    (shipment_id,),
                )
            conn.commit()
        finally:
            conn.close()

    # ================================================================ #
    # Job tracking
    # ================================================================ #

    def create_job_run(self, job_type: str) -> str:
        """Insert a new job_runs row and return its UUID."""
        job_id = str(uuid.uuid4())
        conn = self._pool.connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO job_runs (id, job_type, status) "
                    "VALUES (%s, %s, 'running')",
                    (job_id, job_type),
                )
            conn.commit()
        finally:
            conn.close()
        return job_id

    def complete_job_run(
        self,
        job_run_id: str,
        processed: int,
        failed: int,
        error_summary: Optional[str] = None,
    ) -> None:
        """Mark a job_run as completed (or failed if failed > 0)."""
        status = "failed" if failed > 0 and processed == 0 else "completed"
        conn = self._pool.connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE job_runs "
                    "SET status = %s, processed_count = %s, failed_count = %s, "
                    "    error_summary = %s, completed_at = NOW() "
                    "WHERE id = %s",
                    (status, processed, failed, error_summary, job_run_id),
                )
            conn.commit()
        finally:
            conn.close()

    def track_shipment(
        self,
        shipment_id: str,
        job_run_id: str,
        job_type: str,
        status: str = "pending",
    ) -> None:
        """Insert a single shipment_tracking row."""
        conn = self._pool.connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO shipment_tracking "
                    "(shipment_id, job_run_id, job_type, status) "
                    "VALUES (%s, %s, %s, %s)",
                    (shipment_id, job_run_id, job_type, status),
                )
            conn.commit()
        finally:
            conn.close()

    def bulk_track_shipments(
        self,
        shipment_ids: List[str],
        job_run_id: str,
        job_type: str,
        batch_size: int = 500,
    ) -> None:
        """Bulk-insert shipment_tracking rows using multi-value INSERT for speed."""
        if not shipment_ids:
            return
        conn = self._pool.connection()
        try:
            with conn.cursor() as cur:
                for i in range(0, len(shipment_ids), batch_size):
                    batch = shipment_ids[i : i + batch_size]
                    # Build single INSERT with multiple VALUES — one network round trip
                    values_list = ", ".join(
                        cur.mogrify("(%s, %s, %s, 'pending')", (sid, job_run_id, job_type))

                        for sid in batch
                    )
                    cur.execute(
                        f"INSERT INTO shipment_tracking "
                        f"(shipment_id, job_run_id, job_type, status) VALUES {values_list}"
                    )
                    conn.commit()
                    print(f"  📦 Tracking batch {i // batch_size + 1}: {len(batch)} rows inserted", flush=True)
        finally:
            conn.close()

    def update_tracking(
        self,
        shipment_id: str,
        job_run_id: str,
        status: str,
        error: Optional[str] = None,
        retry_count: Optional[int] = None,
    ) -> None:
        """Update shipment_tracking row status (and optionally error / retry)."""
        parts = ["status = %s", "error_message = %s"]
        values: list = [status, error]

        if status == "in_progress":
            parts.append("started_at = NOW()")
        if status in ("completed", "failed"):
            parts.append("completed_at = NOW()")
        if retry_count is not None:
            parts.append("retry_count = %s")
            values.append(retry_count)

        values.extend([shipment_id, job_run_id])

        conn = self._pool.connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE shipment_tracking SET {', '.join(parts)} "
                    f"WHERE shipment_id = %s AND job_run_id = %s",
                    values,
                )
            conn.commit()
        finally:
            conn.close()

    def get_interrupted(self) -> List[Dict]:
        """
        Return shipments that were in_progress or pending when a job_run
        was still 'running' (i.e. interrupted).
        """
        conn = self._pool.connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT st.shipment_id, st.job_run_id, st.job_type,
                           st.retry_count, st.lifetime_retry_count
                    FROM shipment_tracking st
                    JOIN job_runs jr ON jr.id = st.job_run_id
                    WHERE jr.status = 'running'
                      AND st.status IN ('in_progress', 'pending')
                    """
                )
                return cur.fetchall()
        finally:
            conn.close()

    def get_failed_shipments(self) -> List[Dict]:
        """
        Return shipments that failed in the last 24 hours and whose
        lifetime_retry_count is below the threshold.
        """
        threshold = self._settings.SHIPMENT_MAX_LIFETIME_RETRIES
        conn = self._pool.connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT shipment_id, job_run_id, job_type,
                           retry_count, lifetime_retry_count, error_message
                    FROM shipment_tracking
                    WHERE status = 'failed'
                      AND completed_at >= NOW() - INTERVAL 24 HOUR
                      AND lifetime_retry_count < %s
                    """,
                    (threshold,),
                )
                return cur.fetchall()
        finally:
            conn.close()

    def get_dead_letter_shipments(self) -> List[Dict]:
        """
        Return shipments whose lifetime_retry_count has reached
        the max threshold — candidates for dead-letter alerting.
        """
        threshold = self._settings.SHIPMENT_MAX_LIFETIME_RETRIES
        conn = self._pool.connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT shipment_id, job_run_id, job_type,
                           lifetime_retry_count, error_message
                    FROM shipment_tracking
                    WHERE status = 'failed'
                      AND lifetime_retry_count >= %s
                    """,
                    (threshold,),
                )
                return cur.fetchall()
        finally:
            conn.close()

    def was_processed_in_cycle(
        self, shipment_id: str, parent_job_run_id: str
    ) -> bool:
        """Check if shipment was already completed in a given job run."""
        conn = self._pool.connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt FROM shipment_tracking
                    WHERE shipment_id = %s
                      AND job_run_id = %s
                      AND status = 'completed'
                    """,
                    (shipment_id, parent_job_run_id),
                )
                return cur.fetchone()["cnt"] > 0
        finally:
            conn.close()

    # ================================================================ #
    # Excel imports
    # ================================================================ #

    def save_excel_metadata(self, metadata: Dict) -> int:
        """Insert excel_imports row and return the auto-increment id."""
        conn = self._pool.connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO excel_imports
                        (filename, sftp_path, file_size_bytes, file_modified_at,
                         row_count, new_shipment_count, job_run_id, status,
                         local_path, s3_archive_path)
                    VALUES
                        (%(filename)s, %(sftp_path)s, %(file_size_bytes)s,
                         %(file_modified_at)s, %(row_count)s,
                         %(new_shipment_count)s, %(job_run_id)s,
                         %(status)s, %(local_path)s, %(s3_archive_path)s)
                    """,
                    {
                        "filename": metadata.get("filename"),
                        "sftp_path": metadata.get("sftp_path"),
                        "file_size_bytes": metadata.get("file_size_bytes"),
                        "file_modified_at": metadata.get("file_modified_at"),
                        "row_count": metadata.get("row_count", 0),
                        "new_shipment_count": metadata.get("new_shipment_count", 0),
                        "job_run_id": metadata.get("job_run_id"),
                        "status": metadata.get("status", "downloaded"),
                        "local_path": metadata.get("local_path"),
                        "s3_archive_path": metadata.get("s3_archive_path"),
                    },
                )
                import_id = cur.lastrowid
            conn.commit()
            return import_id
        finally:
            conn.close()

    def save_excel_rows(self, import_id: int, rows: List[Dict], batch_size: int = 500) -> None:
        """Bulk-insert excel_import_rows using multi-value INSERT for speed."""
        if not rows:
            return
        conn = self._pool.connection()
        try:
            with conn.cursor() as cur:
                data = [
                    (
                        import_id,
                        r.get("shipment_id"),
                        r.get("raw_row_data"),
                        r.get("is_new", False),
                    )
                    for r in rows
                ]
                for i in range(0, len(data), batch_size):
                    batch = data[i : i + batch_size]
                    values_list = ", ".join(
                        cur.mogrify("(%s, %s, %s, %s)", row)
                        for row in batch
                    )
                    cur.execute(
                        f"INSERT INTO excel_import_rows "
                        f"(excel_import_id, shipment_id, raw_row_data, is_new) VALUES {values_list}"
                    )
                    conn.commit()
                    print(f"  📦 Excel rows batch {i // batch_size + 1}: {len(batch)} rows inserted", flush=True)
        finally:
            conn.close()

    # ================================================================ #
    # Maintenance
    # ================================================================ #

    def purge_old_tracking(self, retention_days: int) -> None:
        """
        Delete job_runs older than retention_days.
        CASCADE handles shipment_tracking, excel_imports, excel_import_rows.
        """
        conn = self._pool.connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM job_runs "
                    "WHERE started_at < NOW() - INTERVAL %s DAY",
                    (retention_days,),
                )
            conn.commit()
        finally:
            conn.close()