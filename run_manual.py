# #!/usr/bin/env python3
# """
# Manual job runner — test any job without the scheduler.

# Usage:
#     python3 run_manual.py download        # SFTP download + store rows in DB only (no CW sync)
#     python3 run_manual.py ingest          # Excel ingest + AIR/SEA sync chain
#     python3 run_manual.py downloadandingest # Download + ingest in one step (
#     python3 run_manual.py air             # AIR sync only
#     python3 run_manual.py sea             # SEA sync (critical window) only
#     python3 run_manual.py reverse         # SEA reverse (midnight job)
#     python3 run_manual.py retry           # Nightly retry (failed shipments)
#     python3 run_manual.py archive         # Archive old files to S3 + purge tracking
#     python3 run_manual.py all             # Full cycle: ingest → air → sea → reverse
# """



# import sys
# from pipeline.config import Settings
# from pipeline.db import Database
# from pipeline.cargowise import CargoWiseClient
# from pipeline.notifications import EmailNotifier
# from pipeline.log_setup import setup_logging
# import os
# from dotenv import load_dotenv


# env = os.getenv("ENV")


# def main():
#     if len(sys.argv) < 2:
#         print(__doc__)
#         sys.exit(1)

#     job = sys.argv[1].lower()

#     settings = Settings()
#     setup_logging(settings)
#     db = Database(settings)
#     cw = CargoWiseClient(settings)
#     notifier = EmailNotifier(settings)

#     if job == "download":
#         from pipeline.jobs.excel_ingest import run_download_only
#         job_run_id = run_download_only(db, settings)
#         print(f"Excel download + DB populate complete. Job run: {job_run_id}")

#     elif job == "ingest":
#         from pipeline.jobs.excel_ingest import run
#         job_run_id = run(db, cw, notifier, settings)
#         print(f"Excel ingest complete. Job run: {job_run_id}")

#         # Chain AIR + SEA sync
#         from pipeline.jobs.sync_air import run as run_air
#         from pipeline.jobs.sync_sea import run_sync
#         from pipeline.jobs.sync_sea import run_reverse
#         print("Triggering AIR sync...")
#         # run_air(db, cw, notifier, settings, parent_job_run_id=job_run_id)
#         run_air(db, cw, notifier, settings)
#         print("Triggering SEA sync...")
#         # run_sync(db, cw, notifier, settings, parent_job_run_id=job_run_id)
#         run_sync(db, cw, notifier, settings)
#         print("Triggering Reverse sync...")
#         run_reverse(db, cw, notifier, settings)

#     elif job == "downloadandingest":
#         # Step 1: SFTP download + DB populate
#         from pipeline.jobs.excel_ingest import run_download_only
#         print("=== SFTP Download ===")
#         download_run_id = run_download_only(db, settings)
#         print(f"Excel download + DB populate complete. Job run: {download_run_id}")
 
#         # Step 2: Excel ingest (CargoWise sync for the rows just downloaded)
#         from pipeline.jobs.excel_ingest import run as run_ingest
#         print("=== Excel Ingest ===")
#         job_run_id = run_ingest(db, cw, notifier, settings)
#         print(f"Excel ingest complete. Job run: {job_run_id}")
 
#         print("Download + ingest complete.")
    
#     elif job == "air":
#         from pipeline.jobs.sync_air import run
#         run(db, cw, notifier, settings)
#         print("AIR sync complete.")

#     elif job == "sea":
#         from pipeline.jobs.sync_sea import run_sync
#         run_sync(db, cw, notifier, settings)
#         print("SEA sync complete.")

#     elif job == "reverse":
#         from pipeline.jobs.sync_sea import run_reverse
#         run_reverse(db, cw, notifier, settings)
#         print("SEA reverse sync complete.")

#     elif job == "retry":
#         from pipeline.jobs.nightly_retry import run
#         run(db, cw, notifier, settings)
#         print("Nightly retry complete.")
        
#     elif job == "local":
#         if len(sys.argv) < 3:
#             print("Usage: python run_manual.py local <file_path>")
#             sys.exit(1)

#         file_path = sys.argv[2]

#         from pipeline.jobs.excel_ingest import run_local_ingest

#         job_run_id = run_local_ingest(db, settings, file_path)

#         print(f"Local Excel ingest complete. Job run: {job_run_id}")    
        

#     elif job == "archive":
#         from pipeline.jobs.archive import run
#         run(db, settings)
#         print("Archive complete.")
        
        

#     elif job == "all":
#         from pipeline.jobs.excel_ingest import run as run_ingest
#         from pipeline.jobs.sync_air import run as run_air
#         from pipeline.jobs.sync_sea import run_sync, run_reverse

#         print("=== Excel Ingest ===")
#         job_run_id = run_ingest(db, cw, notifier, settings)

#         print("=== AIR Sync ===")
#         run_air(db, cw, notifier, settings, parent_job_run_id=job_run_id)

#         print("=== SEA Sync ===")
#         run_sync(db, cw, notifier, settings, parent_job_run_id=job_run_id)

#         print("=== SEA Reverse ===")
#         run_reverse(db, cw, notifier, settings)

#         print("All jobs complete.")

#     else:
#         print(f"Unknown job: {job}")
#         print(__doc__)
#         sys.exit(1)


# if __name__ == "__main__":
#     main()



