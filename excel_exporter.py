import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font


def _build_workbook(headers: list, rows: list) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.sheet_view.rightToLeft = True

    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")

    for row in rows:
        ws.append(row)

    for column_cells in ws.columns:
        length = max((len(str(cell.value)) for cell in column_cells if cell.value is not None), default=10)
        ws.column_dimensions[column_cells[0].column_letter].width = min(40, max(10, length + 2))

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


class RidersExcelExporter:
    @staticmethod
    def export(riders: list, is_today: bool) -> bytes:
        headers = ["ID Rider", "Driver Name", "Phone Number"]
        if is_today:
            headers.append("State")
        headers += [
            "Rent Remaining", "Zone", "Complete Hours", "Complete Order",
            "Wallet", "Installments", "Equation", "Notes",
        ]

        rows = []
        for r in riders:
            row = [r.id_rider, r.driver_name, r.phone]
            if is_today:
                row.append(r.state)
            row += [
                r.rent_remaining, r.zone, r.complete_hours, r.complete_order,
                r.wallet, r.installments, r.equation, r.notes,
            ]
            rows.append(row)

        return _build_workbook(headers, rows)


class EquationExcelExporter:
    @staticmethod
    def export(rows: list) -> bytes:
        headers = ["Equation", "Installments", "Wallet", "ID Rider", "Zone", "Driver Name"]
        sheet_rows = [
            [
                round(r["equation"], 2), round(r["installments_sum"], 2), round(r["wallet"], 2),
                r["rider_id"], r["zone"], r["driver_name"],
            ]
            for r in rows
        ]
        return _build_workbook(headers, sheet_rows)
