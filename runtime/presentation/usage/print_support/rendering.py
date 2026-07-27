from __future__ import annotations

from dataclasses import dataclass

# ruff: noqa: E402  # Consolidated module keeps section-local imports.


@dataclass(frozen=True, slots=True)
class UsagePrintContext:
    title: str
    generated_at_text: str
    branch_text: str
    row_count: int
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    numeric_columns: tuple[int, ...]
    column_ratios: tuple[int, ...]
    logo_path: str


import logging
from collections.abc import Sequence
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QFontMetrics
from runtime.shared.settings.config import _
from runtime.shared.errors import SERVICE_OPERATION_EXCEPTIONS
from runtime.shared.numbers import format_plain_number

logger = logging.getLogger(__name__)


class UsagePrintMetricsMixin:

    def _fit_print_fonts(
        self, *, column_widths: Sequence[int], dpi: int
    ) -> tuple[QFont, QFont, QFont, int, int, int, int]:
        # Keep printed headings legible even on high-DPI printer drivers.
        header_pt = 9
        cell_pt = 7
        if column_widths and min(column_widths) >= int(round(12 * dpi / 25.4)):
            header_pt = 10
            cell_pt = 8
        if column_widths and min(column_widths) < int(round(9 * dpi / 25.4)):
            header_pt = 8
            cell_pt = 6
        meta_font = QFont("Segoe UI", 8)
        header_font = QFont("Segoe UI", header_pt)
        header_font.setBold(True)
        cell_font = QFont("Segoe UI", cell_pt)
        header_metrics = QFontMetrics(header_font)
        cell_metrics = QFontMetrics(cell_font)
        header_h = max(
            int(round(13.5 * dpi / 25.4)),
            min(
                int(round(19 * dpi / 25.4)),
                header_metrics.lineSpacing() * 3 + int(round(3.0 * dpi / 25.4)),
            ),
        )
        row_h = max(int(round(6.8 * dpi / 25.4)), cell_metrics.height() + 4)
        footer_h = int(round(7 * dpi / 25.4))
        cell_pad_x = max(2, int(round(0.85 * dpi / 25.4)))
        return (
            meta_font,
            header_font,
            cell_font,
            header_h,
            row_h,
            footer_h,
            cell_pad_x,
        )

    def _column_widths_for_a4(
        self,
        usable_width: int,
        ratios: Sequence[int],
        column_count: int,
        headers: Sequence[str],
        dpi: int,
    ) -> tuple[int, ...]:
        """Calculate all Usage columns for A4 portrait without hiding columns."""
        if column_count <= 0:
            return tuple()
        default_ratios = (16, 38, 9, 10, 8, 14, 6, 13)
        if not ratios or len(ratios) != column_count:
            ratios = default_ratios[:column_count] or tuple([1] * column_count)
        ratios = tuple((max(1, int(value)) for value in ratios))
        min_mm = (19, 48, 12, 13, 10, 18, 9, 15)
        min_widths = [int(round(mm * dpi / 25.4)) for mm in min_mm[:column_count]]
        if len(min_widths) < column_count:
            min_widths.extend(
                [int(round(12 * dpi / 25.4))] * (column_count - len(min_widths))
            )
        header_metrics = QFontMetrics(QFont("Segoe UI", 8))
        for index, header in enumerate(headers[:column_count]):
            parts = (
                str(header or "")
                .replace("(", " ")
                .replace(")", " ")
                .replace("/", " ")
                .split()
            )
            longest = max(parts, key=len) if parts else str(header or "")
            needed = header_metrics.horizontalAdvance(longest) + int(
                round(2 * dpi / 25.4)
            )
            min_widths[index] = max(
                min_widths[index], min(needed, int(round(28 * dpi / 25.4)))
            )
        min_total = sum(min_widths)
        if min_total >= usable_width:
            scale = usable_width / max(1, min_total)
            widths = [max(1, int(width * scale)) for width in min_widths]
        else:
            remaining = usable_width - min_total
            total_ratio = max(1, sum(ratios))
            widths = [
                min_widths[index] + int(remaining * (ratios[index] / total_ratio))
                for index in range(column_count)
            ]
        drift = usable_width - sum(widths)
        if widths:
            widths[1 if len(widths) > 1 else 0] += drift
        return tuple((max(1, int(width)) for width in widths))

    @staticmethod
    def _wrap_text_to_lines(
        text: str, metrics: QFontMetrics, max_width: int, max_lines: int
    ) -> list[str]:
        clean = str(text or "").strip()
        if not clean:
            return [""]
        words = clean.replace("/", " / ").split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if metrics.horizontalAdvance(candidate) <= max_width or not current:
                current = candidate
                continue
            lines.append(current)
            current = word
            if len(lines) >= max_lines - 1:
                break
        if current and len(lines) < max_lines:
            lines.append(current)
        if not lines:
            lines = [clean]
        if len(lines) == max_lines and metrics.horizontalAdvance(lines[-1]) > max_width:
            lines[-1] = metrics.elidedText(lines[-1], Qt.ElideRight, max(8, max_width))
        return lines[:max_lines]

    @staticmethod
    def _column_alignment(column: int, numeric_columns: set[int]) -> int:
        if column in numeric_columns:
            return Qt.AlignCenter
        if column == 6:
            return Qt.AlignCenter
        return Qt.AlignVCenter | Qt.AlignLeft

    @staticmethod
    def _normalize_header(label: str) -> str:
        value = str(label or "").strip()
        lowered = value.lower()
        if lowered == "begining":
            return _("Beginning")
        if lowered == "available stock":
            return _("Available")
        if lowered in {"available qty", "available qty (enter)"}:
            return _("Available Qty")
        if lowered == "actual consumption":
            return _("Actual consumption")
        return value

    @staticmethod
    def _format_cell(
        *, column: int, display_value, raw_value, numeric_columns: set[int]
    ) -> str:
        if column in numeric_columns:
            if display_value in (None, "") and raw_value in (None, ""):
                return ""
            if raw_value is None and display_value not in (None, ""):
                return str(display_value)
            try:
                return format_plain_number(raw_value if raw_value is not None else 0.0)
            except SERVICE_OPERATION_EXCEPTIONS:
                return str(display_value or "")
        return str(display_value or "")