#!/usr/bin/env python3
"""
Manual job runner — test any job without the scheduler.

Usage:
    python3 run_manual.py --env prod download           # SFTP download (PROD)
    python3 run_manual.py --env uat  download           # SFTP download (UAT)
    python3 run_manual.py --env prod ingest             # Excel ingest + AIR/SEA sync chain (PROD)
    python3 run_manual.py --env uat  ingest             # Excel ingest + AIR/SEA sync chain (UAT)
    python3 run_manual.py --env prod downloadandingest  # Download + ingest in one step (PROD)
    python3 run_manual.py --env uat  downloadandingest  # Download + ingest in one step (UAT)
    python3 run_manual.py --env prod air                # AIR sync only (PROD)
    python3 run_manual.py --env prod sea                # SEA sync only (PROD)
    python3 run_manual.py --env prod reverse            # SEA reverse (PROD)
    python3 run_manual.py --env prod retry              # Nightly retry (PROD)
    python3 run_manual.py --env prod archive            # Archive old files (PROD)
    python3 run_manual.py --env prod all                # Full cycle (PROD)
    python3 run_manual.py --env uat  all                # Full cycle (UAT)
    python3 run_manual.py --env prod local <file_path>  # Ingest local Excel file (PROD)

    python3 run_manual.py ingest                        # Legacy: uses .env
"""

import os
import sys


def main():
    args = sys.argv[1:]

    # Parse --env flag
    if "--env" in args:
        idx = args.index("--env")
        if idx + 1 >= len(args):
            print("Error: --env requires a value (prod or uat)")
            sys.exit(1)
        env_name = args[idx + 1]
        os.environ["PIPELINE_ENV"] = env_name
        args = args[:idx] + args[idx + 2:]

    if not args:
        print(__doc__)
        sys.exit(1)

    job = args[0].lower()

    # Import AFTER setting PIPELINE_ENV so config.py picks it up
    from pipeline.config import Settings
    from pipeline.db import Database
    from pipeline.cargowise import CargoWiseClient
    from pipeline.notifications import EmailNotifier
    from pipeline.log_setup import setup_logging

    settings = Settings()
    setup_logging(settings)
    print(f"[run_manual] Environment: {settings.ENV} | Database: {settings.DB_NAME}")
    db = Database(settings)
    cw = CargoWiseClient(settings)
    notifier = EmailNotifier(settings)
    cw.warmup()

    if job == "download":
        from pipeline.jobs.excel_ingest import run_download_only
        job_run_id = run_download_only(db, settings)
        print(f"Excel download + DB populate complete. Job run: {job_run_id}")

    elif job == "ingest":
        from pipeline.jobs.excel_ingest import run
        job_run_id = run(db, cw, notifier, settings)
        print(f"Excel ingest complete. Job run: {job_run_id}")

        # from pipeline.jobs.sync_air import run as run_air
        # from pipeline.jobs.sync_sea import run_sync
        # from pipeline.jobs.sync_sea import run_reverse
        # print("Triggering AIR sync...")
        # run_air(db, cw, notifier, settings)
        # print("Triggering SEA sync...")
        # run_sync(db, cw, notifier, settings)
        # print("Triggering Reverse sync...")
        # run_reverse(db, cw, notifier, settings)

    # elif job == "downloadandingest":
    #     from pipeline.jobs.excel_ingest import run_download_only
    #     print("=== SFTP Download ===")
    #     download_run_id = run_download_only(db, settings)
    #     print(f"Excel download + DB populate complete. Job run: {download_run_id}")

    #     from pipeline.jobs.excel_ingest import run as run_ingest
    #     print("=== Excel Ingest ===")
    #     job_run_id = run_ingest(db, cw, notifier, settings)
    #     print(f"Excel ingest complete. Job run: {job_run_id}")

    #     print("Download + ingest complete.")
    
    elif job == "downloadandingest":
        from pipeline.jobs.excel_ingest import run_download_and_ingest
        job_run_id = run_download_and_ingest(db, cw, notifier, settings)
        print(f"Download + ingest complete. Job run: {job_run_id}")

    elif job == "air":
        from pipeline.jobs.sync_air import run
        run(db, cw, notifier, settings)
        print("AIR sync complete.")

    elif job == "sea":
        from pipeline.jobs.sync_sea import run_sync
        run_sync(db, cw, notifier, settings)
        print("SEA sync complete.")

    elif job == "reverse":
        from pipeline.jobs.sync_sea import run_reverse
        run_reverse(db, cw, notifier, settings)
        print("SEA reverse sync complete.")

    elif job == "retry":
        from pipeline.jobs.nightly_retry import run
        run(db, cw, notifier, settings)
        print("Nightly retry complete.")

    elif job == "local":
        if len(args) < 2:
            print("Usage: python run_manual.py [--env prod|uat] local <file_path>")
            sys.exit(1)
        file_path = args[1]

        from pipeline.jobs.excel_ingest import run_local_ingest
        job_run_id = run_local_ingest(db, settings, file_path)
        print(f"Local Excel ingest complete. Job run: {job_run_id}")

    elif job == "archive":
        from pipeline.jobs.archive import run
        run(db, settings)
        print("Archive complete.")

    elif job == "all":
        from pipeline.jobs.excel_ingest import run as run_ingest
        from pipeline.jobs.sync_air import run as run_air
        from pipeline.jobs.sync_sea import run_sync, run_reverse

        print("=== Excel Ingest ===")
        job_run_id = run_ingest(db, cw, notifier, settings)

        print("=== AIR Sync ===")
        run_air(db, cw, notifier, settings, parent_job_run_id=job_run_id)

        print("=== SEA Sync ===")
        run_sync(db, cw, notifier, settings, parent_job_run_id=job_run_id)

        print("=== SEA Reverse ===")
        run_reverse(db, cw, notifier, settings)

        print("All jobs complete.")

    else:
        print(f"Unknown job: {job}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()