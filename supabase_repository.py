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


class ExtractedImageRepository(SupabaseRepository):
    TABLE_NAME = "extracted_data"

    def insert(self, image_name: str, extracted_text: str, rider_id: str = None) -> dict:
        response = (
            self._get_client().table(self.TABLE_NAME)
            .insert({"image_name": image_name, "extracted_text": extracted_text, "rider_id": rider_id})
            .execute()
        )
        return response.data[0] if response.data else {}


class UserRepository(SupabaseRepository):
    TABLE_NAME = "users"

    def get_by_username(self, username: str) -> dict:
        response = (
            self._get_client().table(self.TABLE_NAME)
            .select("*")
            .eq("username", username)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None


class DigitTemplateRepository(SupabaseRepository):
    TABLE_NAME = "digit_templates"

    def get_all(self) -> dict:
        response = (
            self._get_client().table(self.TABLE_NAME)
            .select("id, label, canvas_data")
            .order("created_at")
            .execute()
        )
        templates = {}
        for row in response.data:
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
        today = date.today().isoformat()
        response = (
            self._get_client().table(self.TABLE_NAME)
            .upsert({
                "rider_id": stats.rider_id,
                "stat_date": today,
                "complete_hours": stats.complete_hours,
                "complete_order": stats.complete_order,
                "installments": stats.installments,
                "wallet": stats.wallet,
                "driver_name": stats.driver_name,
                "phone": stats.phone,
            }, on_conflict="rider_id,stat_date")
            .execute()
        )
        return response.data[0] if response.data else {}

    def get_for_rider_today(self, rider_id: str):
        today = date.today().isoformat()
        response = (
            self._get_client().table(self.TABLE_NAME)
            .select("*")
            .eq("rider_id", rider_id)
            .eq("stat_date", today)
            .limit(1)
            .execute()
        )
        return self._row_to_stats(response.data[0]) if response.data else None

    def get_all_today(self) -> dict:
        today = date.today().isoformat()
        response = self._get_client().table(self.TABLE_NAME).select("*").eq("stat_date", today).execute()
        return {row["rider_id"]: self._row_to_stats(row) for row in response.data}

    def get_by_date(self, stat_date: str) -> list:
        response = (
            self._get_client().table(self.TABLE_NAME)
            .select("*")
            .eq("stat_date", stat_date)
            .order("driver_name")
            .execute()
        )
        return [self._row_to_stats(row) for row in response.data]

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
            stat_date=row.get("stat_date", ""),
        )
