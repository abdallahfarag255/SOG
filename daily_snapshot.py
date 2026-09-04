import json
import os

from sheets_repository import GoogleSheetsRepository
from supabase_repository import RiderStatsRepository


BOM = "﻿"


def main():
    service_account_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"].lstrip(BOM)
    sheets_repo = GoogleSheetsRepository(
        sheet_id=os.environ["GOOGLE_SHEET_ID"],
        service_account_info=json.loads(service_account_json),
    )
    stats_repo = RiderStatsRepository(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    riders = sheets_repo.get_active_riders(force_refresh=True)
    stats_repo.ensure_daily_snapshot(riders)
    print(f"snapshotted {len(riders)} active riders")


if __name__ == "__main__":
    main()
