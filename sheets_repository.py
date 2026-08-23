import threading
import time

import gspread
from google.oauth2.service_account import Credentials

from models import Rider


class GoogleSheetsRepository:
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    DASHBOARD_SHEET_NAME = "Dashboard"
    DRIVERS_DATA_SHEET_NAME = "Drivers Data"

    def __init__(self, sheet_id: str, cache_ttl_seconds: int = 60,
                 service_account_file: str = None, service_account_info: dict = None):
        if not service_account_file and not service_account_info:
            raise ValueError("Provide either service_account_file or service_account_info")
        self._service_account_file = service_account_file
        self._service_account_info = service_account_info
        self._sheet_id = sheet_id
        self._cache_ttl_seconds = cache_ttl_seconds
        self._client = None
        self._cache: list = None
        self._cache_time: float = 0.0
        self._lock = threading.Lock()

    def _get_client(self):
        if self._client is None:
            if self._service_account_info:
                creds = Credentials.from_service_account_info(self._service_account_info, scopes=self.SCOPES)
            else:
                creds = Credentials.from_service_account_file(self._service_account_file, scopes=self.SCOPES)
            self._client = gspread.authorize(creds)
        return self._client

    def _get_spreadsheet(self):
        return self._get_client().open_by_key(self._sheet_id)

    def _fetch_zone_by_rider_id(self) -> dict:
        worksheet = self._get_spreadsheet().worksheet(self.DRIVERS_DATA_SHEET_NAME)
        values = worksheet.get_all_values()
        if not values:
            return {}

        header = [h.strip() for h in values[0]]
        id_idx = header.index("Rider ID")
        zone_idx = header.index("zone")

        zone_by_id = {}
        for row in values[1:]:
            rider_id = row[id_idx].strip() if len(row) > id_idx else ""
            if not rider_id:
                continue
            zone_by_id[rider_id] = row[zone_idx].strip() if len(row) > zone_idx else ""
        return zone_by_id

    def _fetch_active_riders(self) -> list:
        worksheet = self._get_spreadsheet().worksheet(self.DASHBOARD_SHEET_NAME)
        values = worksheet.get_all_values()
        if not values:
            return []

        header = [h.strip() for h in values[0]]
        id_idx = header.index("ID Rider")
        name_idx = header.index("Driver Name")
        phone_idx = header.index("Phone Num.")
        state_idx = header.index("State")
        rent_idx = header.index("Rent Remaining")

        zone_by_id = self._fetch_zone_by_rider_id()

        riders = []
        for row in values[1:]:
            if len(row) <= state_idx or row[state_idx].strip() != "Active":
                continue
            rider_id = row[id_idx].strip() if len(row) > id_idx else ""
            riders.append(Rider(
                id_rider=rider_id,
                driver_name=row[name_idx].strip() if len(row) > name_idx else "",
                phone=row[phone_idx].strip() if len(row) > phone_idx else "",
                state=row[state_idx].strip(),
                rent_remaining=row[rent_idx].strip() if len(row) > rent_idx else "",
                zone=zone_by_id.get(rider_id, ""),
            ))
        return riders

    def get_active_riders(self, force_refresh: bool = False) -> list:
        now = time.time()
        is_expired = (now - self._cache_time) > self._cache_ttl_seconds
        if force_refresh or self._cache is None or is_expired:
            with self._lock:
                now = time.time()
                is_expired = (now - self._cache_time) > self._cache_ttl_seconds
                if force_refresh or self._cache is None or is_expired:
                    self._cache = self._fetch_active_riders()
                    self._cache_time = now
        return self._cache

    def find_rider(self, rider_id: str):
        for rider in self.get_active_riders():
            if rider.id_rider == rider_id:
                return rider
        return None

    def start_background_refresh(self, interval_seconds: float = None) -> None:
        interval = interval_seconds or max(5, self._cache_ttl_seconds - 15)

        def _loop():
            while True:
                try:
                    self.get_active_riders(force_refresh=True)
                except Exception:
                    pass
                time.sleep(interval)

        thread = threading.Thread(target=_loop, daemon=True)
        thread.start()