from PyQt5.QtGui import QPainter
from PyQt5.QtPrintSupport import QPrinter
from runtime.presentation.layout import helpers as _layout_rules



class UsagePrintPrinterMixin:

    def _configure_a4_portrait_printer(
        self, printer: QPrinter, *, doc_name: str = ""
    ) -> None:
        try:
            printer.setFullPage(False)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("Usage print: setFullPage(False) failed", exc_info=True)
        try:
            printer.setResolution(max(300, int(printer.resolution() or 0)))
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("Usage print: setResolution failed", exc_info=True)
        try:
            from PyQt5.QtCore import QMarginsF
            from PyQt5.QtGui import QPageLayout, QPageSize

            margins = QMarginsF(
                self.PAGE_MARGIN_MM,
                self.PAGE_MARGIN_MM,
                self.PAGE_MARGIN_MM,
                self.PAGE_MARGIN_MM,
            )
            page_layout = QPageLayout(
                QPageSize(QPageSize.A4),
                QPageLayout.Portrait,
                margins,
                QPageLayout.Millimeter,
            )
            printer.setPageLayout(page_layout)
            if hasattr(printer, "setPageOrientation"):
                printer.setPageOrientation(QPageLayout.Portrait)
            if hasattr(printer, "setPageSize"):
                printer.setPageSize(QPageSize(QPageSize.A4))
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug(
                "Usage print: QPageLayout A4 portrait setup failed", exc_info=True
            )
        try:
            _layout_rules.set_printer_page_size(printer, QPrinter.A4)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("Usage print: public setPageSize(A4) failed", exc_info=True)
        try:
            if hasattr(printer, "setPaperSize"):
                printer.setPaperSize(QPrinter.A4)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("Usage print: setPaperSize(A4) failed", exc_info=True)
        try:
            printer.setOrientation(QPrinter.Portrait)
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug(
                "Usage print: public setOrientation(Portrait) failed", exc_info=True
            )
        try:
            printer.setPageMargins(
                self.PAGE_MARGIN_MM,
                self.PAGE_MARGIN_MM,
                self.PAGE_MARGIN_MM,
                self.PAGE_MARGIN_MM,
                QPrinter.Millimeter,
            )
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("Usage print: setPageMargins fallback failed", exc_info=True)
        try:
            printer.setDocName(str(doc_name or _("Herfy Monthly Usage")))
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("Usage print: setDocName failed", exc_info=True)

    def _portrait_page_rect(
        self, painter: QPainter, printer: QPrinter
    ) -> tuple[int, int, bool]:
        """Return portrait device coordinates; rotate only when the driver reports landscape."""
        del painter
        page_rect = printer.pageRect()
        page_w = int(page_rect.width())
        page_h = int(page_rect.height())
        if page_h >= page_w:
            return (page_w, page_h, False)
        return (page_h, page_w, True)

    @staticmethod
    def _restore_portrait_painter(painter: QPainter, rotated: bool) -> None:
        if rotated:
            painter.restore()


