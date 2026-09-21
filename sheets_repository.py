import threading
import time
import unicodedata

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

    @staticmethod
    def _clean_id(value) -> str:
        # Some sheet IDs carry invisible bidi marks (e.g. U+200F) that
        # str.strip() leaves in place, which would make the same rider
        # look like two different IDs.
        return "".join(ch for ch in str(value) if unicodedata.category(ch) != "Cf").strip()

    def _read_tab(self, tab_name: str) -> tuple:
        values = self._get_spreadsheet().worksheet(tab_name).get_all_values()
        if not values:
            return [], []
        return [h.strip() for h in values[0]], values[1:]

    @staticmethod
    def _cell(row: list, idx: int) -> str:
        return row[idx].strip() if len(row) > idx else ""

    @staticmethod
    def _column(header: list, name: str, tab_name: str) -> int:
        if name not in header:
            raise ValueError(f'عمود "{name}" مش موجود في تاب "{tab_name}" في الشيت (اتغير اسمه أو اتمسح؟)')
        return header.index(name)

    def _fetch_rent_by_rider_id(self) -> dict:
        header, rows = self._read_tab(self.DASHBOARD_SHEET_NAME)
        if not header:
            return {}
        id_idx = self._column(header, "ID Rider", self.DASHBOARD_SHEET_NAME)
        rent_idx = self._column(header, "Rent Remaining", self.DASHBOARD_SHEET_NAME)
        return {
            self._clean_id(row[id_idx]): self._cell(row, rent_idx)
            for row in rows
            if len(row) > id_idx and self._clean_id(row[id_idx])
        }

    def _fetch_active_riders(self) -> list:
        # Identity (name/phone/zone/state) comes from "Drivers Data", keyed
        # by the rider's ID. The Dashboard tab pulls those columns by row
        # position, one column at a time, so they can drift apart and show
        # one rider's ID next to another rider's name. Its rent column is
        # looked up by ID, so that one is safe to use.
        header, rows = self._read_tab(self.DRIVERS_DATA_SHEET_NAME)
        if not header:
            return []
        tab = self.DRIVERS_DATA_SHEET_NAME
        id_idx = self._column(header, "Rider ID", tab)
        name_idx = self._column(header, "Driver Name", tab)
        phone_idx = self._column(header, "Phone Num.", tab)
        state_idx = self._column(header, "State", tab)
        zone_idx = self._column(header, "zone", tab)

        rent_by_id = self._fetch_rent_by_rider_id()

        riders = []
        seen = set()
        for row in rows:
            rider_id = self._clean_id(row[id_idx]) if len(row) > id_idx else ""
            if not rider_id or rider_id in seen or self._cell(row, state_idx) != "Active":
                continue
            seen.add(rider_id)
            riders.append(Rider(
                id_rider=rider_id,
                driver_name=self._cell(row, name_idx),
                phone=self._cell(row, phone_idx),
                state=self._cell(row, state_idx),
                rent_remaining=rent_by_id.get(rider_id, ""),
                zone=self._cell(row, zone_idx),
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
