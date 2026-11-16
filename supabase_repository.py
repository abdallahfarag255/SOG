from datetime import date

from supabase import create_client

from models import RiderStats


class SupabaseRepository:
    def __init__(self, url: str, key: str):
        self._url = url
        self._key = key
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = create_client(self._url, self._key)
        return self._client

    PAGE_SIZE = 1000

    def _select_all(self, build_query) -> list:
        # Supabase returns at most 1000 rows per request and silently drops
        # the rest, so page through until a short page comes back. The query
        # must be ordered so the pages don't overlap or skip rows.
        rows = []
        start = 0
        while True:
            batch = build_query().range(start, start + self.PAGE_SIZE - 1).execute().data
            rows.extend(batch)
            if len(batch) < self.PAGE_SIZE:
                return rows
            start += self.PAGE_SIZE


class ExtractedImageRepository(SupabaseRepository):
    TABLE_NAME = "extracted_data"

    def insert(self, image_name: str, extracted_text: str, rider_id: str = None) -> dict:
        response = (
            self._get_client().table(self.TABLE_NAME)
            .insert({"image_name": image_name, "extracted_text": extracted_text, "rider_id": rider_id})
            .execute()
        )
        return response.data[0] if response.data else {}


class DigitTemplateRepository(SupabaseRepository):
    TABLE_NAME = "digit_templates"

    def get_all(self) -> dict:
        rows = self._select_all(lambda: (
            self._get_client().table(self.TABLE_NAME)
            .select("id, label, canvas_data")
            .order("created_at")
            .order("id")
        ))
        templates = {}
        for row in rows:
            templates.setdefault(row["label"], []).append(row)
        return templates

    def insert(self, label: str, canvas_data: str) -> dict:
        response = (
            self._get_client().table(self.TABLE_NAME)
            .insert({"label": label, "canvas_data": canvas_data})
            .execute()
        )
        return response.data[0] if response.data else {}

    def delete(self, template_id: str) -> None:
        self._get_client().table(self.TABLE_NAME).delete().eq("id", template_id).execute()


class RiderStatsRepository(SupabaseRepository):
    TABLE_NAME = "rider_stats"

    def upsert(self, stats: RiderStats) -> dict:
        stat_date = stats.stat_date or date.today().isoformat()
        response = (
            self._get_client().table(self.TABLE_NAME)
            .upsert({
                "rider_id": stats.rider_id,
                "stat_date": stat_date,
                "complete_hours": stats.complete_hours,
                "complete_order": stats.complete_order,
                "installments": stats.installments,
                "wallet": stats.wallet,
                "driver_name": stats.driver_name,
                "phone": stats.phone,
                "zone": stats.zone,
            }, on_conflict="rider_id,stat_date")
            .execute()
        )
        return response.data[0] if response.data else {}

    def update_notes(self, rider_id: str, stat_date: str, notes: str) -> None:
        (
            self._get_client().table(self.TABLE_NAME)
            .upsert(
                {"rider_id": rider_id, "stat_date": stat_date, "notes": notes},
                on_conflict="rider_id,stat_date",
            )
            .execute()
        )

    def ensure_daily_snapshot(self, riders: list) -> None:
        """Makes sure every currently active rider has a rider_stats row for today,
        so archived/past-day views can show everyone who was active that day —
        even riders nobody entered stats for. Never overwrites a row's saved
        stats or already-filled driver_name/phone/zone; only backfills those
        three fields if an earlier snapshot the same day captured them blank
        (e.g. the source sheet hadn't been filled in yet at that point)."""
        if not riders:
            return
        today = date.today().isoformat()
        client = self._get_client()

        existing_response = (
            client.table(self.TABLE_NAME)
            .select("rider_id, driver_name, phone, zone")
            .eq("stat_date", today)
            .in_("rider_id", [r.id_rider for r in riders])
            .execute()
        )
        existing_by_id = {row["rider_id"]: row for row in existing_response.data}

        new_rows = []
        for r in riders:
            if r.id_rider not in existing_by_id:
                new_rows.append({
                    "rider_id": r.id_rider,
                    "stat_date": today,
                    "driver_name": r.driver_name,
                    "phone": r.phone,
                    "zone": r.zone,
                    "complete_hours": "",
                    "complete_order": "",
                    "installments": "",
                    "wallet": "",
                    "notes": "",
                })

        if new_rows:
            client.table(self.TABLE_NAME).upsert(
                new_rows, on_conflict="rider_id,stat_date", ignore_duplicates=True
            ).execute()

        for r in riders:
            existing = existing_by_id.get(r.id_rider)
            if not existing:
                continue
            patch = {}
            if not existing.get("driver_name") and r.driver_name:
                patch["driver_name"] = r.driver_name
            if not existing.get("phone") and r.phone:
                patch["phone"] = r.phone
            if not existing.get("zone") and r.zone:
                patch["zone"] = r.zone
            if patch:
                patch["rider_id"] = r.id_rider
                patch["stat_date"] = today
                client.table(self.TABLE_NAME).upsert(patch, on_conflict="rider_id,stat_date").execute()

    def get_for_rider(self, rider_id: str, stat_date: str):
        response = (
            self._get_client().table(self.TABLE_NAME)
            .select("*")
            .eq("rider_id", rider_id)
            .eq("stat_date", stat_date)
            .limit(1)
            .execute()
        )
        return self._row_to_stats(response.data[0]) if response.data else None

    def get_all_today(self) -> dict:
        today = date.today().isoformat()
        rows = self._select_all(lambda: (
            self._get_client().table(self.TABLE_NAME)
            .select("*")
            .eq("stat_date", today)
            .order("rider_id")
        ))
        return {row["rider_id"]: self._row_to_stats(row) for row in rows}

    def get_by_date(self, stat_date: str) -> list:
        rows = self._select_all(lambda: (
            self._get_client().table(self.TABLE_NAME)
            .select("*")
            .eq("stat_date", stat_date)
            .order("driver_name")
            .order("rider_id")
        ))
        return [self._row_to_stats(row) for row in rows]

    def get_by_dates(self, stat_dates: list) -> list:
        if not stat_dates:
            return []
        rows = self._select_all(lambda: (
            self._get_client().table(self.TABLE_NAME)
            .select("*")
            .in_("stat_date", stat_dates)
            .order("stat_date")
            .order("rider_id")
        ))
        return [self._row_to_stats(row) for row in rows]

    def get_by_date_range(self, start_date: str, end_date: str) -> list:
        rows = self._select_all(lambda: (
            self._get_client().table(self.TABLE_NAME)
            .select("*")
            .gte("stat_date", start_date)
            .lte("stat_date", end_date)
            .order("stat_date")
            .order("rider_id")
        ))
        return [self._row_to_stats(row) for row in rows]

    def remove_stale(self, active_rider_ids: list) -> None:
        if not active_rider_ids:
            return
        today = date.today().isoformat()
        (
            self._get_client().table(self.TABLE_NAME)
            .delete()
            .eq("stat_date", today)
            .not_.in_("rider_id", active_rider_ids)
            .execute()
        )

    @staticmethod
    def _row_to_stats(row: dict) -> RiderStats:
        return RiderStats(
            rider_id=row.get("rider_id", ""),
            complete_hours=row.get("complete_hours") or "",
            complete_order=row.get("complete_order") or "",
            installments=row.get("installments") or "",
            wallet=row.get("wallet") or "",
            driver_name=row.get("driver_name") or "",
            phone=row.get("phone") or "",
            zone=row.get("zone") or "",
            notes=row.get("notes") or "",
            stat_date=row.get("stat_date", ""),
        )