import math
import os
from collections.abc import Iterable
from datetime import datetime
from PyQt5.QtCore import QRect
from PyQt5.QtGui import QPen, QPixmap
from PyQt5.QtPrintSupport import QPrintPreviewDialog
from runtime.shared.settings.config import resource_path
from runtime.presentation.widgets import apply_popup_contract
from runtime.presentation.widgets import qt_file_image_loading_enabled



class UsagePrintRenderMixin:

    @staticmethod
    def _format_generated_date(value: datetime | None = None) -> str:
        stamp = value or datetime.now()
        return stamp.strftime("%d %b %Y")

    def build_context(
        self,
        *,
        model,
        headers: Sequence[str],
        numeric_columns: Iterable[int] = (),
        column_ratios: Sequence[int] | None = None,
        title: str | None = None,
        branch_text: str = "",
        logo_path: str | None = None,
    ) -> UsagePrintContext:
        numeric_set = {int(value) for value in numeric_columns}
        normalized_headers = tuple((self._normalize_header(label) for label in headers))
        rows: list[tuple[str, ...]] = []
        row_count = int(model.rowCount())
        column_count = int(model.columnCount())
        ratios = tuple(
            (int(value) for value in column_ratios or [1] * max(1, column_count))
        )
        for row in range(row_count):
            rendered_row: list[str] = []
            for column in range(column_count):
                index = model.index(row, column)
                display_value = model.data(index, Qt.DisplayRole)
                raw_value = model.data(index, Qt.UserRole)
                rendered_row.append(
                    self._format_cell(
                        column=column,
                        display_value=display_value,
                        raw_value=raw_value,
                        numeric_columns=numeric_set,
                    )
                )
            rows.append(tuple(rendered_row))
        return UsagePrintContext(
            title=str(title or _("Herfy Monthly Usage")),
            generated_at_text=self._format_generated_date(),
            branch_text=str(branch_text or "").strip(),
            row_count=row_count,
            headers=normalized_headers,
            rows=tuple(rows),
            numeric_columns=tuple(sorted(numeric_set)),
            column_ratios=ratios,
            logo_path=str(
                logo_path or resource_path("resources", "images", "logo.png")
            ),
        )

    def show_preview(self, parent, *, context: UsagePrintContext) -> bool:
        if context.row_count <= 0:
            return False
        printer = QPrinter(QPrinter.HighResolution)
        self._configure_a4_portrait_printer(printer, doc_name=context.title)
        preview = QPrintPreviewDialog(printer, parent)
        try:
            if hasattr(preview, "printer"):
                self._configure_a4_portrait_printer(
                    preview.printer(), doc_name=context.title
                )
        except SERVICE_OPERATION_EXCEPTIONS:
            logger.debug("Usage print: preview printer setup failed", exc_info=True)
        apply_popup_contract(
            preview,
            object_name="UsagePrintPreviewDialog",
            modal=True,
            size_grip=True,
            width_ratio=0.94,
            height_ratio=0.9,
            min_width=1180,
            min_height=760,
            max_width=None,
            max_height=None,
        )
        preview.setWindowTitle(_("Herfy Monthly Usage - Print Preview"))

        def _paint_requested(device):
            self._configure_a4_portrait_printer(device, doc_name=context.title)
            self.render_report(device, context=context)

        preview.paintRequested.connect(_paint_requested)
        preview.exec_()
        return True

    def render_report(self, printer: QPrinter, *, context: UsagePrintContext) -> None:
        painter = QPainter(printer)
        if not painter.isActive():
            return
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            self._render_document(painter, printer, context)
        finally:
            painter.end()

    def _render_document(
        self, painter: QPainter, printer: QPrinter, context: UsagePrintContext
    ) -> None:
        dpi = max(72, int(printer.resolution() or self.PRINT_DPI_FALLBACK))

        def mm(value: float) -> int:
            return int(round(float(value) * dpi / 25.4))

        page_w, page_h, rotated = self._portrait_page_rect(painter, printer)
        raw_page_h = int(printer.pageRect().height())
        left = mm(self.PAGE_MARGIN_MM)
        top = mm(self.PAGE_MARGIN_MM)
        right = mm(self.PAGE_MARGIN_MM)
        bottom = mm(self.PAGE_MARGIN_MM)
        header_block_h = mm(22)
        section_gap = mm(2.5)
        usable_w = max(mm(80), page_w - left - right)
        usable_h = max(mm(80), page_h - top - bottom)
        column_widths = self._column_widths_for_a4(
            usable_w, context.column_ratios, len(context.headers), context.headers, dpi
        )
        meta_font, header_font, cell_font, header_h, row_h, footer_h, cell_pad_x = (
            self._fit_print_fonts(column_widths=column_widths, dpi=dpi)
        )
        small_font = QFont("Segoe UI", max(7, meta_font.pointSize() - 1))
        body_h = usable_h - footer_h - header_block_h - section_gap
        rows_per_page = max(1, int((body_h - header_h) // row_h))
        total_pages = max(1, math.ceil(max(1, context.row_count) / rows_per_page))
        current_row = 0
        total_rows = max(1, context.row_count)
        for page_number in range(total_pages):
            if page_number > 0:
                printer.newPage()
            if rotated:
                painter.save()
                painter.translate(raw_page_h, 0)
                painter.rotate(90)
            try:
                y = top
                self._draw_top_block(
                    painter,
                    left=left,
                    y=y,
                    width=usable_w,
                    height=header_block_h,
                    title_text=context.title,
                    branch_text=context.branch_text,
                    generated_at_text=context.generated_at_text,
                    logo_path=context.logo_path,
                    meta_font=meta_font,
                    small_font=small_font,
                )
                y += header_block_h + section_gap
                self._draw_header_row(
                    painter,
                    left=left,
                    y=y,
                    widths=column_widths,
                    height=header_h,
                    headers=context.headers,
                    font=header_font,
                    cell_pad_x=cell_pad_x,
                )
                y += header_h
                body_limit = top + usable_h - footer_h
                page_row_index = 0
                while (
                    current_row < total_rows
                    and page_row_index < rows_per_page
                    and (y + row_h <= body_limit)
                ):
                    row_values = (
                        context.rows[current_row]
                        if current_row < context.row_count
                        else tuple(("" for _ in context.headers))
                    )
                    self._draw_data_row(
                        painter,
                        left=left,
                        y=y,
                        widths=column_widths,
                        height=row_h,
                        values=row_values,
                        numeric_columns=set(context.numeric_columns),
                        font=cell_font,
                        cell_pad_x=cell_pad_x,
                        shade=page_row_index % 2 == 1,
                    )
                    y += row_h
                    current_row += 1
                    page_row_index += 1
                painter.setPen(self.MUTED_TEXT)
                painter.setFont(meta_font)
                footer_text = _("Page {page} of {total}").format(
                    page=page_number + 1, total=total_pages
                )
                footer_rect = QRect(left, top + usable_h - footer_h, usable_w, footer_h)
                painter.drawText(
                    footer_rect, Qt.AlignRight | Qt.AlignVCenter, footer_text
                )
            finally:
                self._restore_portrait_painter(painter, rotated)

    def _draw_top_block(
        self,
        painter: QPainter,
        *,
        left: int,
        y: int,
        width: int,
        height: int,
        title_text: str,
        branch_text: str,
        generated_at_text: str,
        logo_path: str,
        meta_font: QFont,
        small_font: QFont,
    ) -> None:
        """Draw a balanced report masthead: logo, title, store and date."""
        painter.save()
        try:
            gap = max(8, int(height * 0.10))
            logo_w = min(int(width * 0.20), max(1, int(height * 2.1)))
            meta_w = min(int(width * 0.27), max(1, int(height * 3.2)))
            title_w = max(1, width - logo_w - meta_w - (gap * 2))

            logo_rect = QRect(left, y, logo_w, height - max(2, gap))
            title_rect = QRect(left + logo_w + gap, y, title_w, height - max(2, gap))
            info_rect = QRect(
                title_rect.right() + gap,
                y,
                meta_w,
                height - max(2, gap),
            )

            if (
                logo_path
                and os.path.exists(logo_path)
                and qt_file_image_loading_enabled()
            ):
                pix = QPixmap(logo_path)
                if not pix.isNull():
                    max_logo_h = max(24, int(logo_rect.height() * 0.82))
                    max_logo_w = max(36, int(logo_rect.width() * 0.92))
                    scaled = pix.scaled(
                        max_logo_w,
                        max_logo_h,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                    target = QRect(
                        logo_rect.x(),
                        logo_rect.y()
                        + max(0, (logo_rect.height() - scaled.height()) // 2),
                        scaled.width(),
                        scaled.height(),
                    )
                    painter.drawPixmap(target, scaled)

            title_font = QFont("Segoe UI", max(13, meta_font.pointSize() + 6))
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.setPen(self.TITLE_COLOR)
            painter.drawText(
                title_rect,
                Qt.AlignCenter,
                str(title_text or _("Herfy Monthly Usage")),
            )

            store_font = QFont(meta_font)
            store_font.setBold(True)
            painter.setFont(store_font)
            painter.setPen(self.ACCENT_COLOR)
            store_line = _("STORE : {store}").format(store=branch_text or _("Unknown"))
            painter.drawText(
                info_rect.adjusted(0, 0, 0, -info_rect.height() // 2),
                Qt.AlignRight | Qt.AlignVCenter,
                store_line,
            )

            painter.setPen(self.MUTED_TEXT)
            painter.setFont(small_font)
            date_line = _("Date: {date}").format(date=generated_at_text)
            painter.drawText(
                info_rect.adjusted(0, info_rect.height() // 2 - 1, 0, 0),
                Qt.AlignRight | Qt.AlignVCenter,
                date_line,
            )

            line_y = y + height - 1
            painter.setPen(QPen(self.ACCENT_COLOR, max(1, int(height * 0.025))))
            painter.drawLine(left, line_y, left + width, line_y)
        finally:
            painter.restore()

    def _draw_header_row(
        self,
        painter: QPainter,
        *,
        left: int,
        y: int,
        widths: Sequence[int],
        height: int,
        headers: Sequence[str],
        font: QFont,
        cell_pad_x: int,
    ) -> None:
        x = left
        painter.save()
        painter.setFont(font)
        metrics = QFontMetrics(font)
        for column, (header, width) in enumerate(zip(headers, widths, strict=False)):
            header_text = self._print_header_text(column, str(header or ""))
            rect = QRect(x, y, width, height)
            painter.fillRect(rect, self.HEADER_BG)
            painter.setPen(QPen(self.GRID_COLOR, 0))
            painter.drawRect(rect)
            painter.setPen(self.HEADER_TEXT)
            text_rect = rect.adjusted(cell_pad_x, 1, -cell_pad_x, -1)
            lines = self._wrap_text_to_lines(
                header_text, metrics, max(8, text_rect.width()), max_lines=3
            )
            line_h = metrics.lineSpacing()
            text_y = text_rect.y() + max(
                0, (text_rect.height() - line_h * len(lines)) // 2
            )
            for line in lines:
                line_rect = QRect(text_rect.x(), text_y, text_rect.width(), line_h)
                painter.drawText(line_rect, Qt.AlignCenter, line)
                text_y += line_h
            x += width
        painter.restore()

    def _draw_data_row(
        self,
        painter: QPainter,
        *,
        left: int,
        y: int,
        widths: Sequence[int],
        height: int,
        values: Sequence[str],
        numeric_columns: set[int],
        font: QFont,
        cell_pad_x: int,
        shade: bool,
    ) -> None:
        x = left
        painter.save()
        painter.setFont(font)
        metrics = QFontMetrics(font)
        for column, width in enumerate(widths):
            rect = QRect(x, y, width, height)
            if shade:
                painter.fillRect(rect, self.ALT_ROW_BG)
            painter.setPen(QPen(self.GRID_COLOR, 0))
            painter.drawRect(rect)
            painter.setPen(self.ROW_TEXT)
            text_rect = rect.adjusted(cell_pad_x, 0, -cell_pad_x, 0)
            raw_text = str(values[column] if column < len(values) else "")
            text = metrics.elidedText(
                raw_text, Qt.ElideRight, max(10, text_rect.width())
            )
            painter.drawText(
                text_rect, self._column_alignment(column, numeric_columns), text
            )
            x += width
        painter.restore()

    def _print_header_text(self, column: int, header: str) -> str:
        if 0 <= int(column) < len(self._HEADER_FALLBACKS):
            return _(self._HEADER_FALLBACKS[int(column)])
        return self._normalize_header(header)
