import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font


class RidersExcelExporter:
    @staticmethod
    def export(riders: list, is_today: bool) -> bytes:
        wb = Workbook()
        ws = wb.active
        ws.sheet_view.rightToLeft = True

        headers = ["ID Rider", "Driver Name", "Phone Number"]
        if is_today:
            headers.append("State")
        headers += [
            "Rent Remaining", "Zone", "Complete Hours", "Complete Order",
            "Wallet", "Installments", "Equation", "Notes",
        ]
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center")

        for r in riders:
            row = [r.id_rider, r.driver_name, r.phone]
            if is_today:
                row.append(r.state)
            row += [
                r.rent_remaining, r.zone, r.complete_hours, r.complete_order,
                r.wallet, r.installments, r.equation, r.notes,
            ]
            ws.append(row)

        for column_cells in ws.columns:
            length = max((len(str(cell.value)) for cell in column_cells if cell.value is not None), default=10)
            ws.column_dimensions[column_cells[0].column_letter].width = min(40, max(10, length + 2))

        buffer = io.BytesIO()
        wb.save(buffer)
        return buffer.getvalue()
